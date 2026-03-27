"""Module 1 — Ingestion & Preprocessing.

Extracts audio from any video or audio container using ffmpeg.
Produces two WAV files:
  - full_44k.wav   — 44.1 kHz stereo, used for mixing
  - full_16k.wav   — 16 kHz mono, used for ASR / diarization
"""

import logging
import shutil
import subprocess
from pathlib import Path

from backend import config

logger = logging.getLogger(__name__)


def _ffmpeg_bin() -> str:
    """Return the ffmpeg executable path.

    Prefers the system ffmpeg; falls back to the binary bundled with
    imageio-ffmpeg so no manual install is required.
    """
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError(
            "ffmpeg not found. Install it with:\n"
            "  pip install imageio[ffmpeg]\n"
            "or download from https://ffmpeg.org/download.html"
        )


def extract_audio(input_path: str | Path, job_id: str = "default") -> dict:
    """Extract audio from a video/audio file.

    Returns a dict with paths:
        {
            "full_44k": Path,   # 44.1 kHz stereo WAV (for mixing)
            "full_16k": Path,   # 16 kHz mono WAV (for ML models)
            "duration": float,  # total duration in seconds
        }
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    out_dir = config.TEMP_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    full_44k = out_dir / "full_44k.wav"
    full_16k = out_dir / "full_16k.wav"

    logger.info("Extracting audio from: %s", input_path)

    # 44.1 kHz stereo — used later for stem mixing
    _run_ffmpeg(
        str(input_path),
        str(full_44k),
        sample_rate=44100,
        channels=2,
    )

    # 16 kHz mono — used by Whisper + pyannote
    _run_ffmpeg(
        str(input_path),
        str(full_16k),
        sample_rate=16000,
        channels=1,
    )

    duration = _get_duration(str(full_44k))
    logger.info("Audio extracted. Duration: %.2f s", duration)

    return {
        "full_44k": full_44k,
        "full_16k": full_16k,
        "duration": duration,
    }


def _run_ffmpeg(
    input_path: str,
    output_path: str,
    sample_rate: int,
    channels: int,
) -> None:
    cmd = [
        _ffmpeg_bin(),
        "-y",                     # overwrite output
        "-i", input_path,
        "-vn",                    # no video
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-ar", str(sample_rate),
        "-ac", str(channels),
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed:\n{result.stderr}"
        )


def _get_duration(wav_path: str) -> float:
    # Try soundfile first — no external binary needed
    try:
        import soundfile as sf
        info = sf.info(wav_path)
        return info.duration
    except Exception:
        pass

    # Fallback: ffprobe
    ffmpeg_path = _ffmpeg_bin()
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
    if not shutil.which(ffprobe_path):
        raise RuntimeError(
            "Cannot determine audio duration. Install ffprobe or soundfile."
        )
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    raise RuntimeError(f"Could not determine duration of {wav_path}")
