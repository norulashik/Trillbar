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

    # ── Load music/SFX background stem (optional) ─────────────────────────
    if no_vocals_path and Path(no_vocals_path).exists():
        no_vocals_audio, _ = load_audio(no_vocals_path, sr=sr)
        if no_vocals_audio.ndim == 1:
            no_vocals_audio = mono_to_stereo(no_vocals_audio)
        no_vocals_audio = _fit_to_length(no_vocals_audio, total_samples)
    else:
        logger.info("No background stem — output will be dialogue-only audio.")
        no_vocals_audio = np.zeros((2, total_samples), dtype=np.float32)

    # ── Build dialogue track ───────────────────────────────────────────────
    dialogue_track = np.zeros((2, total_samples), dtype=np.float32)

    for seg in segments:
        audio_path = (
            seg.get("processed_audio_path")
            or seg.get("matched_audio_path")
            or seg.get("adjusted_audio_path")
            or seg.get("synth_audio_path")
        )
        if not audio_path or not Path(audio_path).exists():
            logger.debug("Segment %d has no audio — inserting silence.", seg["id"])
            continue

        seg_audio, _ = load_audio(audio_path, sr=sr, mono=True)

        # Apply non-destructive clip edits (trim → stretch → volume)
        clip = seg.get("clip") or {}

        trim_in  = int(float(clip.get("trim_in_ms",  0)) / 1000.0 * sr)
        trim_out = int(float(clip.get("trim_out_ms", 0)) / 1000.0 * sr)
        if trim_in > 0 or trim_out > 0:
            end_idx = len(seg_audio) - trim_out if trim_out > 0 else len(seg_audio)
            seg_audio = seg_audio[trim_in:max(trim_in + 1, end_idx)]

        stretch = float(clip.get("stretch_ratio", 1.0))
        if abs(stretch - 1.0) > 0.02 and len(seg_audio) > 0:
            try:
                import librosa
                seg_audio = librosa.effects.time_stretch(seg_audio, rate=stretch)
            except Exception as _e:
                logger.warning("Time-stretch failed for segment %d: %s", seg["id"], _e)

        seg["dubbed_duration_s"] = len(seg_audio) / sr
        seg_stereo = mono_to_stereo(seg_audio)

        gain_db = float(clip.get("gain_db", 0.0))
        if gain_db != 0.0:
            seg_stereo = seg_stereo * float(10 ** (gain_db / 20.0))

        # Apply per-clip timing offset
        offset_s = float(clip.get("offset_ms", 0)) / 1000.0
        start_sample = int(max(0.0, seg["start"] + offset_s) * sr)
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

    # ── Mix: dynamic ducking — background ducks when dialogue is present ─────
    duck_mask = _compute_duck_mask(dialogue_track, sr)
    # duck_mask shape: (samples,) → broadcast to (2, samples)
    mixed = no_vocals_audio * duck_mask[np.newaxis, :] + dialogue_track

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

def _compute_duck_mask(
    dialogue_track: np.ndarray,
    sr: int,
    attack_ms: float = 50.0,
    release_ms: float = 200.0,
    duck_db: float = -6.0,
) -> np.ndarray:
    """Compute per-sample background gain reduction when dialogue is present.

    Returns a float32 array of shape (total_samples,) with values between
    duck_linear (when dialogue active) and 1.0 (when dialogue silent).
    """
    duck_linear = float(10 ** (duck_db / 20.0))
    total_samples = dialogue_track.shape[-1]

    # Mix to mono for energy detection
    if dialogue_track.ndim == 2:
        mono = dialogue_track.mean(axis=0)
    else:
        mono = dialogue_track

    frame_size = max(1, int(sr * 0.010))  # 10 ms frames
    threshold = float(10 ** (-40.0 / 20.0))  # -40 dBFS

    # Compute frame-level RMS and threshold
    n_frames = max(1, (total_samples + frame_size - 1) // frame_size)
    active = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        start = i * frame_size
        end = min(start + frame_size, total_samples)
        frame = mono[start:end]
        rms = float(np.sqrt(np.mean(frame ** 2))) if len(frame) > 0 else 0.0
        active[i] = 1.0 if rms > threshold else 0.0

    # Smooth with attack/release envelopes
    attack_frames = max(1, int(attack_ms / 10.0))
    release_frames = max(1, int(release_ms / 10.0))
    smoothed = np.zeros_like(active)
    current = 0.0
    for i, a in enumerate(active):
        if a > current:
            current = min(float(a), current + 1.0 / attack_frames)
        else:
            current = max(float(a), current - 1.0 / release_frames)
        smoothed[i] = current

    # Convert to gain: 1.0 (silence) → duck_linear (active dialogue)
    gain_frames = 1.0 - smoothed * (1.0 - duck_linear)

    # Upsample to sample-level via linear interpolation
    frame_centres = np.arange(n_frames) * frame_size + frame_size / 2.0
    sample_indices = np.arange(total_samples, dtype=np.float64)
    gain_samples = np.interp(sample_indices, frame_centres, gain_frames)

    return gain_samples.astype(np.float32)


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
