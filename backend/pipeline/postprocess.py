"""Module 5c — Parametric Post-Processing Chain (Spotify Pedalboard).

Applies per-segment studio-quality audio processing:
  - High-pass filter    — remove sub-80 Hz rumble
  - Low-shelf cut       — reduce mud at 200 Hz
  - Presence boost      — +3 dB at 3 kHz for speech intelligibility
  - Compressor          — 3:1 with fast attack
  - Optional reverb     — room-matched from source RT60 estimate
  - Limiter             — -1 dBFS hard ceiling

All parameters are AI-suggested (per emotion) but are stored on each
segment as 'pedalboard_params' so the frontend can override them.
"""

import logging
from pathlib import Path

import numpy as np

from backend import config
from backend.utils.audio import load_audio, save_audio
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)


# ── Default parameters ────────────────────────────────────────────────────────

DEFAULT_PARAMS: dict = {
    "hp_cutoff":        80.0,
    "low_shelf_hz":    200.0,
    "low_shelf_db":     -2.0,
    "presence_hz":    3000.0,
    "presence_db":      3.0,
    "presence_q":       0.8,
    "comp_threshold":  -18.0,
    "comp_ratio":       3.0,
    "comp_attack_ms":   5.0,
    "comp_release_ms": 100.0,
    "reverb_room_size": 0.3,
    "reverb_wet":       0.0,   # 0.0 = dry by default
    "limiter_db":      -1.0,
}

# Emotion-specific overrides applied on top of defaults
_EMOTION_OVERRIDES: dict[str, dict] = {
    "angry":    {"presence_db": 4.0, "comp_ratio": 4.0, "comp_threshold": -22.0},
    "excited":  {"presence_db": 3.5, "comp_ratio": 4.0, "comp_threshold": -22.0},
    "fear":     {"presence_db": 3.0, "hp_cutoff": 100.0, "comp_ratio": 3.5},
    "surprise": {"presence_db": 3.5, "comp_ratio": 3.5, "comp_threshold": -20.0},
    "sad":      {"presence_db": 1.5, "comp_ratio": 2.0, "low_shelf_db": -1.0, "reverb_wet": 0.04},
    "calm":     {"presence_db": 1.5, "comp_ratio": 2.0, "low_shelf_db": -1.0, "reverb_wet": 0.03},
    "happy":    {"presence_db": 3.0, "comp_ratio": 3.0},
    "disgust":  {"presence_db": 2.5, "comp_ratio": 3.0},
    "neutral":  {},
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_pedalboard_params(
    emotion: str | None,
    emotion_intensity: float = 1.0,
) -> dict:
    """Return AI-suggested pedalboard params for a segment.

    The returned dict is stored on the segment so the frontend can override
    individual values before re-synthesis.
    """
    params = dict(DEFAULT_PARAMS)
    overrides = _EMOTION_OVERRIDES.get(emotion or "neutral", {})

    # Scale overrides by emotion_intensity (blend toward defaults when intensity is low)
    for key, target_val in overrides.items():
        base_val = DEFAULT_PARAMS.get(key, target_val)
        params[key] = base_val + emotion_intensity * (target_val - base_val)

    return params


def apply_pedalboard_chain(
    segments: list[Segment],
    job_id: str = "default",
) -> list[Segment]:
    """Apply parametric post-processing to each segment's best available audio.

    Input path priority: matched_audio_path → adjusted_audio_path → synth_audio_path.
    Output written to data/temp/{job_id}/processed/, sets 'processed_audio_path'.

    Reads 'pedalboard_params' from segment if present (frontend override);
    otherwise calls build_pedalboard_params() to generate AI defaults.
    """
    try:
        from pedalboard import (  # type: ignore
            Pedalboard, HighpassFilter, LowShelfFilter, PeakFilter,
            Compressor, Reverb, Limiter,
        )
    except ImportError:
        logger.warning(
            "pedalboard not installed — skipping post-processing. "
            "Run: pip install pedalboard"
        )
        return segments

    proc_dir = config.TEMP_DIR / job_id / "processed"
    proc_dir.mkdir(parents=True, exist_ok=True)

    result = []
    for seg in segments:
        in_path = (
            seg.get("matched_audio_path")
            or seg.get("adjusted_audio_path")
            or seg.get("synth_audio_path")
        )
        if not in_path or not Path(in_path).exists():
            result.append(dict(seg))
            continue

        out_path = proc_dir / f"proc_{seg['id']:04d}.wav"

        if not out_path.exists():
            # Use stored params (frontend override) or compute AI defaults
            params = seg.get("pedalboard_params") or build_pedalboard_params(
                emotion=seg.get("emotion"),
                emotion_intensity=seg.get("emotion_intensity", 1.0),
            )
            _process_one(in_path, out_path, params)

        new_seg = dict(seg)
        new_seg["processed_audio_path"] = str(out_path)
        # Store params on segment if not already set (for frontend display)
        if not new_seg.get("pedalboard_params"):
            new_seg["pedalboard_params"] = build_pedalboard_params(
                emotion=seg.get("emotion"),
                emotion_intensity=seg.get("emotion_intensity", 1.0),
            )
        result.append(new_seg)
        logger.debug("Post-processed segment %d → %s", seg["id"], out_path.name)

    logger.info("Pedalboard processing complete: %d segments.", len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Core processing
# ─────────────────────────────────────────────────────────────────────────────

def _process_one(in_path: str, out_path: Path, params: dict) -> None:
    from pedalboard import (  # type: ignore
        Pedalboard, HighpassFilter, LowShelfFilter, PeakFilter,
        Compressor, Reverb, Limiter,
    )

    audio, sr = load_audio(in_path, sr=44100, mono=True)
    if len(audio) == 0:
        save_audio(audio, out_path, 44100)
        return

    plugins = [
        HighpassFilter(cutoff_frequency_hz=float(params.get("hp_cutoff", 80.0))),
        LowShelfFilter(
            cutoff_frequency_hz=float(params.get("low_shelf_hz", 200.0)),
            gain_db=float(params.get("low_shelf_db", -2.0)),
        ),
        PeakFilter(
            cutoff_frequency_hz=float(params.get("presence_hz", 3000.0)),
            gain_db=float(params.get("presence_db", 3.0)),
            q=float(params.get("presence_q", 0.8)),
        ),
        Compressor(
            threshold_db=float(params.get("comp_threshold", -18.0)),
            ratio=float(params.get("comp_ratio", 3.0)),
            attack_ms=float(params.get("comp_attack_ms", 5.0)),
            release_ms=float(params.get("comp_release_ms", 100.0)),
        ),
        Limiter(threshold_db=float(params.get("limiter_db", -1.0))),
    ]

    reverb_wet = float(params.get("reverb_wet", 0.0))
    if reverb_wet > 0.005:
        plugins.insert(-1, Reverb(
            room_size=float(params.get("reverb_room_size", 0.3)),
            wet_level=reverb_wet,
            dry_level=1.0 - reverb_wet,
        ))

    board = Pedalboard(plugins)
    # pedalboard expects (channels, samples) float32
    processed = board(audio[np.newaxis, :], sample_rate=sr)[0]
    save_audio(processed.astype(np.float32), out_path, sr)
