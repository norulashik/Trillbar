"""Timestamp and segment duration utilities."""

from __future__ import annotations
from typing import TypedDict


class Segment(TypedDict, total=False):
    id: int
    speaker_id: str
    start: float          # seconds
    end: float            # seconds
    duration: float       # seconds
    source_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    source_audio_path: str   # slice of dialogue stem for this segment
    synth_audio_path: str    # synthesised TTS output
    adjusted_audio_path: str # after prosody + acoustic adjustment
    matched_audio_path: str  # after acoustic matching
    processed_audio_path: str  # after pedalboard post-processing
    # Emotion fields (populated by emotion analysis stage)
    emotion: str             # "happy", "angry", "sad", "neutral", "fear", "surprise"
    emotion_intensity: float # 0.0 (mild) to 1.0 (extreme)
    delivery_direction: str  # natural-language TTS direction, e.g. "Speak with quiet anger"
    # Extended vocal analysis (populated by audio-based emotion stage)
    vocal_character: str     # e.g. "raspy, mid-range, fast delivery"
    speaking_rate_wpm: float # words per minute estimated from source audio
    source_f0_mean: float    # mean F0 in Hz extracted from source segment
    # Voice synthesis
    voice_id: str            # ElevenLabs voice_id used for this segment
    # Pedalboard post-processing params (AI-suggested, overridable per segment)
    pedalboard_params: dict
    # Quality assessment
    mos_score: float         # automated MOS estimate 1.0–5.0
    quality_notes: str       # human-readable quality critique
    needs_regen: bool        # True if quality below threshold
    # Character mapping
    character_name: str      # user-assigned name for this speaker


def segment_duration(seg: Segment) -> float:
    return seg.get("duration", seg["end"] - seg["start"])


def merge_short_segments(
    segments: list[Segment],
    min_duration: float = 0.5,
    gap_threshold: float = 0.3,
) -> list[Segment]:
    """Merge segments that are very short or have tiny gaps between them.

    This reduces the number of TTS API calls and improves prosody continuity.
    Only merges segments from the same speaker.
    """
    if not segments:
        return segments

    merged: list[Segment] = [segments[0].copy()]

    for seg in segments[1:]:
        prev = merged[-1]
        gap = seg["start"] - prev["end"]
        same_speaker = seg.get("speaker_id") == prev.get("speaker_id")
        prev_short = (prev["end"] - prev["start"]) < min_duration

        if same_speaker and (gap <= gap_threshold or prev_short):
            # Extend the previous segment
            prev["end"] = seg["end"]
            prev["duration"] = prev["end"] - prev["start"]
            prev["source_text"] = (prev.get("source_text", "") + " " + seg.get("source_text", "")).strip()
            prev["translated_text"] = (prev.get("translated_text", "") + " " + seg.get("translated_text", "")).strip()
        else:
            merged.append(seg.copy())

    # Re-index and fill duration
    for i, seg in enumerate(merged):
        seg["id"] = i
        seg["duration"] = seg["end"] - seg["start"]

    return merged


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm for debugging."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def segments_to_srt(segments: list[Segment], use_translated: bool = True) -> str:
    """Convert segments to SRT subtitle format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        text = seg.get("translated_text", "") if use_translated else seg.get("source_text", "")
        start = _srt_time(seg["start"])
        end = _srt_time(seg["end"])
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
