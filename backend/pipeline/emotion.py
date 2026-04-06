"""Module 3b — Emotion Analysis via Gemini LLM.

Analyses each segment's source_text (with surrounding context) to detect
the emotional tone.  Populates:
    - emotion: str       (e.g. "happy", "angry", "sad", "neutral")
    - emotion_intensity: float (0.0–1.0)
    - delivery_direction: str  (natural-language acting note)

Uses a single batched Gemini call for efficiency.
"""

import json
import logging

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


def analyze_emotions(segments: list[Segment]) -> list[Segment]:
    """Detect emotion for every segment using Gemini.

    Returns the same segments list with emotion fields populated.
    Gracefully falls back to 'neutral' on any error.
    """
    if not segments:
        return segments

    texts_with_context = []
    for i, seg in enumerate(segments):
        text = seg.get("source_text", "").strip()
        if not text:
            texts_with_context.append({"id": seg["id"], "text": "", "context": ""})
            continue
        # Include previous and next segment text as context
        prev_text = segments[i - 1].get("source_text", "") if i > 0 else ""
        next_text = segments[i + 1].get("source_text", "") if i < len(segments) - 1 else ""
        entry = {
            "id": seg["id"],
            "text": text,
            "prev": prev_text[:100],
            "next": next_text[:100],
        }
        # Include script context if available (from script_align stage)
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
        result.append(new_seg)

    detected = [s["emotion"] for s in result if s.get("emotion") != "neutral"]
    logger.info(
        "Emotion analysis complete: %d segments, %d non-neutral.",
        len(result), len(detected),
    )
    return result


def _batch_emotion_analysis(segments_data: list[dict]) -> dict[int, dict]:
    """Call Gemini once with all segments, return {seg_id: {emotion, intensity, direction}}."""
    # Filter out empty text segments
    non_empty = [s for s in segments_data if s.get("text")]
    if not non_empty:
        return {}

    # Build segment list for prompt
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
        '- "direction": a short acting direction for the voice actor '
        '(e.g. "Speak with restrained anger", "Soft and tearful")\n\n'
        "Respond with ONLY valid JSON — an object mapping segment id to its analysis.\n"
        'Example: {"0": {"emotion": "angry", "intensity": 0.7, '
        '"direction": "Rising frustration, clipped words"}}\n\n'
        f"Segments:\n{segments_json}"
    )

    client = _get_client()
    response = client.models.generate_content(
        model=config.GEMINI_TRANSLATE_MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "max_output_tokens": 2000,
        },
    )

    raw = response.text.strip()
    # Strip markdown code fences if present
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
        result[seg_id] = {"emotion": emotion, "intensity": intensity, "direction": direction}

    return result
