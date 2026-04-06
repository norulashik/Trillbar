"""Module 3c — Script Alignment (optional).

Accepts a screenplay/script file and aligns its lines to transcribed segments
using Gemini.  Enriches segments with:
    - script_line: the matching dialogue from the script
    - stage_direction: any parenthetical acting notes (e.g. "(whispering)")
    - character_name: character name from the script

Supports simple formats:
    CHARACTER_NAME: dialogue text
    CHARACTER_NAME (stage direction): dialogue text
"""

import json
import logging
import re

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


# ─────────────────────────────────────────────────────────────────────────────
# Script parsing
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_LINE_RE = re.compile(
    r'^([A-Z][A-Z0-9_ ]+?)(?:\s*\(([^)]+)\))?\s*[:]\s*(.+)$'
)


def parse_script(script_text: str) -> list[dict]:
    """Parse a simple screenplay format into structured lines.

    Expected format:
        CHARACTER: dialogue text
        CHARACTER (whispering): dialogue text

    Returns:
        [{"character": str, "direction": str | None, "dialogue": str}]
    """
    lines = []
    for raw_line in script_text.strip().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        m = _SCRIPT_LINE_RE.match(raw_line)
        if m:
            lines.append({
                "character": m.group(1).strip(),
                "direction": m.group(2).strip() if m.group(2) else None,
                "dialogue": m.group(3).strip(),
            })
    logger.info("Parsed %d script lines.", len(lines))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Alignment via Gemini
# ─────────────────────────────────────────────────────────────────────────────

def align_script_to_segments(
    segments: list[Segment],
    script_lines: list[dict],
) -> list[Segment]:
    """Use Gemini to align script lines to transcribed segments.

    Each segment gets enriched with script_line, stage_direction,
    and character_name from the best-matching script line.
    """
    if not script_lines or not segments:
        return segments

    # Build prompt data
    seg_data = [
        {"id": s["id"], "text": s.get("source_text", ""), "speaker": s.get("speaker_id", "")}
        for s in segments if s.get("source_text")
    ]
    script_data = [
        {"idx": i, "character": sl["character"], "dialogue": sl["dialogue"],
         "direction": sl.get("direction", "")}
        for i, sl in enumerate(script_lines)
    ]

    prompt = (
        "You are aligning a screenplay script to transcribed audio segments.\n\n"
        "Match each transcribed segment to its corresponding script line based on "
        "semantic similarity of the dialogue text. Not every segment may have a match.\n\n"
        "Return JSON: an object mapping segment id to script line index.\n"
        'Example: {"0": 2, "3": 5}\n'
        "Only include segments that have a confident match.\n\n"
        f"Transcribed segments:\n{json.dumps(seg_data, ensure_ascii=False)}\n\n"
        f"Script lines:\n{json.dumps(script_data, ensure_ascii=False)}"
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=config.GEMINI_TRANSLATE_MODEL,
            contents=prompt,
            config={"temperature": 0.1, "max_output_tokens": 1000},
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        mapping = json.loads(raw)
    except Exception as e:
        logger.warning("Script alignment failed: %s", e)
        return segments

    # Enrich segments
    result = []
    for seg in segments:
        new_seg = dict(seg)
        seg_id_str = str(seg["id"])
        if seg_id_str in mapping:
            script_idx = int(mapping[seg_id_str])
            if 0 <= script_idx < len(script_lines):
                sl = script_lines[script_idx]
                new_seg["script_line"] = sl["dialogue"]
                new_seg["stage_direction"] = sl.get("direction", "")
                new_seg["character_name"] = sl["character"]
        result.append(new_seg)

    matched = sum(1 for s in result if s.get("script_line"))
    logger.info("Script alignment: %d/%d segments matched.", matched, len(result))
    return result
