"""Module 5a — Prosody Transfer.

For each segment:
  1. Time-stretch synthesised audio to fit the original segment duration.
  2. F0 contour transfer: extract source F0 contour with WORLD vocoder (pyworld),
     z-score-normalise the shape, and apply it to the synth's pitch space.
     WORLD resynthesis preserves formants — no robotic pitch-shift artefacts.
  3. Energy (RMS) matching: scale synth RMS to match source RMS.

Falls back to librosa pitch_shift if pyworld is not installed.
"""

import logging
from pathlib import Path

import numpy as np
import librosa

from backend import config
from backend.utils.audio import load_audio, save_audio, rms_energy, stereo_to_mono
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

# Emotion-based pitch offset (semitones on top of source-matched pitch)
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


def apply_prosody_transfer(
    segments: list[Segment],
    job_id: str = "default",
) -> list[Segment]:
    """Transfer prosody from source to synthesised audio for each segment."""
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
    synth_audio, sr = load_audio(synth_path, sr=44100, mono=True)
    synth_dur = len(synth_audio) / sr

    # ── Step 1: Time-stretch to fit target duration ────────────────────────
    if target_duration > 0:
        ratio = synth_dur / target_duration
        clamped = np.clip(ratio, 1 - config.STRETCH_TOLERANCE, 1 + config.STRETCH_TOLERANCE)

        if abs(clamped - 1.0) > 0.01:
            synth_audio = librosa.effects.time_stretch(synth_audio, rate=clamped)

        new_dur = len(synth_audio) / sr
        if new_dur > target_duration * 1.05:
            target_samples = int(target_duration * sr)
            fade_n = min(int(0.05 * sr), target_samples // 4)
            synth_audio = synth_audio[:target_samples]
            synth_audio[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)
        elif new_dur < target_duration * 0.95:
            pad = int(target_duration * sr) - len(synth_audio)
            synth_audio = np.concatenate([synth_audio, np.zeros(pad)])

    # ── Step 2: F0 contour transfer ───────────────────────────────────────
    if src_path and Path(src_path).exists():
        src_audio, _ = load_audio(src_path, sr=44100, mono=True)
        try:
            synth_audio = _transfer_f0_contour(
                src_audio, synth_audio, sr=44100,
                emotion=emotion, emotion_intensity=emotion_intensity,
            )
        except Exception as e:
            logger.debug("pyworld F0 contour failed, falling back to librosa: %s", e)
            # Fallback: single-value pitch shift via librosa
            try:
                n_steps = _compute_pitch_shift_semitones(src_audio, synth_audio, 44100)
                emo_offset = EMOTION_PITCH_OFFSET.get(emotion or "neutral", 0.0) * emotion_intensity
                total = n_steps + emo_offset
                if abs(total) > 0.5:
                    synth_audio = librosa.effects.pitch_shift(synth_audio, sr=44100, n_steps=total)
            except Exception as e2:
                logger.debug("librosa pitch shift also failed: %s", e2)

    # ── Step 3: Energy matching ───────────────────────────────────────────
    if src_path and Path(src_path).exists():
        try:
            src_audio, _ = load_audio(src_path, sr=44100, mono=True)
            synth_audio = _match_energy(synth_audio, src_audio)
        except Exception as e:
            logger.debug("Energy matching failed: %s", e)

    save_audio(synth_audio, out_path, sr=44100)


# ─────────────────────────────────────────────────────────────────────────────
# pyworld F0 contour transfer
# ─────────────────────────────────────────────────────────────────────────────

def _transfer_f0_contour(
    src_audio: np.ndarray,
    synth_audio: np.ndarray,
    sr: int,
    emotion: str | None = None,
    emotion_intensity: float = 1.0,
    frame_period_ms: float = 5.0,
) -> np.ndarray:
    """Transfer F0 contour shape from source to synth using WORLD vocoder.

    Algorithm:
      1. Extract F0 contours from both source and synth (dio + stonemask).
      2. Z-score normalise source contour shape.
      3. Apply that shape to synth's own pitch space (preserves pitch range).
      4. Blend by emotion_intensity (0 = keep synth F0, 1 = full contour transfer).
      5. Add emotion-based semitone offset.
      6. WORLD resynthesis — formants untouched, only F0 changes.
    """
    import pyworld as pw  # ImportError triggers fallback in caller

    # Minimum audio length for meaningful F0 analysis
    if len(src_audio) < int(sr * 0.05) or len(synth_audio) < int(sr * 0.05):
        return synth_audio

    src_64 = src_audio.astype(np.float64)
    synth_64 = synth_audio.astype(np.float64)

    # Extract F0 contours
    src_f0, src_t = pw.dio(src_64, sr, frame_period=frame_period_ms)
    src_f0 = pw.stonemask(src_64, src_f0, src_t, sr)

    synth_f0, synth_t = pw.dio(synth_64, sr, frame_period=frame_period_ms)
    synth_f0 = pw.stonemask(synth_64, synth_f0, synth_t, sr)

    voiced_src = src_f0 > 0
    voiced_synth = synth_f0 > 0

    if not voiced_src.any() or not voiced_synth.any():
        return synth_audio

    src_mean = float(np.mean(src_f0[voiced_src]))
    src_std = float(np.std(src_f0[voiced_src])) + 1e-8
    synth_mean = float(np.mean(synth_f0[voiced_synth]))
    synth_std = float(np.std(synth_f0[voiced_synth])) + 1e-8

    # Resample source contour to match synth frame count
    src_f0_resampled = np.interp(
        np.linspace(0, 1, len(synth_f0)),
        np.linspace(0, 1, len(src_f0)),
        src_f0,
    )

    # Z-score shape of source → apply to synth pitch space
    src_z = (src_f0_resampled - src_mean) / src_std
    target_f0 = synth_mean + src_z * synth_std

    # Blend: 0 = keep synth, 1 = full source shape transfer (max 70%)
    blend = min(emotion_intensity * 0.7, 0.7)
    new_f0 = synth_f0 * (1.0 - blend) + target_f0 * blend

    # Apply emotion-based semitone offset
    emo_offset_st = EMOTION_PITCH_OFFSET.get(emotion or "neutral", 0.0) * emotion_intensity
    if abs(emo_offset_st) > 0.1:
        emo_multiplier = 2.0 ** (emo_offset_st / 12.0)
        new_f0[voiced_synth] *= emo_multiplier

    # Keep unvoiced frames silent, clamp to human pitch range
    new_f0[~voiced_synth] = 0.0
    new_f0 = np.clip(new_f0, 50.0, 600.0)
    new_f0[~voiced_synth] = 0.0

    # WORLD analysis of synth for SP and AP (formants + aperiodicity)
    _, sp = pw.cheaptrick(synth_64, synth_f0, synth_t, sr)
    _, ap = pw.d4c(synth_64, synth_f0, synth_t, sr)

    # Resynthesise with new F0 — formants preserved
    resynthesised = pw.synthesize(new_f0, sp, ap, sr, frame_period=frame_period_ms)

    # Trim/pad to match original synth length
    target_len = len(synth_audio)
    if len(resynthesised) >= target_len:
        output = resynthesised[:target_len]
    else:
        output = np.pad(resynthesised, (0, target_len - len(resynthesised)))

    return output.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Librosa fallback helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_pitch_shift_semitones(
    src_audio: np.ndarray,
    synth_audio: np.ndarray,
    sr: int,
) -> float:
    src_f0 = _mean_f0(src_audio, sr)
    synth_f0 = _mean_f0(synth_audio, sr)
    if src_f0 <= 0 or synth_f0 <= 0:
        return 0.0
    n_semitones = 12.0 * np.log2(src_f0 / synth_f0)
    return float(np.clip(n_semitones, -6.0, 6.0))


def _mean_f0(audio: np.ndarray, sr: int) -> float:
    try:
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


def _match_energy(synth: np.ndarray, source: np.ndarray) -> np.ndarray:
    src_rms = rms_energy(source)
    syn_rms = rms_energy(synth)
    if syn_rms < 1e-8 or src_rms < 1e-8:
        return synth
    gain = np.clip(src_rms / syn_rms, 0.25, 4.0)
    return synth * gain
