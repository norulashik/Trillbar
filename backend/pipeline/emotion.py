"""Module 3b — Emotion Analysis via Gemini LLM.

Two modes:
  1. Audio-based (GEMINI_AUDIO_EMOTION=true, default):
     Sends the actual source WAV for each segment to Gemini 2.5 Flash.
     Returns richer vocal_character, speaking_rate_wpm, and a 2–3 sentence
     acting direction grounded in the real vocal performance.

  2. Text-only fallback (GEMINI_AUDIO_EMOTION=false):
     Analyses source_text with surrounding context.
     Used when source_audio_path is unavailable or audio analysis fails.

Both paths populate:
    - emotion: str
    - emotion_intensity: float (0–1)
    - delivery_direction: str
    - vocal_character: str
    - speaking_rate_wpm: float
    - source_f0_mean: float  (extracted from WAV via librosa, not LLM)
"""

import base64
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from google import genai

from backend import config
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


VALID_EMOTIONS = {"happy", "angry", "sad", "neutral", "fear", "surprise", "disgust", "calm", "excited"}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_emotions_with_audio(
    segments: list[Segment],
    job_id: str = "default",
) -> list[Segment]:
    """Analyze emotion using source WAV + text via Gemini multimodal.

    For segments with source_audio_path, sends the WAV to Gemini and
    receives a rich vocal analysis. Falls back to text-only for segments
    without audio or when audio analysis fails.

    Processes segments concurrently (max 3 parallel Gemini calls).
    """
    if not segments:
        return segments

    # Split into audio-capable and text-only groups
    with_audio = [s for s in segments if s.get("source_audio_path") and
                  Path(s["source_audio_path"]).exists()]
    without_audio = [s for s in segments if s not in with_audio]

    results: dict[int, dict] = {}

    # Process audio segments concurrently
    if with_audio:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_analyze_segment_with_audio, seg): seg["id"]
                for seg in with_audio
            }
            for future in as_completed(futures):
                seg_id = futures[future]
                try:
                    results[seg_id] = future.result()
                except Exception as e:
                    logger.warning("Audio analysis failed for segment %d: %s", seg_id, e)
                    results[seg_id] = {}

    # Process text-only segments in batch
    if without_audio:
        texts_with_context = []
        for i, seg in enumerate(segments):
            if seg["id"] not in results:
                text = seg.get("source_text", "").strip()
                prev_text = segments[i - 1].get("source_text", "") if i > 0 else ""
                next_text = segments[i + 1].get("source_text", "") if i < len(segments) - 1 else ""
                texts_with_context.append({
                    "id": seg["id"],
                    "text": text,
                    "prev": prev_text[:100],
                    "next": next_text[:100],
                })
        if texts_with_context:
            try:
                batch_results = _batch_emotion_analysis(texts_with_context)
                results.update(batch_results)
            except Exception as e:
                logger.warning("Text-only emotion batch failed: %s", e)

    # Merge results back into segments
    result_segs = []
    for seg in segments:
        new_seg = dict(seg)
        em = results.get(seg["id"], {})
        new_seg["emotion"] = em.get("emotion", "neutral")
        new_seg["emotion_intensity"] = em.get("intensity", 0.5)
        new_seg["delivery_direction"] = em.get("direction", "")
        new_seg["vocal_character"] = em.get("vocal_character", "")
        new_seg["speaking_rate_wpm"] = float(em.get("speaking_rate_wpm", 0.0))
        # Compute F0 from the source WAV (more accurate than LLM estimate)
        if new_seg.get("source_audio_path"):
            new_seg["source_f0_mean"] = _extract_mean_f0(new_seg["source_audio_path"])
        result_segs.append(new_seg)

    non_neutral = [s for s in result_segs if s.get("emotion", "neutral") != "neutral"]
    logger.info(
        "Emotion analysis (audio) complete: %d segments, %d non-neutral.",
        len(result_segs), len(non_neutral),
    )
    return result_segs


def analyze_emotions(segments: list[Segment]) -> list[Segment]:
    """Text-only emotion analysis using Gemini (original implementation).

    Kept as fallback when GEMINI_AUDIO_EMOTION=false or audio unavailable.
    """
    if not segments:
        return segments

    texts_with_context = []
    for i, seg in enumerate(segments):
        text = seg.get("source_text", "").strip()
        if not text:
            texts_with_context.append({"id": seg["id"], "text": "", "context": ""})
            continue
        prev_text = segments[i - 1].get("source_text", "") if i > 0 else ""
        next_text = segments[i + 1].get("source_text", "") if i < len(segments) - 1 else ""
        entry = {
            "id": seg["id"],
            "text": text,
            "prev": prev_text[:100],
            "next": next_text[:100],
        }
        if seg.get("stage_direction"):
            entry["stage_direction"] = seg["stage_direction"]
        if seg.get("script_line"):
            entry["script_context"] = seg["script_line"][:150]
        texts_with_context.append(entry)

    try:
        emotion_map = _batch_emotion_analysis(texts_with_context)
    except Exception as e:
        logger.warning("Emotion analysis failed, defaulting to neutral: %s", e)
        emotion_map = {}

    result = []
    for seg in segments:
        new_seg = dict(seg)
        em = emotion_map.get(seg["id"], {})
        new_seg["emotion"] = em.get("emotion", "neutral")
        new_seg["emotion_intensity"] = em.get("intensity", 0.5)
        new_seg["delivery_direction"] = em.get("direction", "")
        new_seg["vocal_character"] = ""
        new_seg["speaking_rate_wpm"] = 0.0
        result.append(new_seg)

    detected = [s["emotion"] for s in result if s.get("emotion") != "neutral"]
    logger.info(
        "Emotion analysis (text) complete: %d segments, %d non-neutral.",
        len(result), len(detected),
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Audio-based analysis (single segment)
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_segment_with_audio(seg: Segment) -> dict:
    """Send source WAV + text to Gemini; return emotion analysis dict."""
    audio_path = seg["source_audio_path"]
    text = seg.get("source_text", "")

    # Read WAV — cap at 10s (~880KB at 44.1kHz mono) to stay well within limits
    audio_bytes = _load_audio_bytes(audio_path, max_seconds=10.0)
    if not audio_bytes:
        raise ValueError("Could not read audio file")

    b64_audio = base64.b64encode(audio_bytes).decode()

    prompt = (
        "You are a professional dubbing director analysing a dialogue segment.\n\n"
        f'Transcript: "{text}"\n\n'
        "Listen to the attached audio clip and return a JSON object with these fields:\n"
        '  "emotion": one of: happy, angry, sad, neutral, fear, surprise, calm, excited, disgust\n'
        '  "intensity": float 0.0 (barely noticeable) to 1.0 (extreme)\n'
        '  "vocal_character": short description of voice quality (e.g. "raspy, fast, mid-range")\n'
        '  "speaking_rate_wpm": estimated words per minute as integer\n'
        '  "direction": 2–3 sentence acting direction for the voice actor, describing '
        "emotional arc, pace, and delivery. Ground it in what you hear, not just the text.\n\n"
        "Respond with ONLY valid JSON. Example:\n"
        '{"emotion":"angry","intensity":0.8,"vocal_character":"tense, clipped, low pitch",'
        '"speaking_rate_wpm":145,"direction":"The actor delivers the line with barely '
        'controlled fury. Words are clipped short, especially at consonants. The voice '
        'drops slightly at the end, as if exhausted by the effort of restraint."}'
    )

    client = _get_client()
    response = client.models.generate_content(
        model=config.GEMINI_AUDIO_MODEL,
        contents=[
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/wav",
                            "data": b64_audio,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        config={"temperature": 0.2, "max_output_tokens": 600},
    )

    raw = response.text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    parsed = json.loads(raw)

    emotion = parsed.get("emotion", "neutral").lower().strip()
    if emotion not in VALID_EMOTIONS:
        emotion = "neutral"
    intensity = max(0.0, min(1.0, float(parsed.get("intensity", 0.5))))
    direction = str(parsed.get("direction", ""))
    vocal_character = str(parsed.get("vocal_character", ""))
    wpm = float(parsed.get("speaking_rate_wpm", 0))

    # Small polite delay to avoid hitting rate limits
    time.sleep(0.1)

    return {
        "emotion": emotion,
        "intensity": intensity,
        "direction": direction,
        "vocal_character": vocal_character,
        "speaking_rate_wpm": wpm,
    }


def _load_audio_bytes(audio_path: str, max_seconds: float = 10.0) -> bytes | None:
    """Load WAV and trim to max_seconds. Returns raw WAV bytes."""
    try:
        import soundfile as sf
        import io
        import numpy as np

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
    except Exception as e:
        logger.debug("Could not load audio %s: %s", audio_path, e)
        return None


def _extract_mean_f0(audio_path: str) -> float:
    """Extract mean F0 from a WAV using librosa.yin."""
    try:
        import librosa
        audio, sr = librosa.load(audio_path, sr=None, mono=True)
        if len(audio) < int(sr * 0.05):
            return 0.0
        f0 = librosa.yin(
            audio,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C7"),
            sr=sr,
        )
        voiced = f0[f0 > 0]
        return float(np.median(voiced)) if len(voiced) > 0 else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Text-only batch analysis (original, kept as fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _batch_emotion_analysis(segments_data: list[dict]) -> dict[int, dict]:
    """Call Gemini once with all segments (text only). Returns {seg_id: analysis}."""
    non_empty = [s for s in segments_data if s.get("text")]
    if not non_empty:
        return {}

    seg_lines = []
    for s in non_empty:
        seg_lines.append(
            f'  {{"id": {s["id"]}, "text": {json.dumps(s["text"])}, '
            f'"prev": {json.dumps(s.get("prev", ""))}, '
            f'"next": {json.dumps(s.get("next", ""))}}}'
        )
    segments_json = "[\n" + ",\n".join(seg_lines) + "\n]"

    prompt = (
        "You are an emotion analysis expert for film/TV dubbing.\n\n"
        "Analyse each dialogue segment below and classify its emotional tone.\n"
        "Consider the text content, the surrounding context (prev/next lines), "
        "and how an actor would deliver this line.\n\n"
        "For each segment, return:\n"
        '- "emotion": one of: happy, angry, sad, neutral, fear, surprise, calm, excited, disgust\n'
        '- "intensity": float 0.0 (barely noticeable) to 1.0 (extreme)\n'
        '- "direction": a 1–2 sentence acting direction for the voice actor\n\n'
        "Respond with ONLY valid JSON — an object mapping segment id to its analysis.\n"
        'Example: {"0": {"emotion": "angry", "intensity": 0.7, '
        '"direction": "Rising frustration, clipped words"}}\n\n'
        f"Segments:\n{segments_json}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model=config.GEMINI_TRANSLATE_MODEL,
        contents=prompt,
        config={"temperature": 0.2, "max_output_tokens": 2000},
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    parsed = json.loads(raw)

    result = {}
    for seg_id_str, data in parsed.items():
        seg_id = int(seg_id_str)
        emotion = data.get("emotion", "neutral").lower().strip()
        if emotion not in VALID_EMOTIONS:
            emotion = "neutral"
        intensity = max(0.0, min(1.0, float(data.get("intensity", 0.5))))
        direction = str(data.get("direction", ""))
        result[seg_id] = {
            "emotion": emotion,
            "intensity": intensity,
            "direction": direction,
            "vocal_character": "",
            "speaking_rate_wpm": 0.0,
        }

    return result
