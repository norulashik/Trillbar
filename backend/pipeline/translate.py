"""Module 3 — Translation & Script Generation.

Uses Google Gemini to translate each segment from the source language into the
target language (Hindi / Tamil / Telugu).

Key feature: isochrony-aware prompting — the model is instructed to keep
the translation short enough to be spoken within the original segment's
duration budget, which reduces the need for aggressive time-stretching later.
"""

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
            raise RuntimeError(
                "GEMINI_API_KEY is not set in .env. "
                "Get one at https://aistudio.google.com/app/apikey"
            )
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def translate_segments(
    segments: list[Segment],
    target_language: str,
    source_language: str | None = None,
) -> list[Segment]:
    """Translate source_text in each segment to target_language.

    Args:
        segments: Output from transcribe_and_diarize().
        target_language: One of 'hindi', 'tamil', 'telugu'.
        source_language: Override detected language (e.g. 'Japanese').
                         If None, uses the source_lang field in segments.

    Returns:
        Same list of segments with 'translated_text' and 'target_lang' added.
    """
    if target_language not in config.LANGUAGE_CONFIGS:
        raise ValueError(
            f"Unsupported target language: {target_language}. "
            f"Choose from: {config.SUPPORTED_LANGUAGES}"
        )

    lang_cfg = config.LANGUAGE_CONFIGS[target_language]
    lang_display = lang_cfg["display"]

    logger.info(
        "Translating %d segments → %s via Gemini (%s)",
        len(segments),
        lang_display,
        config.GEMINI_TRANSLATE_MODEL,
    )

    translated = []
    for seg in segments:
        src_lang = source_language or seg.get("source_lang", "the source language")
        translated_text = _translate_one(
            text=seg["source_text"],
            src_lang=src_lang,
            tgt_lang=lang_display,
            duration_budget=seg["duration"],
            emotion=seg.get("emotion"),
            emotion_intensity=seg.get("emotion_intensity"),
            delivery_direction=seg.get("delivery_direction"),
        )
        new_seg = dict(seg)
        new_seg["translated_text"] = translated_text
        new_seg["target_lang"] = target_language
        translated.append(new_seg)
        logger.debug(
            "[%s → %s] %r → %r",
            seg.get("speaker_id", "?"),
            lang_display,
            seg["source_text"][:60],
            translated_text[:60],
        )

    logger.info("Translation complete.")
    return translated


def _translate_one(
    text: str,
    src_lang: str,
    tgt_lang: str,
    duration_budget: float,
    emotion: str | None = None,
    emotion_intensity: float | None = None,
    delivery_direction: str | None = None,
) -> str:
    """Translate a single text string with isochrony and emotion awareness."""
    emotion_hint = ""
    if emotion and emotion != "neutral":
        parts = [f"- Emotional tone: {emotion}"]
        if emotion_intensity is not None:
            parts[0] += f" (intensity {emotion_intensity:.1f}/1.0)"
        if delivery_direction:
            parts.append(f"- Delivery: {delivery_direction}")
        parts.append(
            "- Match this emotional register in the translation: "
            "angry → sharper/clipped phrasing, sad → softer/longer expressions, "
            "happy → upbeat/energetic phrasing."
        )
        emotion_hint = "\n".join(parts) + "\n"

    prompt = (
        f"You are a professional dubbing script translator specialising in "
        f"translating {src_lang} content into {tgt_lang} for Indian OTT platforms.\n\n"
        f"Rules:\n"
        f"- Output ONLY the translated text — no explanations, no romanisation, no notes.\n"
        f"- Keep it natural and spoken, not literal or subtitle-style.\n"
        f"- Culturally adapt for an Indian audience.\n"
        f"- The translation MUST be speakable in under {duration_budget:.1f} seconds "
        f"(time budget). Prefer concise phrasing.\n"
        f"- Preserve the emotional tone of the original.\n"
        f"{emotion_hint}\n"
        f"Time budget: {duration_budget:.1f} seconds\n"
        f"Source ({src_lang}):\n{text}\n\n"
        f"Translation ({tgt_lang}):"
    )

    client = _get_client()
    response = client.models.generate_content(
        model=config.GEMINI_TRANSLATE_MODEL,
        contents=prompt,
        config={
            "temperature": 0.3,
            "max_output_tokens": 300,
        },
    )
    return response.text.strip()
