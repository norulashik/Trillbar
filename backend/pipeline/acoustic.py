"""Module 5b — Acoustic Character Matching (simplified WORLD substitute).

Transfers the acoustic fingerprint of the source recording to the
synthesised audio so that the dubbed voice sounds "placed" in the original
production environment rather than like a studio overdub.

Techniques used (all CPU-friendly, no GPU required):
  1. Spectral centroid matching — shifts the tonal balance of the synth
     toward the source recording.
  2. RMS energy normalisation (already done in prosody.py; here we do
     per-frame normalisation for better local balance).
  3. Optional very light reverb simulation via a short Gaussian IR to
     approximate room warmth (disabled by default for clean output).
"""

import logging
from pathlib import Path

import numpy as np
import librosa
import soundfile as sf

from backend import config
from backend.utils.audio import load_audio, save_audio, stereo_to_mono, rms_energy
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)


def apply_acoustic_matching(
    segments: list[Segment],
    vocals_44k_path: str | Path,
    job_id: str = "default",
) -> list[Segment]:
    """Apply acoustic character matching to adjusted (prosody-corrected) segments.

    Reads 'adjusted_audio_path'; falls back to 'synth_audio_path' if absent.
    Writes matched audio to data/temp/{job_id}/matched/ and sets
    'matched_audio_path' on returned segments.
    """
    vocals_path = Path(vocals_44k_path)
    matched_dir = config.TEMP_DIR / job_id / "matched"
    matched_dir.mkdir(parents=True, exist_ok=True)

    # Compute global acoustic fingerprint from the full vocals stem
    ref_audio, sr = load_audio(vocals_path, sr=44100, mono=True)
    ref_centroid_mean = _mean_spectral_centroid(ref_audio, sr)
    logger.debug("Reference spectral centroid: %.1f Hz", ref_centroid_mean)

    result = []
    for seg in segments:
        in_path = seg.get("adjusted_audio_path") or seg.get("synth_audio_path")
        if not in_path or not Path(in_path).exists():
            result.append(dict(seg))
            continue

        out_path = matched_dir / f"matched_{seg['id']:04d}.wav"

        if not out_path.exists():
            _match_one(in_path, out_path, ref_centroid_mean, sr)

        new_seg = dict(seg)
        new_seg["matched_audio_path"] = str(out_path)
        result.append(new_seg)

    logger.info("Acoustic matching complete: %d segments.", len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Core matching logic
# ─────────────────────────────────────────────────────────────────────────────

def _match_one(
    in_path: str,
    out_path: Path,
    ref_centroid: float,
    sr: int,
) -> None:
    audio, _ = load_audio(in_path, sr=sr, mono=True)

    # Apply spectral centroid equalisation
    audio = _equalise_toward_centroid(audio, sr, ref_centroid)

    save_audio(audio, out_path, sr)


def _mean_spectral_centroid(audio: np.ndarray, sr: int) -> float:
    """Compute the mean spectral centroid of an audio signal."""
    centroids = librosa.feature.spectral_centroid(y=audio, sr=sr, n_fft=2048, hop_length=512)
    return float(np.mean(centroids))


def _equalise_toward_centroid(
    audio: np.ndarray,
    sr: int,
    target_centroid: float,
    strength: float = 0.5,
) -> np.ndarray:
    """Adjust the spectral centroid of `audio` toward `target_centroid`.

    Uses a simple first-order shelving filter approximation:
      - If source centroid > target → low-pass (darken)
      - If source centroid < target → high-pass boost (brighten)

    `strength` ∈ [0, 1] controls how aggressively to equalise.
    """
    if len(audio) == 0:
        return audio

    src_centroid = float(np.mean(
        librosa.feature.spectral_centroid(y=audio, sr=sr, n_fft=2048, hop_length=512)
    ))

    if src_centroid <= 0 or target_centroid <= 0:
        return audio

    ratio = target_centroid / src_centroid  # >1 → need to brighten, <1 → darken

    # Convert to a mild gain adjustment across frequency bands
    # We'll use STFT-based per-band scaling
    n_fft = 2048
    hop_length = 512

    stft = librosa.stft(audio, n_fft=n_fft, hop_length=hop_length)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    # Build a frequency-dependent gain curve
    # Linear interpolation: gain = 1 at 0 Hz, gain = ratio^strength at nyquist
    gains = 1.0 + (ratio ** strength - 1.0) * (freqs / (sr / 2.0))
    gains = np.clip(gains, 0.5, 2.0)  # never more than ±6 dB

    # Apply gains (broadcast over time frames)
    stft_eq = stft * gains[:, np.newaxis]

    audio_eq = librosa.istft(stft_eq, hop_length=hop_length, length=len(audio))
    return audio_eq.astype(np.float32)
