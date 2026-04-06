"""TrillBar FastAPI Backend.

Endpoints:
    POST /dub          — submit a dubbing job (file upload + language)
    GET  /status/{id}  — poll job status and progress
    GET  /download/{id} — download the finished audio file
    GET  /transcript/{id} — get the transcript JSON

Run with:
    python run_api.py  (runs on port 8005)
"""

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("trillbar.api")

app = FastAPI(
    title="TrillBar API",
    description="AI-powered multilingual dubbing for India's OTT era.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store (replace with Redis/DB for production) ────────────────
jobs: dict[str, dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/dub", summary="Submit a dubbing job")
async def submit_dub(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Video or audio file to dub"),
    target_language: str = Form(..., description="hindi | tamil | telugu"),
    skip_separation: bool = Form(False, description="Skip Demucs (fast mode)"),
    skip_prosody: bool = Form(False),
    skip_acoustic: bool = Form(False),
    script_text: str = Form(None, description="Optional screenplay text for emotion-aware dubbing"),
):
    if target_language not in config.SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported language '{target_language}'. Choose from: {config.SUPPORTED_LANGUAGES}",
        )

    job_id = uuid.uuid4().hex[:10]

    # Save upload to temp storage
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / file.filename

    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Initialise job entry
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "stage": "Queued",
        "progress": 0,
        "target_language": target_language,
        "input_file": file.filename,
        "output_path": None,
        "segments": None,
        "source_lang": None,
        "duration": None,
        "elapsed": None,
        "error": None,
    }

    background_tasks.add_task(
        _run_pipeline_background,
        job_id=job_id,
        input_path=upload_path,
        target_language=target_language,
        skip_separation=skip_separation,
        skip_prosody=skip_prosody,
        skip_acoustic=skip_acoustic,
        script_text=script_text,
    )

    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}", summary="Poll job status")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Return a clean status view (no raw paths)
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "target_language": job.get("target_language"),
        "input_file": job["input_file"],
        "source_lang": job.get("source_lang"),
        "duration": job["duration"],
        "elapsed": job["elapsed"],
        "error": job["error"],
        "ready": job["status"] == "done",
    }


@app.get("/download/{job_id}", summary="Download the dubbed audio")
async def download_audio(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job is not done yet (status: {job['status']})")
    output_path = Path(job["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    return FileResponse(
        path=str(output_path),
        media_type="audio/wav",
        filename=output_path.name,
    )


@app.get("/transcript/{job_id}", summary="Get transcript JSON")
async def get_transcript(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.get("segments"):
        raise HTTPException(status_code=409, detail="Transcript not available yet")
    # Return only the text-relevant fields
    segments = [
        {
            "id": s.get("id"),
            "speaker_id": s.get("speaker_id"),
            "start": s.get("start"),
            "end": s.get("end"),
            "source_text": s.get("source_text"),
            "translated_text": s.get("translated_text"),
            "emotion": s.get("emotion"),
            "emotion_intensity": s.get("emotion_intensity"),
            "delivery_direction": s.get("delivery_direction"),
        }
        for s in job["segments"]
    ]
    return {"job_id": job_id, "segments": segments}


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/languages", summary="Get supported languages")
async def get_languages():
    return {"languages": list(config.SUPPORTED_LANGUAGES)}


# ── Voice Artist Endpoint ───────────────────────────────────────────────────

@app.post("/voice-artist", summary="Submit a voice artist job")
async def submit_voice_artist(
    background_tasks: BackgroundTasks,
    actor_files: list[UploadFile] = File(..., description="Actor's video/audio files"),
    dialogue: UploadFile = File(..., description="Your dialogue recording"),
):
    job_id = uuid.uuid4().hex[:10]
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Save actor files
    actor_paths = []
    for af in actor_files:
        ap = upload_dir / f"actor_{af.filename}"
        with open(ap, "wb") as f:
            shutil.copyfileobj(af.file, f)
        actor_paths.append(str(ap))

    # Save dialogue file
    dlg_path = upload_dir / f"dialogue_{dialogue.filename}"
    with open(dlg_path, "wb") as f:
        shutil.copyfileobj(dialogue.file, f)

    jobs[job_id] = {
        "id": job_id, "status": "queued", "stage": "Queued", "progress": 0,
        "input_file": dialogue.filename, "output_path": None,
        "segments": None, "source_lang": None,
        "duration": None, "elapsed": None, "error": None,
    }

    background_tasks.add_task(
        _run_voice_artist_background, job_id=job_id,
        actor_paths=actor_paths, dialogue_path=str(dlg_path),
    )
    return {"job_id": job_id, "status": "queued"}


# ── Multi-Character Endpoints ────────────────────────────────────────────────

@app.post("/analyze-characters", summary="Analyse source video and detect characters")
async def analyze_characters_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Source video/audio to analyse"),
    skip_separation: bool = Form(False),
    script_text: str = Form(None, description="Optional screenplay text"),
):
    job_id = uuid.uuid4().hex[:10]
    upload_dir = config.TEMP_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / file.filename
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    jobs[job_id] = {
        "id": job_id, "status": "queued", "stage": "Queued", "progress": 0,
        "input_file": file.filename, "output_path": None, "segments": None,
        "characters": None, "analysis_result": None,
        "duration": None, "elapsed": None, "error": None,
    }

    background_tasks.add_task(
        _run_analysis_background, job_id=job_id,
        input_path=upload_path, skip_separation=skip_separation,
        script_text=script_text,
    )
    return {"job_id": job_id, "status": "queued"}


@app.get("/characters/{job_id}", summary="Get detected characters for a job")
async def get_characters(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.get("characters"):
        raise HTTPException(status_code=409, detail="Character analysis not complete yet")
    return {"job_id": job_id, "characters": job["characters"]}


@app.post("/synthesize-characters/{job_id}", summary="Convert per-character dialogue recordings")
async def synthesize_characters_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
    dialogues: list[UploadFile] = File(..., description="Dialogue files named as SPEAKER_XX.wav"),
):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.get("analysis_result"):
        raise HTTPException(status_code=409, detail="Run /analyze-characters first")

    upload_dir = config.TEMP_DIR / job_id / "user_dialogues"
    upload_dir.mkdir(parents=True, exist_ok=True)

    character_dialogues = {}
    for dlg_file in dialogues:
        # Expect filenames like SPEAKER_00.wav or user can name them
        speaker_id = Path(dlg_file.filename).stem
        dlg_path = upload_dir / dlg_file.filename
        with open(dlg_path, "wb") as f:
            shutil.copyfileobj(dlg_file.file, f)
        character_dialogues[speaker_id] = str(dlg_path)

    background_tasks.add_task(
        _run_synthesis_background, job_id=job_id,
        character_dialogues=character_dialogues,
    )
    job["status"] = "synthesizing"
    return {"job_id": job_id, "status": "synthesizing", "characters": list(character_dialogues.keys())}


# ─────────────────────────────────────────────────────────────────────────────
# Background pipeline runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline_background(
    job_id: str,
    input_path: Path,
    target_language: str,
    skip_separation: bool,
    skip_prosody: bool,
    skip_acoustic: bool,
    script_text: str | None = None,
) -> None:
    from backend.main import run_pipeline

    def _progress(stage: str, pct: float):
        jobs[job_id]["stage"] = stage
        jobs[job_id]["progress"] = int(pct)
        logger.info("[job=%s | %3d%%] %s", job_id, int(pct), stage)

    jobs[job_id]["status"] = "running"
    try:
        result = run_pipeline(
            input_file=str(input_path),
            target_language=target_language,
            job_id=job_id,
            skip_separation=skip_separation,
            skip_prosody=skip_prosody,
            skip_acoustic=skip_acoustic,
            output_filename=f"dubbed_{job_id}.wav",
            progress_callback=_progress,
            script_text=script_text,
        )
        jobs[job_id]["status"] = "done"
        jobs[job_id]["output_path"] = str(result["output_path"])
        jobs[job_id]["segments"] = result["segments"]
        jobs[job_id]["duration"] = result["duration"]
        jobs[job_id]["elapsed"] = result["elapsed"]
        jobs[job_id]["source_lang"] = result.get("source_lang")
        jobs[job_id]["progress"] = 100

    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def _run_analysis_background(
    job_id: str,
    input_path: Path,
    skip_separation: bool,
    script_text: str | None = None,
) -> None:
    from backend.main import analyze_characters

    def _progress(stage: str, pct: float):
        jobs[job_id]["stage"] = stage
        jobs[job_id]["progress"] = int(pct)

    jobs[job_id]["status"] = "analyzing"
    try:
        result = analyze_characters(
            source_video=str(input_path),
            job_id=job_id,
            skip_separation=skip_separation,
            progress_callback=_progress,
            script_text=script_text,
        )
        jobs[job_id]["status"] = "analyzed"
        jobs[job_id]["characters"] = result["characters"]
        jobs[job_id]["segments"] = result["segments"]
        jobs[job_id]["analysis_result"] = result
        jobs[job_id]["duration"] = result["total_duration"]
        jobs[job_id]["progress"] = 100
    except Exception as e:
        logger.exception("Analysis failed for job %s", job_id)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def _run_synthesis_background(
    job_id: str,
    character_dialogues: dict[str, str],
) -> None:
    from backend.main import synthesize_characters

    def _progress(stage: str, pct: float):
        jobs[job_id]["stage"] = stage
        jobs[job_id]["progress"] = int(pct)

    jobs[job_id]["status"] = "synthesizing"
    try:
        result = synthesize_characters(
            job_id=job_id,
            character_dialogues=character_dialogues,
            analysis_result=jobs[job_id]["analysis_result"],
            progress_callback=_progress,
        )
        jobs[job_id]["status"] = "done"
        jobs[job_id]["per_character"] = result["per_character"]
        jobs[job_id]["elapsed"] = result["elapsed"]
        jobs[job_id]["progress"] = 100
    except Exception as e:
        logger.exception("Synthesis failed for job %s", job_id)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


def _run_voice_artist_background(
    job_id: str,
    actor_paths: list[str],
    dialogue_path: str,
) -> None:
    from backend.main import run_voice_artist_pipeline

    def _progress(stage: str, pct: float):
        jobs[job_id]["stage"] = stage
        jobs[job_id]["progress"] = int(pct)
        logger.info("[job=%s | %3d%%] %s", job_id, int(pct), stage)

    jobs[job_id]["status"] = "running"
    try:
        result = run_voice_artist_pipeline(
            actor_video=actor_paths,
            dialogue_audio=dialogue_path,
            job_id=job_id,
            output_filename=f"voice_artist_{job_id}.wav",
            progress_callback=_progress,
        )
        jobs[job_id]["status"] = "done"
        jobs[job_id]["output_path"] = str(result["output_path"])
        jobs[job_id]["duration"] = result["duration"]
        jobs[job_id]["elapsed"] = result["elapsed"]
        jobs[job_id]["progress"] = 100
    except Exception as e:
        logger.exception("Voice artist pipeline failed for job %s", job_id)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


# ── Character Audio Endpoints ───────────────────────────────────────────────

@app.get("/character-preview/{job_id}/{speaker_id}", summary="Get character preview audio")
async def get_character_preview(job_id: str, speaker_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    characters = job.get("characters", [])
    for ch in characters:
        if ch.get("speaker_id") == speaker_id and ch.get("preview_path"):
            preview = Path(ch["preview_path"])
            if preview.exists():
                return FileResponse(str(preview), media_type="audio/wav", filename=preview.name)
    raise HTTPException(status_code=404, detail="Preview not found")


@app.get("/download-character/{job_id}/{speaker_id}", summary="Download per-character output")
async def download_character_audio(job_id: str, speaker_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    per_char = job.get("per_character", {})
    char_path = per_char.get(speaker_id)
    if not char_path:
        raise HTTPException(status_code=404, detail="Character output not found")
    p = Path(char_path)
    if not p.exists():
        raise HTTPException(status_code=500, detail="Output file missing")
    return FileResponse(str(p), media_type="audio/wav", filename=p.name)
