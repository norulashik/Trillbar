"""Shared audio I/O helpers used across all pipeline stages."""

import logging
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

logger = logging.getLogger(__name__)


def load_audio(path: str | Path, sr: int = 44100, mono: bool = False) -> tuple[np.ndarray, int]:
    """Load any audio file to a numpy array.

    Returns (audio_array, sample_rate).  audio_array is (samples,) if mono,
    or (channels, samples) if stereo and mono=False.
    """
    path = str(path)
    audio, loaded_sr = sf.read(path, always_2d=True)  # shape: (samples, channels)
    audio = audio.T  # → (channels, samples)

    if loaded_sr != sr:
        # Resample each channel
        resampled = np.stack(
            [librosa.resample(ch, orig_sr=loaded_sr, target_sr=sr) for ch in audio]
        )
        audio = resampled

    if mono:
        audio = audio.mean(axis=0)  # → (samples,)

    return audio, sr


def save_audio(audio: np.ndarray, path: str | Path, sr: int = 44100) -> None:
    """Save numpy array to WAV.

    audio can be (samples,) for mono or (channels, samples) for stereo.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if audio.ndim == 2:
        data = audio.T  # soundfile expects (samples, channels)
    else:
        data = audio

    # Clip to prevent clipping artefacts
    data = np.clip(data, -1.0, 1.0)
    sf.write(str(path), data, sr, subtype="PCM_16")
    logger.debug("Saved audio → %s", path)


def get_duration(path: str | Path) -> float:
    """Return duration of an audio file in seconds without loading all samples."""
    info = sf.info(str(path))
    return info.duration


def rms_energy(audio: np.ndarray) -> float:
    """Root-mean-square energy of an audio array."""
    return float(np.sqrt(np.mean(audio ** 2)))


def trim_silence(audio: np.ndarray, sr: int, top_db: int = 30) -> np.ndarray:
    """Trim leading/trailing silence from a mono audio array."""
    trimmed, _ = librosa.effects.trim(audio, top_db=top_db)
    return trimmed


def normalize_peak(audio: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    """Peak-normalize audio to target_db dBFS."""
    peak = np.max(np.abs(audio))
    if peak < 1e-8:
        return audio
    target_linear = 10 ** (target_db / 20.0)
    return audio * (target_linear / peak)


def mix_stems(
    stems: list[np.ndarray],
    weights: list[float] | None = None,
) -> np.ndarray:
    """Mix a list of audio arrays (same shape) with optional weights."""
    if weights is None:
        weights = [1.0] * len(stems)
    mixed = sum(w * s for w, s in zip(weights, stems))
    return mixed


def stereo_to_mono(audio: np.ndarray) -> np.ndarray:
    """Convert (2, samples) stereo to (samples,) mono."""
    if audio.ndim == 1:
        return audio
    return audio.mean(axis=0)


def mono_to_stereo(audio: np.ndarray) -> np.ndarray:
    """Convert (samples,) mono to (2, samples) stereo."""
    if audio.ndim == 2:
        return audio
    return np.stack([audio, audio])


def strip_internal_silence(audio: np.ndarray, sr: int, top_db: int = 25, min_silence_ms: int = 300) -> np.ndarray:
    """Remove long internal silence gaps, keeping only speech portions.

    Splits audio into non-silent intervals and concatenates them with a
    short crossfade, so ElevenLabs receives dense speech without dead air.
    """
    intervals = librosa.effects.split(audio, top_db=top_db)
    if len(intervals) == 0:
        return audio

    min_silence_samples = int(min_silence_ms / 1000.0 * sr)
    crossfade = int(0.01 * sr)  # 10ms crossfade

    chunks = []
    for i, (start, end) in enumerate(intervals):
        chunk = audio[start:end]
        if len(chunk) < int(0.15 * sr):  # skip fragments under 150ms
            continue
        if chunks and crossfade > 0:
            # Apply short crossfade between chunks
            overlap = min(crossfade, len(chunks[-1]), len(chunk))
            if overlap > 0:
                fade_out = np.linspace(1.0, 0.0, overlap)
                fade_in = np.linspace(0.0, 1.0, overlap)
                chunks[-1][-overlap:] *= fade_out
                chunk = chunk.copy()
                chunk[:overlap] *= fade_in
                chunks[-1][-overlap:] += chunk[:overlap]
                chunk = chunk[overlap:]
        chunks.append(chunk)

    if not chunks:
        return audio
    return np.concatenate(chunks)


def match_spectral_envelope(source: np.ndarray, reference: np.ndarray, sr: int, strength: float = 0.6) -> np.ndarray:
    """Match source audio's spectral envelope to reference audio.

    This makes the output sound more like it was recorded in the same
    acoustic environment and with the same vocal tract as the reference.
    strength=1.0 is full match, 0.0 is no change.
    """
    n_fft = 2048
    hop = 512

    src_stft = librosa.stft(source, n_fft=n_fft, hop_length=hop)
    ref_stft = librosa.stft(reference, n_fft=n_fft, hop_length=hop)

    # Average spectral envelope (frequency profile)
    src_env = np.mean(np.abs(src_stft), axis=1, keepdims=True) + 1e-8
    ref_env = np.mean(np.abs(ref_stft), axis=1, keepdims=True) + 1e-8

    # Compute correction ratio, clamped to avoid extreme boosts
    ratio = ref_env / src_env
    ratio = np.clip(ratio, 0.25, 4.0)

    # Blend between original and matched
    blended_ratio = 1.0 + strength * (ratio - 1.0)

    matched_stft = src_stft * blended_ratio
    matched = librosa.istft(matched_stft, hop_length=hop, length=len(source))

    # Prevent clipping
    peak = np.max(np.abs(matched))
    if peak > 0.99:
        matched = matched * (0.99 / peak)

    return matched


def reduce_noise_spectral(audio: np.ndarray, sr: int, noise_floor_db: float = -40.0) -> np.ndarray:
    """Simple spectral gating noise reduction.

    Estimates a noise profile from low-energy frames and gates out
    frequency bins below the noise threshold. Preserves voice clarity.
    """
    n_fft = 2048
    hop = 512

    stft = librosa.stft(audio, n_fft=n_fft, hop_length=hop)
    magnitude = np.abs(stft)
    phase = np.angle(stft)

    # Estimate noise profile from the quietest 10% of frames
    frame_energy = np.mean(magnitude ** 2, axis=0)
    noise_frame_count = max(1, int(len(frame_energy) * 0.10))
    quietest_indices = np.argsort(frame_energy)[:noise_frame_count]
    noise_profile = np.mean(magnitude[:, quietest_indices], axis=1, keepdims=True)

    # Apply soft spectral gate
    gate_threshold = noise_profile * (10 ** (noise_floor_db / 20.0) * -1 + 2.0)
    mask = np.clip((magnitude - gate_threshold) / (magnitude + 1e-8), 0.0, 1.0)

    cleaned_stft = magnitude * mask * np.exp(1j * phase)
    cleaned = librosa.istft(cleaned_stft, hop_length=hop, length=len(audio))

    return cleaned
