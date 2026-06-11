"""Module 7 — Quality Assessment and Feedback Loop.

Scores each synthesised segment using:
  1. Heuristic MOS estimator — runs in-process, no model download.
     Uses SNR estimate, spectral flatness, clipping rate, and HNR proxy.
  2. (Optional) Gemini audio critique — sends synth + source audio to
     Gemini for a structured naturalness and emotion-match assessment.

Populates 'mos_score' (1–5), 'quality_notes', and 'needs_regen' on each segment.
"""

import base64
import json
import logging
from pathlib import Path

import numpy as np

from backend import config
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def run_quality_check(
    segments: list[Segment],
    use_gemini: bool = False,
    mos_threshold: float = 3.5,
    job_id: str = "default",
) -> list[Segment]:
    """Score all segments; flag those below mos_threshold as needs_regen."""
    import librosa

    result = []
    for seg in segments:
        audio_path = (
            seg.get("processed_audio_path")
            or seg.get("matched_audio_path")
            or seg.get("adjusted_audio_path")
            or seg.get("synth_audio_path")
        )
        new_seg = dict(seg)

        if not audio_path or not Path(audio_path).exists():
            new_seg["mos_score"] = 0.0
            new_seg["quality_notes"] = "No audio file found."
            new_seg["needs_regen"] = True
            result.append(new_seg)
            continue

        try:
            audio, sr = librosa.load(audio_path, sr=None, mono=True)
            heuristic_mos = score_segment_heuristic(audio, sr)
        except Exception as e:
            logger.debug("Heuristic scoring failed for segment %d: %s", seg["id"], e)
            heuristic_mos = 2.5

        mos = heuristic_mos
        notes = _mos_to_notes(heuristic_mos)

        if use_gemini and config.QUALITY_CHECK_GEMINI:
            try:
                gemini_result = score_segment_gemini(
                    synth_audio_path=audio_path,
                    source_audio_path=seg.get("source_audio_path"),
                    translated_text=seg.get("translated_text", ""),
                    client=_get_client(),
                )
                # Blend heuristic and Gemini scores (60/40)
                mos = 0.6 * heuristic_mos + 0.4 * gemini_result.get("mos_score", heuristic_mos)
                if gemini_result.get("quality_notes"):
                    notes = gemini_result["quality_notes"]
            except Exception as e:
                logger.debug("Gemini quality check failed for segment %d: %s", seg["id"], e)

        new_seg["mos_score"] = round(mos, 2)
        new_seg["quality_notes"] = notes
        new_seg["needs_regen"] = mos < mos_threshold
        result.append(new_seg)

    flagged = sum(1 for s in result if s.get("needs_regen"))
    logger.info(
        "Quality check complete: %d segments, %d below threshold (MOS < %.1f).",
        len(result), flagged, mos_threshold,
    )
    return result


def score_segment_heuristic(audio: np.ndarray, sr: int) -> float:
    """Estimate MOS (1–5) from signal features. No model download required.

    Features used:
      - SNR estimate (10th/90th percentile frame energy ratio)
      - Spectral flatness (low = tonal speech-like = good)
      - Clipping rate (fraction of samples at ±1.0)
      - HNR proxy via autocorrelation peak in pitch range
    """
    import librosa

    if len(audio) < 100:
        return 1.0

    audio = audio.astype(np.float32)

    # 1. Clipping rate
    clip_rate = float(np.mean(np.abs(audio) > 0.99))
    clip_score = max(0.0, 1.0 - clip_rate * 20.0)

    # 2. Spectral flatness (lower = more speech-like)
    try:
        flat = float(np.mean(librosa.feature.spectral_flatness(y=audio)))
        flat_score = max(0.0, 1.0 - flat * 4.0)
    except Exception:
        flat_score = 0.5

    # 3. SNR via frame energy distribution
    frame_size = max(1, int(sr * 0.010))
    energies = []
    for i in range(0, len(audio) - frame_size, frame_size):
        frame = audio[i : i + frame_size]
        energies.append(float(np.mean(frame ** 2)) + 1e-12)
    if len(energies) >= 4:
        energies_db = 10.0 * np.log10(np.array(energies))
        noise_db = float(np.percentile(energies_db, 10))
        signal_db = float(np.percentile(energies_db, 90))
        snr_db = signal_db - noise_db
        snr_score = max(0.0, min(1.0, (snr_db - 10.0) / 20.0))
    else:
        snr_score = 0.5

    # 4. HNR proxy via autocorrelation in pitch range
    try:
        ac = np.correlate(audio[:min(len(audio), sr)], audio[:min(len(audio), sr)], mode="full")
        ac = ac[len(ac) // 2 :]
        if ac[0] > 0:
            ac_norm = ac / ac[0]
            min_lag = max(1, int(sr / 600))
            max_lag = min(len(ac_norm) - 1, int(sr / 50))
            if min_lag < max_lag:
                hnr_score = float(np.clip(np.max(ac_norm[min_lag:max_lag]), 0.0, 1.0))
            else:
                hnr_score = 0.5
        else:
            hnr_score = 0.5
    except Exception:
        hnr_score = 0.5

    combined = (
        0.30 * snr_score
        + 0.25 * flat_score
        + 0.25 * hnr_score
        + 0.20 * clip_score
    )
    return round(1.0 + combined * 4.0, 2)


def score_segment_gemini(
    synth_audio_path: str,
    source_audio_path: str | None,
    translated_text: str,
    client,
) -> dict:
    """Send synth (+ optionally source) audio to Gemini for quality critique.

    Returns:
        {
            "mos_score": float,       # Gemini's 1–5 estimate
            "naturalness": float,     # 0–1
            "emotion_match": float,   # 0–1
            "quality_notes": str,
        }
    """
    parts = []

    if source_audio_path and Path(source_audio_path).exists():
        src_bytes = _read_audio_bytes(source_audio_path)
        if src_bytes:
            parts.append({
                "inline_data": {
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(src_bytes).decode(),
                }
            })

    synth_bytes = _read_audio_bytes(synth_audio_path)
    if not synth_bytes:
        return {"mos_score": 2.5, "quality_notes": "Could not read audio."}

    parts.append({
        "inline_data": {
            "mime_type": "audio/wav",
            "data": base64.b64encode(synth_bytes).decode(),
        }
    })

    context = f'Dubbed text: "{translated_text}"' if translated_text else ""
    prompt = (
        "You are a professional dubbing quality evaluator.\n\n"
        + (
            "The first audio clip is the original source dialogue. "
            "The second is the AI-dubbed version.\n\n"
            if source_audio_path
            else "The audio clip is an AI-dubbed dialogue segment.\n\n"
        )
        + f"{context}\n\n"
        "Rate the dubbed audio on these criteria and return ONLY valid JSON:\n"
        '  "mos_score": float 1–5 (overall quality)\n'
        '  "naturalness": float 0–1 (how human does it sound)\n'
        '  "emotion_match": float 0–1 (does dubbed emotion match source)\n'
        '  "quality_notes": one sentence describing the main quality issue, if any\n\n'
        'Example: {"mos_score":3.8,"naturalness":0.75,"emotion_match":0.7,'
        '"quality_notes":"Slight over-compression flattens dynamics in the middle phrase."}'
    )
    parts.append({"text": prompt})

    response = client.models.generate_content(
        model=config.GEMINI_AUDIO_MODEL,
        contents=[{"parts": parts}],
        config={"temperature": 0.2, "max_output_tokens": 300},
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    parsed = json.loads(raw)
    return {
        "mos_score": max(1.0, min(5.0, float(parsed.get("mos_score", 3.0)))),
        "naturalness": max(0.0, min(1.0, float(parsed.get("naturalness", 0.5)))),
        "emotion_match": max(0.0, min(1.0, float(parsed.get("emotion_match", 0.5)))),
        "quality_notes": str(parsed.get("quality_notes", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mos_to_notes(mos: float) -> str:
    if mos >= 4.5:
        return "Excellent quality."
    if mos >= 4.0:
        return "Good quality — minor naturalness issues."
    if mos >= 3.5:
        return "Acceptable — some synthetic character audible."
    if mos >= 2.5:
        return "Below average — robotic or unnatural segments detected."
    return "Poor quality — consider re-synthesis."


def _read_audio_bytes(audio_path: str, max_seconds: float = 10.0) -> bytes | None:
    try:
        import soundfile as sf
        import io

        audio, sr = sf.read(audio_path, always_2d=False)
        max_samples = int(max_seconds * sr)
        if len(audio) > max_samples:
            audio = audio[:max_samples]
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()
    except Exception:
        return None
