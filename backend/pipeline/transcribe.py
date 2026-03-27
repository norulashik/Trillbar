"""Module 2b — ASR + Speaker Diarization.

Uses:
  - faster-whisper  (base model, CPU) — transcription with word-level timestamps
  - pyannote-audio  (CPU) — speaker diarization

The two outputs are merged: each Whisper segment gets assigned a speaker ID
by finding the diarization turn that covers the majority of its time span.

If HUGGINGFACE_TOKEN is not set, diarization is skipped and all segments
are assigned to SPEAKER_00.
"""

import logging
from pathlib import Path

from backend import config
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)


def transcribe_and_diarize(
    audio_16k_path: str | Path,
    vocals_16k_path: str | Path | None = None,
) -> list[Segment]:
    """Transcribe and diarize audio.

    Args:
        audio_16k_path: 16 kHz mono WAV of the full audio (for diarization).
        vocals_16k_path: 16 kHz mono WAV of the vocals-only stem (for ASR).
                         If None, uses audio_16k_path for ASR too.

    Returns:
        List of Segment dicts with: id, speaker_id, start, end, duration, source_text, source_lang.
    """
    asr_path = str(vocals_16k_path or audio_16k_path)
    diar_path = str(audio_16k_path)

    logger.info("Running Whisper ASR on: %s", asr_path)
    whisper_segments, detected_lang = _run_whisper(asr_path)

    if config.HUGGINGFACE_TOKEN:
        logger.info("Running pyannote diarization on: %s", diar_path)
        diar_turns = _run_diarization(diar_path)
    else:
        logger.warning(
            "HUGGINGFACE_TOKEN not set — skipping diarization. "
            "All segments assigned to SPEAKER_00."
        )
        diar_turns = []

    segments = _merge(whisper_segments, diar_turns, detected_lang)
    logger.info(
        "Transcription complete: %d segments, lang=%s, speakers=%s",
        len(segments),
        detected_lang,
        list({s["speaker_id"] for s in segments}),
    )
    return segments


# ── Whisper ───────────────────────────────────────────────────────────────────

def _run_whisper(audio_path: str) -> tuple[list[dict], str]:
    """Return list of {start, end, text} dicts and detected language."""
    from faster_whisper import WhisperModel

    model = WhisperModel(
        config.WHISPER_MODEL,
        device="cpu",
        compute_type="int8",   # fastest on CPU
    )
    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,       # skip silence
        vad_parameters={"min_silence_duration_ms": 500},
    )

    results = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        results.append({
            "start": seg.start,
            "end": seg.end,
            "text": text,
        })

    detected_lang = info.language
    return results, detected_lang


# ── Pyannote Diarization ──────────────────────────────────────────────────────

def _run_diarization(audio_path: str) -> list[dict]:
    """Return list of {start, end, speaker} dicts."""
    from pyannote.audio import Pipeline
    import torch

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=config.HUGGINGFACE_TOKEN,
    )
    # Force CPU
    pipeline.to(torch.device("cpu"))

    diarization = pipeline(audio_path)

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker,
        })
    return turns


# ── Merge Whisper + Diarization ───────────────────────────────────────────────

def _merge(
    whisper_segs: list[dict],
    diar_turns: list[dict],
    lang: str,
) -> list[Segment]:
    """Assign a speaker_id to each Whisper segment."""
    segments: list[Segment] = []

    for i, ws in enumerate(whisper_segs):
        speaker_id = _find_speaker(ws["start"], ws["end"], diar_turns)
        duration = ws["end"] - ws["start"]
        seg: Segment = {
            "id": i,
            "speaker_id": speaker_id,
            "start": round(ws["start"], 3),
            "end": round(ws["end"], 3),
            "duration": round(duration, 3),
            "source_text": ws["text"],
            "source_lang": lang,
        }
        segments.append(seg)

    return segments


def _find_speaker(start: float, end: float, diar_turns: list[dict]) -> str:
    """Find the speaker that covers the most of the [start, end] interval."""
    if not diar_turns:
        return "SPEAKER_00"

    best_speaker = "SPEAKER_00"
    best_overlap = 0.0

    for turn in diar_turns:
        overlap = max(0, min(end, turn["end"]) - max(start, turn["start"]))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn["speaker"]

    return best_speaker


# ── Vocals → 16 kHz mono helper ───────────────────────────────────────────────

def convert_vocals_to_16k(vocals_44k_path: str | Path, job_id: str = "default") -> Path:
    """Downsample the vocals stem to 16 kHz mono for ASR."""
    import subprocess

    vocals_44k_path = Path(vocals_44k_path)
    out_path = config.TEMP_DIR / job_id / "stems" / "vocals_16k.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        return out_path

    from backend.pipeline.ingest import _ffmpeg_bin
    cmd = [
        _ffmpeg_bin(), "-y",
        "-i", str(vocals_44k_path),
        "-ar", "16000",
        "-ac", "1",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg downsampling failed:\n{result.stderr}")

    return out_path
