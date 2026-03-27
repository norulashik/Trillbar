"""Module 6 — Audio Assembly & Final Output.

Places the synthesised (prosody + acoustically matched) dialogue segments
on a timeline, mixes them with the music/SFX stem from source separation,
and applies EBU R128 loudness normalisation.

Output: a broadcast-ready WAV (44.1 kHz, 16-bit, stereo).
"""

import logging
from pathlib import Path

import numpy as np
import pyloudnorm as pyln

from backend import config
from backend.utils.audio import load_audio, save_audio, mono_to_stereo, stereo_to_mono
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

# Target loudness (EBU R128 / streaming standard)
TARGET_LUFS = -16.0


def assemble_output(
    segments: list[Segment],
    no_vocals_path: str | Path,
    total_duration: float,
    job_id: str = "default",
    output_filename: str | None = None,
) -> Path:
    """Assemble the final dubbed audio track.

    Args:
        segments: Processed segments with 'matched_audio_path' (or fallback paths).
        no_vocals_path: Music + SFX stem from source separation.
        total_duration: Total duration of the original clip (seconds).
        job_id: Job identifier for temp directory routing.
        output_filename: Optional custom filename for the output.

    Returns:
        Path to the final output WAV file.
    """
    sr = config.SAMPLE_RATE
    total_samples = int(total_duration * sr)

    # ── Load music/SFX background stem ────────────────────────────────────
    no_vocals_audio, _ = load_audio(no_vocals_path, sr=sr)
    if no_vocals_audio.ndim == 1:
        no_vocals_audio = mono_to_stereo(no_vocals_audio)

    # Trim or pad to match total_duration
    no_vocals_audio = _fit_to_length(no_vocals_audio, total_samples)

    # ── Build dialogue track ───────────────────────────────────────────────
    dialogue_track = np.zeros((2, total_samples), dtype=np.float32)

    for seg in segments:
        audio_path = (
            seg.get("matched_audio_path")
            or seg.get("adjusted_audio_path")
            or seg.get("synth_audio_path")
        )
        if not audio_path or not Path(audio_path).exists():
            logger.debug("Segment %d has no audio — inserting silence.", seg["id"])
            continue

        seg_audio, _ = load_audio(audio_path, sr=sr, mono=True)
        seg_stereo = mono_to_stereo(seg_audio)

        start_sample = int(seg["start"] * sr)
        end_sample = start_sample + seg_stereo.shape[1]

        # Clamp to total length
        if start_sample >= total_samples:
            logger.warning("Segment %d starts beyond total duration — skipping.", seg["id"])
            continue
        if end_sample > total_samples:
            seg_stereo = seg_stereo[:, : total_samples - start_sample]
            end_sample = total_samples

        # Apply fade-in / fade-out (5 ms) to avoid clicks
        seg_stereo = _apply_fades(seg_stereo, sr, fade_ms=5)

        dialogue_track[:, start_sample:end_sample] += seg_stereo

    # ── Mix: background at -3 dB, dialogue at 0 dB ────────────────────────
    mixed = no_vocals_audio * 0.707 + dialogue_track

    # Clip to prevent digital distortion before normalisation
    mixed = np.clip(mixed, -1.0, 1.0)

    # ── EBU R128 loudness normalisation ───────────────────────────────────
    mixed = _normalise_loudness(mixed, sr, TARGET_LUFS)

    # ── Write output ──────────────────────────────────────────────────────
    out_dir = config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = f"dubbed_{job_id}.wav"

    out_path = out_dir / output_filename
    save_audio(mixed, out_path, sr)
    logger.info("Final output written: %s (%.1f s)", out_path, total_duration)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fit_to_length(audio: np.ndarray, target_samples: int) -> np.ndarray:
    """Trim or zero-pad audio to exactly target_samples."""
    current = audio.shape[-1]
    if current >= target_samples:
        return audio[..., :target_samples]
    # Pad
    pad_width = [(0, 0)] * (audio.ndim - 1) + [(0, target_samples - current)]
    return np.pad(audio, pad_width)


def _apply_fades(audio: np.ndarray, sr: int, fade_ms: float = 5.0) -> np.ndarray:
    """Apply linear fade-in and fade-out."""
    fade_samples = min(int(fade_ms * sr / 1000), audio.shape[-1] // 4)
    if fade_samples < 2:
        return audio
    fade_in = np.linspace(0.0, 1.0, fade_samples)
    fade_out = np.linspace(1.0, 0.0, fade_samples)
    audio = audio.copy()
    audio[..., :fade_samples] *= fade_in
    audio[..., -fade_samples:] *= fade_out
    return audio


def _normalise_loudness(audio: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    """Normalise integrated loudness to target LUFS using pyloudnorm."""
    # pyloudnorm expects (samples, channels)
    data = audio.T.astype(np.float64)
    meter = pyln.Meter(sr)
    try:
        loudness = meter.integrated_loudness(data)
        if np.isinf(loudness) or np.isnan(loudness):
            return audio
        normalised = pyln.normalize.loudness(data, loudness, target_lufs)
        # Peak limit to -1.0 dBFS
        peak = np.max(np.abs(normalised))
        if peak > 0.891:  # -1 dBFS
            normalised = normalised * (0.891 / peak)
        return normalised.T.astype(np.float32)
    except Exception as e:
        logger.warning("Loudness normalisation failed (non-critical): %s", e)
        return audio
