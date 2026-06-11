"""Module 2b — Transcription + Speaker Diarization via AssemblyAI.

Uses the AssemblyAI REST API directly (bypassing the SDK) because the SDK
v0.64.x sends the deprecated `speech_model` field; the API now requires
`speech_models` as a list with values "universal-3-pro" or "universal-2".
"""

import logging
import time
from pathlib import Path

import requests

from backend import config
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

_BASE = "https://api.assemblyai.com/v2"


def _headers() -> dict:
    return {"authorization": config.ASSEMBLYAI_API_KEY}


def _upload(audio_path: str) -> str:
    """Upload a local file to AssemblyAI CDN, return the hosted URL."""
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{_BASE}/upload",
            headers=_headers(),
            data=f,
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()["upload_url"]


def _submit(audio_url: str) -> str:
    """Submit a transcription job, return the transcript ID."""
    payload = {
        "audio_url": audio_url,
        "speech_models": ["universal-3-pro"],
        "speaker_labels": True,
        "language_detection": True,
    }
    resp = requests.post(
        f"{_BASE}/transcript",
        headers={**_headers(), "content-type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _poll(transcript_id: str, poll_interval: float = 3.0, timeout: float = 600.0) -> dict:
    """Poll until the transcript is complete, return the full result dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{_BASE}/transcript/{transcript_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "completed":
            return data
        if status == "error":
            raise RuntimeError(f"AssemblyAI transcription failed: {data.get('error')}")
        time.sleep(poll_interval)
    raise TimeoutError(f"AssemblyAI transcription timed out after {timeout}s")


def transcribe_and_diarize(
    audio_path: str | Path,
    vocals_path: str | Path | None = None,
    audio_16k_path: str | Path | None = None,
    vocals_16k_path: str | Path | None = None,
) -> list[Segment]:
    """Transcribe audio and identify speakers via AssemblyAI REST API.

    Prefers vocals_path (voice-isolated) over audio_path for cleaner ASR.

    Returns:
        List of Segment dicts with: id, speaker_id, start, end, duration,
        source_text, source_lang.
    """
    # Prefer 16k mono (smallest upload, same ASR quality) → fall back to vocals → full 44k
    transcribe_from = str(audio_16k_path or vocals_path or audio_path)
    logger.info("Uploading to AssemblyAI: %s", Path(transcribe_from).name)

    audio_url = _upload(transcribe_from)
    logger.info("Submitted upload → %s", audio_url)

    transcript_id = _submit(audio_url)
    logger.info("Transcription submitted → id=%s", transcript_id)

    data = _poll(transcript_id)

    utterances = data.get("utterances") or []
    if not utterances:
        logger.warning("No utterances returned — empty transcript.")
        return []

    detected_lang = data.get("language_code") or "en"

    segments: list[Segment] = []
    for i, utt in enumerate(utterances):
        text = (utt.get("text") or "").strip()
        if not text:
            continue
        start = utt["start"] / 1000.0
        end = utt["end"] / 1000.0
        seg: Segment = {
            "id": i,
            "speaker_id": f"SPEAKER_{utt['speaker']}",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "source_text": text,
            "source_lang": detected_lang,
        }
        segments.append(seg)

    speakers = list({s["speaker_id"] for s in segments})
    logger.info(
        "Transcription complete: %d segments, lang=%s, speakers=%s",
        len(segments), detected_lang, speakers,
    )
    return segments


def convert_vocals_to_16k(vocals_44k_path: str | Path, job_id: str = "default") -> Path:
    """No-op kept for call-site compatibility. AssemblyAI handles any sample rate."""
    return Path(vocals_44k_path)
