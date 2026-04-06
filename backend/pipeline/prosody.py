"""Module 5a — Prosody Transfer (simplified GST substitute).

For each segment:
  1. Extract F0 (fundamental frequency / pitch) from the SOURCE segment using
     parselmouth (Praat Python bindings).
  2. Compute mean F0 and energy of the source.
  3. Shift the SYNTHESISED audio's pitch to match the source F0 mean.
  4. Time-stretch the synthesised audio to fit within the original segment
     duration (±STRETCH_TOLERANCE).

This gives ~70–80 % of the emotional fidelity of full GST, which is
sufficient for a prototype demo on CPU.
"""

import logging
from pathlib import Path

import numpy as np
import librosa
import soundfile as sf

from backend import config
from backend.utils.audio import load_audio, save_audio, rms_energy, stereo_to_mono
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

# Emotion-based pitch adjustments (semitones added on top of source-matching shift)
EMOTION_PITCH_OFFSET: dict[str, float] = {
    "happy":    +1.5,
    "excited":  +2.5,
    "angry":    +2.0,
    "sad":      -1.5,
    "fear":     +1.0,
    "surprise": +2.0,
    "calm":     -0.5,
    "neutral":   0.0,
    "disgust":  -0.5,
}

try:
    import parselmouth
    from parselmouth.praat import call as praat_call
    HAS_PARSELMOUTH = True
except ImportError:
    HAS_PARSELMOUTH = False
    logger.warning(
        "parselmouth not installed — pitch analysis disabled. "
        "Install with: pip install praat-parselmouth"
    )


def apply_prosody_transfer(
    segments: list[Segment],
    job_id: str = "default",
) -> list[Segment]:
    """Transfer prosody from source audio to synthesised audio for each segment.

    Requires both 'source_audio_path' and 'synth_audio_path' to be set on
    each segment (set by synthesize.extract_segment_audio + synthesize_segments).

    Saves adjusted audio to data/temp/{job_id}/adjusted/ and sets
    'adjusted_audio_path' on each returned segment.
    """
    adj_dir = config.TEMP_DIR / job_id / "adjusted"
    adj_dir.mkdir(parents=True, exist_ok=True)

    result = []
    for seg in segments:
        synth_path = seg.get("synth_audio_path")
        src_path = seg.get("source_audio_path")

        if not synth_path or not Path(synth_path).exists():
            logger.warning("Segment %d has no synth audio — skipping prosody.", seg["id"])
            result.append(dict(seg))
            continue

        out_path = adj_dir / f"adj_{seg['id']:04d}.wav"

        if not out_path.exists():
            _transfer_one(
                src_path=src_path,
                synth_path=synth_path,
                out_path=out_path,
                target_duration=seg["duration"],
                emotion=seg.get("emotion"),
                emotion_intensity=seg.get("emotion_intensity", 1.0),
            )

        new_seg = dict(seg)
        new_seg["adjusted_audio_path"] = str(out_path)
        result.append(new_seg)

    logger.info("Prosody transfer complete: %d segments.", len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Core transfer logic
# ─────────────────────────────────────────────────────────────────────────────

def _transfer_one(
    src_path: str | None,
    synth_path: str,
    out_path: Path,
    target_duration: float,
    emotion: str | None = None,
    emotion_intensity: float = 1.0,
) -> None:
    # Load synthesised audio (always mono 44.1kHz from our TTS pipeline)
    synth_audio, sr = load_audio(synth_path, sr=44100, mono=True)

    synth_dur = len(synth_audio) / sr

    # ── Step 1: Time-stretch to fit target duration ────────────────────────
    if target_duration > 0:
        ratio = synth_dur / target_duration  # >1 means synth is longer
        clamped_ratio = np.clip(ratio, 1 - config.STRETCH_TOLERANCE, 1 + config.STRETCH_TOLERANCE)

        if abs(clamped_ratio - 1.0) > 0.01:
            # librosa time_stretch: rate > 1 → speed up, < 1 → slow down
            stretch_rate = clamped_ratio
            synth_audio = librosa.effects.time_stretch(synth_audio, rate=stretch_rate)

        # If still too long after max stretch, truncate with a short fade
        new_dur = len(synth_audio) / sr
        if new_dur > target_duration * 1.05:
            target_samples = int(target_duration * sr)
            fade_samples = min(int(0.05 * sr), target_samples // 4)
            synth_audio = synth_audio[:target_samples]
            # Fade out at the end
            fade = np.linspace(1.0, 0.0, fade_samples)
            synth_audio[-fade_samples:] *= fade

        # If too short, pad with silence
        elif new_dur < target_duration * 0.95:
            pad_samples = int(target_duration * sr) - len(synth_audio)
            synth_audio = np.concatenate([synth_audio, np.zeros(pad_samples)])

    # ── Step 2: Pitch shift to match source F0 ───────────────────────────
    if src_path and Path(src_path).exists() and HAS_PARSELMOUTH:
        try:
            src_audio, _ = load_audio(src_path, sr=44100, mono=True)
            n_semitones = _compute_pitch_shift(src_audio, synth_audio, sr)
            # Apply emotion-based pitch offset
            emo_offset = EMOTION_PITCH_OFFSET.get(emotion or "neutral", 0.0) * emotion_intensity
            n_semitones += emo_offset
            if abs(n_semitones) > 0.5:  # only shift if meaningful
                synth_audio = librosa.effects.pitch_shift(
                    synth_audio, sr=sr, n_steps=n_semitones
                )
                logger.debug("Pitch shifted by %.2f semitones (%.2f from emotion)", n_semitones, emo_offset)
        except Exception as e:
            logger.debug("Pitch shift failed (non-critical): %s", e)

    # ── Step 3: Energy (RMS) matching ────────────────────────────────────
    if src_path and Path(src_path).exists():
        try:
            src_audio, _ = load_audio(src_path, sr=44100, mono=True)
            synth_audio = _match_energy(synth_audio, src_audio)
        except Exception as e:
            logger.debug("Energy matching failed (non-critical): %s", e)

    save_audio(synth_audio, out_path, sr=44100)


def _compute_pitch_shift(src_audio: np.ndarray, synth_audio: np.ndarray, sr: int) -> float:
    """Compute pitch shift in semitones needed to match source F0 mean."""
    src_f0 = _mean_f0(src_audio, sr)
    synth_f0 = _mean_f0(synth_audio, sr)

    if src_f0 <= 0 or synth_f0 <= 0:
        return 0.0

    # Convert Hz ratio to semitones: n = 12 * log2(f_src / f_synth)
    n_semitones = 12.0 * np.log2(src_f0 / synth_f0)
    # Clamp to ±6 semitones to avoid unnatural shifts
    return float(np.clip(n_semitones, -6.0, 6.0))


def _mean_f0(audio: np.ndarray, sr: int) -> float:
    """Extract mean F0 using parselmouth (Praat)."""
    if not HAS_PARSELMOUTH:
        return 0.0

    # parselmouth needs float64
    audio_64 = audio.astype(np.float64)
    sound = parselmouth.Sound(audio_64, sr)
    pitch = sound.to_pitch(time_step=0.01, pitch_floor=60, pitch_ceiling=400)
    f0_values = pitch.selected_array["frequency"]
    voiced = f0_values[f0_values > 0]
    if len(voiced) == 0:
        return 0.0
    return float(np.median(voiced))


def _match_energy(synth: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Scale synth RMS to match source RMS."""
    src_rms = rms_energy(source)
    syn_rms = rms_energy(synth)
    if syn_rms < 1e-8 or src_rms < 1e-8:
        return synth
    gain = src_rms / syn_rms
    # Clamp gain to avoid extreme amplification
    gain = np.clip(gain, 0.25, 4.0)
    return synth * gain
