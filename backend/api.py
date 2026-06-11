"""TrillBar FastAPI Backend.

Run with:
    uvicorn backend.api:app --reload --port 8005
"""

import asyncio
import json
import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from backend import config
from backend.jobs import create_job, get_job, update_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("trillbar.api")

app = FastAPI(
    title="TrillBar API",
    description="AI-powered multilingual dubbing workstation.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# SSE — Real-time job progress
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/events/{job_id}", summary="SSE stream for job progress")
async def job_events(job_id: str):
    async def stream():
        last_key = None
        ticks = 0

        while True:
            job = get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break

            key = (job["status"], job["stage"], job["progress"])
            if key != last_key:
                last_key = key
                event: dict = {
                    "status": job["status"],
                    "stage": job["stage"],
                    "progress": job["progress"],
                    "error": job.get("error"),
                }
                yield f"data: {json.dumps(event)}\n\n"

            if job["status"] in ("done", "error"):
                break

            await asyncio.sleep(0.5)
            ticks += 1
            if ticks % 60 == 0:  # heartbeat every 30 s to keep connection alive
                yield "data: {\"heartbeat\":true}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core dubbing endpoints
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# New two-phase endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/upload", summary="Upload file and preview — no pipeline started")
async def upload_file(
    file: UploadFile = File(...),
    mode: str = Form("translation"),
    target_language: str = Form("hindi"),
    skip_separation: bool = Form(False),
):
    import anyio

    job_id = uuid.uuid4().hex[:10]
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    src_ext = Path(file.filename).suffix.lower()
    is_video = src_ext in {".mp4", ".mkv", ".avi", ".mov", ".webm"}

    # Use a stable filename so /video endpoint always finds it
    save_name = f"source{src_ext}" if is_video else Path(file.filename).name
    upload_path = upload_dir / save_name

    # Stream file to disk off the event loop so TCP flow-control stays healthy
    async with await anyio.open_file(upload_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            await out.write(chunk)

    source_video_path = str(upload_path) if is_video else None

    create_job(job_id, mode, {
        "target_language": target_language,
        "input_file": file.filename,
        "skip_separation": skip_separation,
    })
    update_job(job_id,
        status="uploaded",
        stage="Uploaded",
        result={
            "input_path": str(upload_path),
            "is_video": is_video,
            "source_video_path": source_video_path,
        },
    )

    return {
        "job_id": job_id,
        "status": "uploaded",
        "is_video": is_video,
        "video_url": f"/video/{job_id}" if is_video else None,
    }


@app.post("/analyze/{job_id}", summary="Run Stage A: transcribe + diarize + emotion")
async def start_analysis(
    job_id: str,
    background_tasks: BackgroundTasks,
    skip_separation: bool = Form(False),
    trim_in: float = Form(0.0),
    trim_out: float = Form(0.0),
    keep_ranges: str = Form(None),
):
    import json as _json
    job = _require_job(job_id)
    if job["status"] != "uploaded":
        raise HTTPException(status_code=409, detail=f"Job must be in 'uploaded' state (current: {job['status']})")

    result = job["result"]
    input_path = result.get("input_path")
    if not input_path or not Path(input_path).exists():
        raise HTTPException(status_code=422, detail="Input file not found — re-upload required")

    parsed_ranges = None
    if keep_ranges:
        try:
            parsed_ranges = _json.loads(keep_ranges)
        except Exception:
            raise HTTPException(status_code=422, detail="keep_ranges must be valid JSON")

    update_job(job_id, status="analyzing", stage="Starting analysis")
    background_tasks.add_task(
        _run_analysis_bg_new, job_id, input_path, skip_separation, trim_in, trim_out, parsed_ranges
    )
    return {"job_id": job_id, "status": "analyzing"}


@app.post("/dub/{job_id}", summary="Run Stage B: translate + synthesize (Translation Dubbing)")
async def start_dub(
    job_id: str,
    background_tasks: BackgroundTasks,
    target_language: str = Form(None),
    skip_prosody: bool = Form(False),
    skip_acoustic: bool = Form(False),
):
    job = _require_job(job_id)
    if job["status"] != "analyzed":
        raise HTTPException(status_code=409, detail=f"Job must be in 'analyzed' state (current: {job['status']})")

    lang = target_language or job["params"].get("target_language", "hindi")
    if lang not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language '{lang}'")

    update_job(job_id, status="dubbing", stage="Starting dubbing")
    background_tasks.add_task(_run_dub_bg, job_id, lang, skip_prosody, skip_acoustic)
    return {"job_id": job_id, "status": "dubbing"}


@app.post("/voice-dub/{job_id}", summary="Run Stage B: STS per speaker (Voice Mode)")
async def start_voice_dub(
    job_id: str,
    background_tasks: BackgroundTasks,
    speaker_assignments: str = Form(...),
    dialogue_files: list[UploadFile] = File(...),
):
    """speaker_assignments: JSON string {speaker_id: voice_library_id}"""
    import json as _json
    job = _require_job(job_id)
    if job["status"] != "analyzed":
        raise HTTPException(status_code=409, detail=f"Job must be in 'analyzed' state (current: {job['status']})")

    assignments_raw = _json.loads(speaker_assignments)

    # Resolve voice_library_id → elevenlabs_voice_id
    from backend.jobs import get_voice
    voice_assignments: dict[str, str] = {}
    for speaker_id, lib_id in assignments_raw.items():
        entry = get_voice(lib_id)
        if not entry:
            raise HTTPException(status_code=422, detail=f"Voice library entry '{lib_id}' not found")
        voice_assignments[speaker_id] = entry["elevenlabs_id"]

    # Save dialogue files
    upload_dir = config.TEMP_DIR / job_id / "dialogues"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dialogue_paths: dict[str, str] = {}
    for dlg_file in dialogue_files:
        speaker_id = Path(dlg_file.filename).stem
        dlg_path = upload_dir / dlg_file.filename
        with open(dlg_path, "wb") as f:
            shutil.copyfileobj(dlg_file.file, f)
        dialogue_paths[speaker_id] = str(dlg_path)

    update_job(job_id, status="running", stage="Starting voice dub")
    background_tasks.add_task(_run_voice_dub_bg, job_id, voice_assignments, dialogue_paths)
    return {"job_id": job_id, "status": "running"}


@app.post("/dub", summary="Submit a dubbing job (legacy CLI path)")
async def submit_dub(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_language: str = Form(...),
    skip_separation: bool = Form(False),
    skip_prosody: bool = Form(False),
    skip_acoustic: bool = Form(False),
    script_text: str = Form(None),
):
    if target_language not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported language '{target_language}'. Choose from: {config.SUPPORTED_LANGUAGES}",
        )

    job_id = uuid.uuid4().hex[:10]
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / file.filename

    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    create_job(job_id, "dub", {
        "target_language": target_language,
        "input_file": file.filename,
        "skip_separation": skip_separation,
        "skip_prosody": skip_prosody,
        "skip_acoustic": skip_acoustic,
    })

    background_tasks.add_task(
        _run_pipeline_bg, job_id, upload_path,
        target_language, skip_separation, skip_prosody, skip_acoustic, script_text,
    )
    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}", summary="Poll job status")
async def get_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    params = job["params"]
    result = job["result"]
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "target_language": params.get("target_language"),
        "input_file": params.get("input_file"),
        "source_lang": result.get("source_lang"),
        "duration": result.get("duration"),
        "elapsed": result.get("elapsed"),
        "error": job.get("error"),
        "ready": job["status"] == "done",
        "is_video": result.get("is_video", False),
        "preview_url": f"/preview/{job['id']}" if result.get("preview_path") else None,
    }


@app.get("/download/{job_id}", summary="Download the dubbed audio")
async def download_audio(job_id: str):
    job = _require_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job not done yet (status: {job['status']})")
    output_path = Path(job["result"]["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    return FileResponse(str(output_path), media_type="audio/wav", filename=output_path.name)


@app.get("/transcript/{job_id}", summary="Get transcript JSON")
async def get_transcript(job_id: str):
    job = _require_job(job_id)
    segments = job["result"].get("segments")
    if not segments:
        raise HTTPException(status_code=409, detail="Transcript not available yet")

    serialised = []
    for i, s in enumerate(segments):
        next_s = segments[i + 1] if i + 1 < len(segments) else None
        sync = _compute_sync_metrics(s)
        qc_flags = _compute_qc_flags(s, next_s, sync)
        serialised.append({
            "id": s.get("id"),
            "speaker_id": s.get("speaker_id"),
            "start": s.get("start"),
            "end": s.get("end"),
            "source_text": s.get("source_text"),
            "translated_text": s.get("translated_text"),
            "emotion": s.get("emotion"),
            "emotion_intensity": s.get("emotion_intensity"),
            "delivery_direction": s.get("delivery_direction"),
            "vocal_character": s.get("vocal_character"),
            "speaking_rate_wpm": s.get("speaking_rate_wpm"),
            "source_f0_mean": s.get("source_f0_mean"),
            "voice_id": s.get("voice_id"),
            "pedalboard_params": s.get("pedalboard_params"),
            "mos_score": s.get("mos_score"),
            "quality_notes": s.get("quality_notes"),
            "needs_regen": s.get("needs_regen"),
            "dubbed_duration_s": s.get("dubbed_duration_s"),
            "lip_sync_score": sync["lip_sync_score"],
            "pace_ratio": sync["pace_ratio"],
            "pace_ok": sync["pace_ok"],
            "suggested_offset_ms": sync.get("suggested_offset_ms"),
            "qc_flags": qc_flags,
            "qc_flagged": len(qc_flags) > 0,
        })

    return {"job_id": job_id, "segments": serialised}


@app.get("/export/mp4/{job_id}", summary="Download dubbed video as MP4")
async def export_mp4(job_id: str):
    job = _require_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job not done yet")
    path = job["result"].get("preview_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Preview video not available — job may not have video input")
    return FileResponse(
        path, media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="dubbed_{job_id}.mp4"'},
    )


@app.get("/export/srt/{job_id}", summary="Download dubbed subtitles as SRT")
async def export_srt(job_id: str):
    from backend.utils.timing import segments_to_srt
    job = _require_job(job_id)
    segments = job["result"].get("segments")
    if not segments:
        raise HTTPException(status_code=409, detail="Transcript not available yet")
    # Adjust timestamps for any applied clip offsets
    adjusted = []
    for s in segments:
        if (s.get("clip") or {}).get("muted"):
            continue
        offset_s = float((s.get("clip") or {}).get("offset_ms", 0)) / 1000.0
        adjusted.append({**s, "start": s["start"] + offset_s, "end": s["end"] + offset_s})
    from fastapi.responses import Response as _Response
    content = segments_to_srt(adjusted, use_translated=True)
    return _Response(
        content=content, media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="dubbed_{job_id}.srt"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Voice Library
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/voice-library", summary="List all saved voices")
async def list_voice_library():
    from backend.jobs import list_voices
    return list_voices()


@app.post("/voice-library", summary="Clone a voice and save to library")
async def add_to_voice_library(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    job_id: str = Form(None),
    speaker_id: str = Form(None),
):
    """Clone a voice from one or more uploaded files OR a speaker from an existing analyzed job."""
    import uuid as _uuid
    from backend.jobs import create_voice_entry
    from backend.pipeline import synthesize, ingest

    entry_id = _uuid.uuid4().hex[:10]
    ref_dir = config.VOICE_PROFILES_DIR / entry_id
    ref_dir.mkdir(parents=True, exist_ok=True)

    if files:
        # External upload path — supports multiple reference files
        # Full cleaning chain: isolate vocals → denoise → trim silence → normalize
        from backend.pipeline import separation as _sep
        from backend.utils.audio import (
            load_audio, save_audio, stereo_to_mono,
            reduce_noise_spectral, trim_silence, strip_internal_silence, normalize_peak,
        )

        ref_wavs: list[str] = []
        for i, upload_file in enumerate(files):
            ref_path = ref_dir / upload_file.filename
            with open(ref_path, "wb") as f:
                shutil.copyfileobj(upload_file.file, f)

            # Step 1: Extract / convert to 44.1 kHz WAV (handles video + any audio format)
            file_job = f"{entry_id}_ref{i}"
            audio_paths = ingest.extract_audio(str(ref_path), job_id=file_job)
            raw_wav = str(audio_paths["full_44k"])

            # Step 2: ElevenLabs Audio Isolation — strips background music and SFX
            logger.info("Isolating vocals for cloning: %s", Path(raw_wav).name)
            stems = _sep.separate_stems(raw_wav, job_id=file_job)
            isolated_path = str(stems["vocals"])

            # Step 3: Local cleaning — denoise, trim silence, normalize
            audio, sr = load_audio(isolated_path)
            audio = stereo_to_mono(audio)
            audio = reduce_noise_spectral(audio, sr)
            audio = trim_silence(audio, sr, top_db=25)
            audio = strip_internal_silence(audio, sr, top_db=25)
            audio = normalize_peak(audio, target_db=-3.0)

            if len(audio) < int(sr * 1.0):
                logger.warning("File %d too short after cleaning — using isolated (uncleaned) audio", i)
                audio, sr = load_audio(isolated_path)
                audio = stereo_to_mono(audio)
                audio = normalize_peak(audio, target_db=-3.0)

            clean_path = ref_dir / f"ref_clean_{i:02d}.wav"
            save_audio(audio, clean_path, sr)
            ref_wavs.append(str(clean_path))
            logger.info("Cleaned reference %d ready: %.1f s", i, len(audio) / sr)

        ref_audio_path = ref_wavs[0]

    elif job_id and speaker_id:
        # Slice from existing analyzed job
        job = _require_job(job_id)
        if job["status"] not in ("analyzed", "done"):
            raise HTTPException(status_code=409, detail="Job must be analyzed or done to extract speaker audio")
        segments = job["result"].get("segments", [])
        speaker_segs = [s for s in segments if s.get("speaker_id") == speaker_id]
        if not speaker_segs:
            raise HTTPException(status_code=404, detail=f"Speaker '{speaker_id}' not found in job")
        ref_paths = [s["source_audio_path"] for s in speaker_segs if s.get("source_audio_path") and Path(s["source_audio_path"]).exists()]
        if not ref_paths:
            raise HTTPException(status_code=422, detail="No source audio extracted for this speaker yet")
        ref_wavs = ref_paths[:config.MAX_REF_CHUNKS]
        ref_audio_path = ref_paths[0]

    else:
        raise HTTPException(status_code=422, detail="Provide either 'files' or 'job_id' + 'speaker_id'")

    # Clone voice with all reference files
    voice_id_el = synthesize.clone_voice_from_audio(ref_wavs, speaker_id=entry_id)
    if not voice_id_el:
        raise HTTPException(status_code=502, detail="Voice cloning failed — check ElevenLabs credits and API key")

    entry = create_voice_entry(entry_id, name, voice_id_el, ref_audio_path)
    return {"id": entry_id, "name": name, "elevenlabs_id": voice_id_el, "created_at": entry["created_at"]}


@app.delete("/voice-library/{entry_id}", summary="Delete a voice from library")
async def delete_from_voice_library(entry_id: str):
    from backend.jobs import get_voice, delete_voice
    from backend.pipeline.synthesize import cleanup_cloned_voices
    entry = get_voice(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Voice not found")
    cleanup_cloned_voices({entry_id: {"voice_id": entry["elevenlabs_id"]}})
    delete_voice(entry_id)
    return {"deleted": entry_id}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/languages")
async def get_languages():
    return {"languages": list(config.SUPPORTED_LANGUAGES)}


# ─────────────────────────────────────────────────────────────────────────────
# Voice Artist
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/voice-artist", summary="Submit a voice artist job")
async def submit_voice_artist(
    background_tasks: BackgroundTasks,
    actor_files: list[UploadFile] = File(...),
    dialogue: UploadFile = File(...),
):
    job_id = uuid.uuid4().hex[:10]
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    actor_paths = []
    for af in actor_files:
        ap = upload_dir / f"actor_{af.filename}"
        with open(ap, "wb") as f:
            shutil.copyfileobj(af.file, f)
        actor_paths.append(str(ap))

    dlg_path = upload_dir / f"dialogue_{dialogue.filename}"
    with open(dlg_path, "wb") as f:
        shutil.copyfileobj(dialogue.file, f)

    create_job(job_id, "voice-artist", {"input_file": dialogue.filename})
    background_tasks.add_task(_run_voice_artist_bg, job_id, actor_paths, str(dlg_path))
    return {"job_id": job_id, "status": "queued"}


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Character
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/analyze-characters", summary="Detect characters in source video")
async def analyze_characters_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    skip_separation: bool = Form(False),
    script_text: str = Form(None),
):
    job_id = uuid.uuid4().hex[:10]
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / file.filename

    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    create_job(job_id, "analyze-characters", {"input_file": file.filename})
    background_tasks.add_task(_run_analysis_bg, job_id, upload_path, skip_separation, script_text)
    return {"job_id": job_id, "status": "queued"}


@app.get("/characters/{job_id}", summary="Get detected characters")
async def get_characters(job_id: str):
    job = _require_job(job_id)
    characters = job["result"].get("characters")
    if not characters:
        raise HTTPException(status_code=409, detail="Character analysis not complete yet")
    return {"job_id": job_id, "characters": characters}


@app.post("/synthesize-characters/{job_id}", summary="Convert per-character dialogue")
async def synthesize_characters_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
    dialogues: list[UploadFile] = File(...),
):
    job = _require_job(job_id)
    if not job["result"].get("analysis_result"):
        raise HTTPException(status_code=409, detail="Run /analyze-characters first")

    upload_dir = config.TEMP_DIR / job_id / "user_dialogues"
    upload_dir.mkdir(parents=True, exist_ok=True)

    character_dialogues: dict[str, str] = {}
    for dlg_file in dialogues:
        speaker_id = Path(dlg_file.filename).stem
        dlg_path = upload_dir / dlg_file.filename
        with open(dlg_path, "wb") as f:
            shutil.copyfileobj(dlg_file.file, f)
        character_dialogues[speaker_id] = str(dlg_path)

    background_tasks.add_task(_run_synthesis_bg, job_id, character_dialogues)
    update_job(job_id, status="synthesizing")
    return {"job_id": job_id, "status": "synthesizing", "characters": list(character_dialogues.keys())}


@app.get("/character-preview/{job_id}/{speaker_id}")
async def get_character_preview(job_id: str, speaker_id: str):
    job = _require_job(job_id)
    for ch in job["result"].get("characters", []):
        if ch.get("speaker_id") == speaker_id and ch.get("preview_path"):
            p = Path(ch["preview_path"])
            if p.exists():
                return FileResponse(str(p), media_type="audio/wav", filename=p.name)
    raise HTTPException(status_code=404, detail="Preview not found")


@app.get("/download-character/{job_id}/{speaker_id}")
async def download_character_audio(job_id: str, speaker_id: str):
    job = _require_job(job_id)
    char_path = job["result"].get("per_character", {}).get(speaker_id)
    if not char_path:
        raise HTTPException(status_code=404, detail="Character output not found")
    p = Path(char_path)
    if not p.exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    return FileResponse(str(p), media_type="audio/wav", filename=p.name)


# ─────────────────────────────────────────────────────────────────────────────
# Background runners
# ─────────────────────────────────────────────────────────────────────────────

def _progress_fn(job_id: str):
    def _progress(stage: str, pct: float):
        update_job(job_id, stage=stage, progress=int(pct))
        logger.info("[job=%s | %3d%%] %s", job_id, int(pct), stage)
    return _progress


def _run_analysis_bg_new(
    job_id: str, input_path: str, skip_separation: bool,
    trim_in: float = 0.0, trim_out: float = 0.0,
    keep_ranges: list | None = None,
) -> None:
    from backend.main import run_analysis_pipeline
    try:
        result = run_analysis_pipeline(
            input_file=input_path,
            job_id=job_id,
            skip_separation=skip_separation,
            trim_in=trim_in,
            trim_out=trim_out,
            keep_ranges=keep_ranges,
            progress_callback=_progress_fn(job_id),
        )
        update_job(job_id, status="analyzed", progress=100, result={
            "segments": result["segments"],
            "stems_vocals_path": result.get("stems_vocals_path"),
            "stems_no_vocals_path": result.get("stems_no_vocals_path"),
            "duration": result["duration"],
            "is_video": result["is_video"],
            "source_video_path": result.get("source_video_path"),
            "source_lang": result.get("source_lang"),
            "elapsed_analysis": result["elapsed"],
            "keep_ranges": parsed_ranges,
        })
    except Exception as e:
        logger.exception("Analysis failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


def _run_dub_bg(job_id: str, target_language: str, skip_prosody: bool, skip_acoustic: bool) -> None:
    from backend.main import run_dub_from_analysis
    job = get_job(job_id)
    result = job["result"]
    try:
        dub_result = run_dub_from_analysis(
            job_id=job_id,
            segments=result["segments"],
            stems_vocals_path=result.get("stems_vocals_path"),
            stems_no_vocals_path=result.get("stems_no_vocals_path"),
            total_duration=result["duration"],
            target_language=target_language,
            skip_prosody=skip_prosody,
            skip_acoustic=skip_acoustic,
            output_filename=f"dubbed_{job_id}.wav",
            progress_callback=_progress_fn(job_id),
        )
        preview_path = _mux_preview_video(
            result.get("source_video_path"),
            str(dub_result["output_path"]),
            job_id,
            keep_ranges=result.get("keep_ranges"),
        )
        update_job(job_id, status="done", progress=100, result={
            "output_path": str(dub_result["output_path"]),
            "segments": dub_result["segments"],
            "voice_profiles": dub_result.get("voice_profiles", {}),
            "elapsed": dub_result["elapsed"],
            "source_lang": dub_result.get("source_lang"),
            "preview_path": str(preview_path) if preview_path else None,
            "no_vocals_path": result.get("stems_no_vocals_path"),
        })
    except Exception as e:
        logger.exception("Dub failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


def _run_voice_dub_bg(
    job_id: str,
    voice_assignments: dict[str, str],
    dialogue_paths: dict[str, str],
) -> None:
    from backend.main import run_voice_dub_from_analysis
    job = get_job(job_id)
    result = job["result"]
    try:
        dub_result = run_voice_dub_from_analysis(
            job_id=job_id,
            segments=result["segments"],
            stems_no_vocals_path=result.get("stems_no_vocals_path"),
            total_duration=result["duration"],
            voice_assignments=voice_assignments,
            dialogue_paths=dialogue_paths,
            output_filename=f"voiced_{job_id}.wav",
            progress_callback=_progress_fn(job_id),
        )
        preview_path = _mux_preview_video(
            result.get("source_video_path"),
            str(dub_result["output_path"]),
            job_id,
            keep_ranges=result.get("keep_ranges"),
        )
        update_job(job_id, status="done", progress=100, result={
            "output_path": str(dub_result["output_path"]),
            "segments": dub_result["segments"],
            "elapsed": dub_result["elapsed"],
            "preview_path": str(preview_path) if preview_path else None,
        })
    except Exception as e:
        logger.exception("Voice dub failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


def _run_pipeline_bg(
    job_id: str, input_path: Path, target_language: str,
    skip_separation: bool, skip_prosody: bool, skip_acoustic: bool,
    script_text: str | None,
) -> None:
    from backend.main import run_pipeline
    update_job(job_id, status="running")
    try:
        result = run_pipeline(
            input_file=str(input_path),
            target_language=target_language,
            job_id=job_id,
            skip_separation=skip_separation,
            skip_prosody=skip_prosody,
            skip_acoustic=skip_acoustic,
            output_filename=f"dubbed_{job_id}.wav",
            progress_callback=_progress_fn(job_id),
            script_text=script_text,
        )
        # Mux preview video if input was a video file
        preview_path = _mux_preview_video(
            result.get("source_video_path"),
            str(result["output_path"]),
            job_id,
        )

        update_job(
            job_id,
            status="done", progress=100,
            result={
                "output_path": str(result["output_path"]),
                "segments": result["segments"],
                "voice_profiles": result.get("voice_profiles", {}),
                "duration": result["duration"],
                "elapsed": result["elapsed"],
                "source_lang": result.get("source_lang"),
                "is_video": result.get("is_video", False),
                "source_video_path": result.get("source_video_path"),
                "preview_path": str(preview_path) if preview_path else None,
            },
        )
    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


def _run_voice_artist_bg(job_id: str, actor_paths: list[str], dialogue_path: str) -> None:
    from backend.main import run_voice_artist_pipeline
    update_job(job_id, status="running")
    try:
        result = run_voice_artist_pipeline(
            actor_video=actor_paths,
            dialogue_audio=dialogue_path,
            job_id=job_id,
            output_filename=f"voice_artist_{job_id}.wav",
            progress_callback=_progress_fn(job_id),
        )
        update_job(
            job_id,
            status="done", progress=100,
            result={
                "output_path": str(result["output_path"]),
                "duration": result["duration"],
                "elapsed": result["elapsed"],
            },
        )
    except Exception as e:
        logger.exception("Voice artist pipeline failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


def _run_analysis_bg(
    job_id: str, input_path: Path, skip_separation: bool, script_text: str | None,
) -> None:
    from backend.main import analyze_characters
    update_job(job_id, status="analyzing")
    try:
        result = analyze_characters(
            source_video=str(input_path),
            job_id=job_id,
            skip_separation=skip_separation,
            progress_callback=_progress_fn(job_id),
            script_text=script_text,
        )
        update_job(
            job_id,
            status="analyzed", progress=100,
            result={
                "characters": result["characters"],
                "segments": result["segments"],
                "analysis_result": result,
                "duration": result["total_duration"],
            },
        )
    except Exception as e:
        logger.exception("Analysis failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


def _run_synthesis_bg(job_id: str, character_dialogues: dict[str, str]) -> None:
    from backend.main import synthesize_characters
    update_job(job_id, status="synthesizing")
    try:
        job = get_job(job_id)
        analysis_result = job["result"]["analysis_result"]
        result = synthesize_characters(
            job_id=job_id,
            character_dialogues=character_dialogues,
            analysis_result=analysis_result,
            progress_callback=_progress_fn(job_id),
        )
        update_job(
            job_id,
            status="done", progress=100,
            result={
                "per_character": result["per_character"],
                "elapsed": result["elapsed"],
            },
        )
    except Exception as e:
        logger.exception("Synthesis failed for job %s", job_id)
        update_job(job_id, status="error", error=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Video + preview serving
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/video/{job_id}", summary="Stream original source video")
async def get_source_video(job_id: str):
    job = _require_job(job_id)
    path = job["result"].get("source_video_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="No source video for this job")
    suffix = Path(path).suffix.lower()
    media_type = "video/mp4" if suffix == ".mp4" else "video/x-matroska" if suffix == ".mkv" else "video/webm"
    return FileResponse(path, media_type=media_type)


@app.get("/preview/{job_id}", summary="Stream dubbed video (video + dubbed audio muxed)")
async def get_preview_video(job_id: str):
    job = _require_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job not done yet")
    path = job["result"].get("preview_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Preview video not available")
    return FileResponse(path, media_type="video/mp4")


@app.post("/reassemble/{job_id}", summary="Re-assemble with updated clip timings (no re-synthesis)")
async def reassemble(job_id: str, body: dict):
    """Re-mix the final audio/video using updated clip offsets.

    Body: {clips: {str(segment_id): {offset_ms: int, muted: bool}}}
    Returns: {output_url, preview_url}
    """
    job = _require_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job not done yet")

    result = job["result"]
    segments = [dict(s) for s in result.get("segments", [])]
    clips: dict = body.get("clips", {})

    # Apply clip overrides to working copies of segments
    for seg in segments:
        clip_override = clips.get(str(seg.get("id")))
        if clip_override:
            seg["clip"] = {
                "offset_ms":     clip_override.get("offset_ms", 0),
                "muted":         clip_override.get("muted", False),
                "gain_db":       clip_override.get("gain_db", 0.0),
                "stretch_ratio": clip_override.get("stretch_ratio", 1.0),
                "trim_in_ms":    clip_override.get("trim_in_ms", 0),
                "trim_out_ms":   clip_override.get("trim_out_ms", 0),
            }
        if seg.get("clip", {}).get("muted"):
            seg["_skip"] = True

    active_segments = [s for s in segments if not s.get("_skip")]

    try:
        from backend.pipeline import assemble as _assemble
        from backend import config as _cfg

        out_filename = f"dubbed_{job_id}_reassembled.wav"
        out_path = _assemble.assemble_output(
            segments=active_segments,
            no_vocals_path=result.get("no_vocals_path"),
            total_duration=result["duration"],
            job_id=job_id,
            output_filename=out_filename,
        )

        # Update stored segments with new dubbed_duration_s values (set by assemble)
        seg_by_id = {s.get("id"): s for s in active_segments}
        stored_segs = result.get("segments", [])
        for stored in stored_segs:
            updated = seg_by_id.get(stored.get("id"))
            if updated and "dubbed_duration_s" in updated:
                stored["dubbed_duration_s"] = updated["dubbed_duration_s"]
            if updated and "clip" in updated:
                stored["clip"] = updated["clip"]

        result["output_path"] = str(out_path)
        result["segments"] = stored_segs

        # Re-mux preview video if source video exists
        preview_path = _mux_preview_video(
            result.get("source_video_path"),
            str(out_path),
            job_id,
            suffix="_reassembled",
        )
        if preview_path:
            result["preview_path"] = str(preview_path)

        update_job(job_id, result=result)

        return {
            "output_url": f"/download/{job_id}",
            "preview_url": f"/preview/{job_id}" if preview_path else None,
        }

    except Exception as e:
        logger.exception("Reassemble failed for job=%s", job_id)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# AI Lip Sync (SyncLabs)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/lipsync/{job_id}", summary="Submit AI lip sync job to SyncLabs")
async def submit_lipsync(job_id: str, background_tasks: BackgroundTasks):
    """Send original video + dubbed audio to SyncLabs for lip sync processing.

    Requires SYNCLABS_API_KEY and SYNCLABS_PUBLIC_BASE_URL to be set in .env.
    Returns {synclabs_job_id, status: 'submitted'}.
    """
    job = _require_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Dubbing job not done yet")

    result = job["result"]
    if not result.get("is_video"):
        raise HTTPException(status_code=422, detail="No source video for this job — lip sync requires video input")

    if not config.SYNCLABS_API_KEY:
        raise HTTPException(status_code=422, detail="SYNCLABS_API_KEY not configured")
    if not config.SYNCLABS_PUBLIC_BASE_URL:
        raise HTTPException(status_code=422, detail="SYNCLABS_PUBLIC_BASE_URL not configured — set to your ngrok/public URL")

    # Build publicly accessible URLs for SyncLabs to fetch
    video_url = f"{config.SYNCLABS_PUBLIC_BASE_URL}/api/video/{job_id}"
    audio_url = f"{config.SYNCLABS_PUBLIC_BASE_URL}/api/download/{job_id}"

    try:
        from backend.pipeline.lipsync import submit_lipsync_job
        synclabs_job_id = submit_lipsync_job(video_url, audio_url, config.SYNCLABS_API_KEY)
    except Exception as e:
        logger.exception("SyncLabs submission failed for job=%s", job_id)
        raise HTTPException(status_code=502, detail=f"SyncLabs error: {e}")

    # Store synclabs_job_id in our job result so we can poll later
    result["synclabs_job_id"] = synclabs_job_id
    result["synclabs_status"] = "processing"
    result["synclabs_result_url"] = None
    update_job(job_id, result=result)

    # Start background polling
    background_tasks.add_task(_poll_lipsync_bg, job_id, synclabs_job_id)

    return {"synclabs_job_id": synclabs_job_id, "status": "submitted"}


@app.get("/lipsync/{job_id}/status", summary="Poll AI lip sync status")
async def get_lipsync_status(job_id: str):
    """Returns current SyncLabs processing status for this job.

    status: 'not_started' | 'processing' | 'done' | 'failed'
    When done, lipsync_url points to the synced video served from our backend.
    """
    job = _require_job(job_id)
    result = job["result"]
    synclabs_status = result.get("synclabs_status")

    if not synclabs_status:
        return {"status": "not_started"}

    return {
        "status": synclabs_status,
        "synclabs_job_id": result.get("synclabs_job_id"),
        "lipsync_url": f"/lipsync/{job_id}/video" if synclabs_status == "done" else None,
    }


@app.get("/lipsync/{job_id}/video", summary="Serve AI lip-synced video")
async def get_lipsync_video(job_id: str):
    job = _require_job(job_id)
    result = job["result"]
    path = result.get("synclabs_local_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Lip-synced video not ready yet")
    return FileResponse(path, media_type="video/mp4")


def _poll_lipsync_bg(job_id: str, synclabs_job_id: str) -> None:
    """Background task: poll SyncLabs until done, download result, update job."""
    import urllib.request

    try:
        from backend.pipeline.lipsync import wait_for_lipsync
        output_url = wait_for_lipsync(synclabs_job_id, config.SYNCLABS_API_KEY, timeout=600.0)

        # Download the result video locally
        local_path = config.OUTPUT_DIR / f"lipsync_{job_id}.mp4"
        urllib.request.urlretrieve(output_url, str(local_path))
        logger.info("SyncLabs result downloaded to %s", local_path)

        job = get_job(job_id)
        result = job["result"]
        result["synclabs_status"] = "done"
        result["synclabs_result_url"] = output_url
        result["synclabs_local_path"] = str(local_path)
        update_job(job_id, result=result)

    except Exception as e:
        logger.exception("SyncLabs polling failed for job=%s", job_id)
        job = get_job(job_id)
        result = job["result"]
        result["synclabs_status"] = "failed"
        result["synclabs_error"] = str(e)
        update_job(job_id, result=result)


# ─────────────────────────────────────────────────────────────────────────────
# Re-synthesis + per-segment audio preview
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/segment-audio/{job_id}/{segment_id}", summary="Serve processed segment WAV for preview")
async def get_segment_audio(job_id: str, segment_id: int):
    job = _require_job(job_id)
    segments = job["result"].get("segments", [])
    seg = next((s for s in segments if s.get("id") == segment_id), None)
    if not seg:
        raise HTTPException(status_code=404, detail="Segment not found")

    audio_path = (
        seg.get("processed_audio_path")
        or seg.get("matched_audio_path")
        or seg.get("adjusted_audio_path")
        or seg.get("synth_audio_path")
    )
    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(status_code=404, detail="Segment audio not found")

    return FileResponse(audio_path, media_type="audio/wav", filename=Path(audio_path).name)


@app.post("/resynthesize/{job_id}/{segment_id}", summary="Re-synthesize a single segment with updated parameters")
async def resynthesize_segment(job_id: str, segment_id: int, body: dict):
    """Re-run TTS → prosody → postprocess for a single segment.

    Body fields (all optional):
        emotion: str
        emotion_intensity: float
        translated_text: str
        pedalboard_params: dict
    """
    job = _require_job(job_id)
    result = job["result"]
    segments: list = result.get("segments", [])
    seg_idx = next((i for i, s in enumerate(segments) if s.get("id") == segment_id), None)
    if seg_idx is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    seg = dict(segments[seg_idx])

    # Apply overrides from body
    if "emotion" in body:
        seg["emotion"] = body["emotion"]
    if "emotion_intensity" in body:
        seg["emotion_intensity"] = float(body["emotion_intensity"])
    if "translated_text" in body:
        seg["translated_text"] = body["translated_text"]
    if "pedalboard_params" in body:
        seg["pedalboard_params"] = body["pedalboard_params"]

    voice_id = seg.get("voice_id") or (result.get("voice_profiles", {}).get(seg.get("speaker_id"), {}) or {}).get("voice_id")
    if not voice_id:
        raise HTTPException(status_code=422, detail="No voice_id available for this segment — cannot re-synthesize")

    try:
        from backend.pipeline import synthesize, prosody, postprocess, quality
        from backend.pipeline.quality import score_segment_heuristic
        import librosa

        # Re-synthesize TTS
        updated_segs = synthesize.synthesize_segments(
            [seg],
            {seg["speaker_id"]: {"voice_id": voice_id}},
            job["params"].get("target_language", "hindi"),
            job_id=job_id,
        )
        seg = updated_segs[0]

        # Prosody transfer
        updated_segs = prosody.apply_prosody_transfer([seg], job_id=job_id)
        seg = updated_segs[0]

        # Pedalboard chain
        updated_segs = postprocess.apply_pedalboard_chain([seg], job_id=job_id)
        seg = updated_segs[0]

        # Heuristic MOS score for the new audio
        audio_path = seg.get("processed_audio_path") or seg.get("adjusted_audio_path") or seg.get("synth_audio_path")
        if audio_path and Path(audio_path).exists():
            audio, sr = librosa.load(audio_path, sr=None, mono=True)
            seg["mos_score"] = round(score_segment_heuristic(audio, sr), 2)

        # Persist updated segment back into job result
        segments[seg_idx] = seg
        result["segments"] = segments
        update_job(job_id, result=result)

        return {
            "segment_id": segment_id,
            "mos_score": seg.get("mos_score"),
            "quality_notes": seg.get("quality_notes"),
            "audio_url": f"/segment-audio/{job_id}/{segment_id}",
        }

    except Exception as e:
        logger.exception("Re-synthesis failed for job=%s segment=%d", job_id, segment_id)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _compute_sync_metrics(s: dict) -> dict:
    src_start = s.get("start", 0.0)
    src_end = s.get("end", 0.0)
    src_dur = max(src_end - src_start, 0.001)
    clip = s.get("clip") or {}
    offset_s = float(clip.get("offset_ms", 0)) / 1000.0
    dub_dur = s.get("dubbed_duration_s") or src_dur
    dub_start = src_start + offset_s
    dub_end = dub_start + dub_dur
    overlap = max(0.0, min(src_end, dub_end) - max(src_start, dub_start))
    overlap_score = round(overlap / max(src_dur, dub_dur), 3)
    pace_ratio = round(dub_dur / src_dur, 3)
    return {
        "lip_sync_score": overlap_score,
        "pace_ratio": pace_ratio,
        "pace_ok": 0.8 <= pace_ratio <= 1.2,
    }


def _compute_qc_flags(s: dict, next_s: dict | None, sync: dict) -> list[str]:
    flags: list[str] = []
    if sync["lip_sync_score"] < 0.7:
        flags.append("sync_drift")
    pace = sync["pace_ratio"]
    if pace > 1.2:
        flags.append("pace_long")
    elif pace < 0.8:
        flags.append("pace_short")
    mos = s.get("mos_score")
    if mos is not None and mos < 3.0:
        flags.append("low_mos")
    if s.get("needs_regen"):
        flags.append("needs_regen")
    if next_s:
        dub_dur = s.get("dubbed_duration_s") or (s.get("end", 0) - s.get("start", 0))
        clip = s.get("clip") or {}
        offset_s = float(clip.get("offset_ms", 0)) / 1000.0
        dub_end = s.get("start", 0) + offset_s + dub_dur
        if dub_end > next_s.get("start", float("inf")) + 0.05:
            flags.append("overlap")
    return flags


def _mux_preview_video(
    source_video_path: str | None,
    dubbed_audio_path: str,
    job_id: str,
    suffix: str = "",
    keep_ranges: list | None = None,
) -> Path | None:
    """Mux original video + dubbed audio into preview MP4 using ffmpeg.

    When keep_ranges is set, the source video is trimmed to only those regions
    before muxing so the preview is aligned with the dubbed audio.
    """
    if not source_video_path or not Path(source_video_path).exists():
        return None
    try:
        from backend.pipeline.ingest import _ffmpeg_bin
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = config.OUTPUT_DIR / f"preview_{job_id}{suffix}.mp4"
        ffmpeg = _ffmpeg_bin()

        if keep_ranges and len(keep_ranges) > 0:
            # Build a trim + concat filter to extract only the kept regions
            # Each range becomes a [v][a] trimmed segment, then concat
            filter_parts = []
            concat_v = ""
            concat_a = ""
            for i, r in enumerate(keep_ranges):
                start = r["start"]
                end   = r["end"]
                filter_parts.append(
                    f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
                    f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
                )
                concat_v += f"[v{i}]"
                concat_a += f"[a{i}]"
            n = len(keep_ranges)
            filter_parts.append(f"{concat_v}{concat_a}concat=n={n}:v=1:a=1[vout][aout]")
            filter_str = ";".join(filter_parts)

            trimmed_path = config.OUTPUT_DIR / f"preview_{job_id}{suffix}_trimmed.mp4"
            trim_cmd = [
                ffmpeg, "-y", "-i", source_video_path,
                "-filter_complex", filter_str,
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                str(trimmed_path),
            ]
            res = subprocess.run(trim_cmd, capture_output=True, text=True, timeout=300)
            if res.returncode != 0:
                logger.warning("ffmpeg trim failed, falling back to full video: %s", res.stderr[-300:])
                trimmed_path = Path(source_video_path)
            video_for_mux = str(trimmed_path)
        else:
            video_for_mux = source_video_path

        cmd = [
            ffmpeg, "-y",
            "-i", video_for_mux,
            "-i", dubbed_audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            logger.info("Preview video muxed: %s", out_path)
            return out_path
        logger.warning("ffmpeg mux failed: %s", result.stderr[-500:])
    except Exception as e:
        logger.warning("Preview mux error (non-critical): %s", e)
    return None
