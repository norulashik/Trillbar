"""Module 2a — Source Separation.

Isolates the vocals (dialogue) from the full audio using the ElevenLabs
Audio Isolation API.  Background music/SFX is NOT returned as a separate
stem (API limitation); the assembler handles a missing no_vocals stem by
using silence for the background track.

Outputs written to data/temp/{job_id}/stems/
"""

import logging
import shutil
import subprocess
from pathlib import Path

import requests

from backend import config
from backend.utils.audio import load_audio, save_audio

logger = logging.getLogger(__name__)

_ISOLATION_URL = f"{config.ELEVENLABS_BASE_URL}/audio-isolation"


def separate_stems(audio_path_44k: str | Path, job_id: str = "default") -> dict:
    """Isolate vocals via ElevenLabs Audio Isolation API.

    Returns:
        {
            "vocals":    Path,  # voice-isolated WAV (44.1 kHz stereo)
            "no_vocals": None,  # not available via this API
        }
    """
    audio_path_44k = Path(audio_path_44k)
    stems_dir = config.TEMP_DIR / job_id / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    vocals_path = stems_dir / "vocals.wav"

    if vocals_path.exists():
        logger.info("Vocals stem already exists, skipping isolation.")
        return {"vocals": vocals_path, "no_vocals": None}

    logger.info("Running ElevenLabs Audio Isolation on: %s", audio_path_44k.name)

    with open(audio_path_44k, "rb") as f:
        response = requests.post(
            _ISOLATION_URL,
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            files={"audio": (audio_path_44k.name, f, "audio/wav")},
            timeout=300,
        )

    if response.status_code != 200:
        logger.warning(
            "Audio Isolation API returned %d: %s — falling back to raw audio.",
            response.status_code,
            response.text[:200],
        )
        shutil.copy(audio_path_44k, vocals_path)
    else:
        raw_path = stems_dir / f"vocals_raw{audio_path_44k.suffix}"
        raw_path.write_bytes(response.content)
        _convert_to_wav(raw_path, vocals_path)
        raw_path.unlink(missing_ok=True)

    logger.info("Audio isolation complete → %s", vocals_path.name)
    return {"vocals": vocals_path, "no_vocals": None}


def skip_separation(audio_path_44k: str | Path, job_id: str = "default") -> dict:
    """Use the raw audio as the vocals stem (no separation)."""
    audio_path_44k = Path(audio_path_44k)
    stems_dir = config.TEMP_DIR / job_id / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    vocals_path = stems_dir / "vocals.wav"
    shutil.copy(audio_path_44k, vocals_path)

    logger.warning(
        "Skipping source separation — original audio used as vocals stem. "
        "Final output may include original background audio."
    )
    return {"vocals": vocals_path, "no_vocals": None}


def _convert_to_wav(src: Path, dst: Path) -> None:
    """Convert any audio file to 44.1 kHz stereo PCM WAV via ffmpeg."""
    from backend.pipeline.ingest import _ffmpeg_bin

    cmd = [
        _ffmpeg_bin(), "-y",
        "-i", str(src),
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed:\n{result.stderr}")
