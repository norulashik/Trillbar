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
        "target_language": job["target_language"],
        "input_file": job["input_file"],
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
        }
        for s in job["segments"]
    ]
    return {"job_id": job_id, "segments": segments}


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok", "version": "0.1.0"}


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
        )
        jobs[job_id]["status"] = "done"
        jobs[job_id]["output_path"] = str(result["output_path"])
        jobs[job_id]["segments"] = result["segments"]
        jobs[job_id]["duration"] = result["duration"]
        jobs[job_id]["elapsed"] = result["elapsed"]
        jobs[job_id]["progress"] = 100

    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
