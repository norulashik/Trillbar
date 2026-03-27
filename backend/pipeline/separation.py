"""Module 2a — Source Separation.

Splits the full audio into stems using Demucs (htdemucs):
  - vocals  → dialogue stem  (used for ASR, voice profiling, prosody reference)
  - no_vocals → music + SFX stem  (preserved in final mix)

On CPU a 5-minute clip typically takes 40–70 minutes with htdemucs.
Set USE_SPLEETER=true in .env for a faster (lower-quality) alternative.

Outputs are written to:
    data/temp/{job_id}/stems/
"""

import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np

from backend import config
from backend.utils.audio import load_audio, save_audio

logger = logging.getLogger(__name__)


def separate_stems(audio_path_44k: str | Path, job_id: str = "default") -> dict:
    """Run source separation and return paths to stem files.

    Returns:
        {
            "vocals":    Path,  # dialogue / vocals stem (44.1 kHz stereo WAV)
            "no_vocals": Path,  # music + SFX stem      (44.1 kHz stereo WAV)
        }
    """
    audio_path_44k = Path(audio_path_44k)
    stems_dir = config.TEMP_DIR / job_id / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    vocals_path = stems_dir / "vocals.wav"
    no_vocals_path = stems_dir / "no_vocals.wav"

    # Return cached results if already computed
    if vocals_path.exists() and no_vocals_path.exists():
        logger.info("Stems already exist, skipping separation.")
        return {"vocals": vocals_path, "no_vocals": no_vocals_path}

    if config.USE_SPLEETER:
        _separate_spleeter(audio_path_44k, stems_dir, vocals_path, no_vocals_path)
    else:
        _separate_demucs(audio_path_44k, stems_dir, vocals_path, no_vocals_path, job_id)

    return {"vocals": vocals_path, "no_vocals": no_vocals_path}


# ── Demucs ────────────────────────────────────────────────────────────────────

def _separate_demucs(
    audio_path: Path,
    stems_dir: Path,
    vocals_path: Path,
    no_vocals_path: Path,
    job_id: str,
) -> None:
    logger.info(
        "Running Demucs (%s) on CPU — this may take 40–70 min for a 5-min clip.",
        config.DEMUCS_MODEL,
    )

    demucs_out = config.TEMP_DIR / job_id / "demucs_raw"
    cmd = [
        "python", "-m", "demucs",
        "--two-stems", "vocals",           # only split into vocals / no_vocals
        "--name", config.DEMUCS_MODEL,
        "--out", str(demucs_out),
        str(audio_path),
    ]
    logger.info("Demucs command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if result.returncode != 0:
        # Log full stderr for debugging, show last 1000 chars in error
        logger.error("Demucs stderr:\n%s", result.stderr[-2000:])
        logger.error("Demucs stdout:\n%s", result.stdout[-1000:])
        # Filter out download progress bars from stderr to show actual errors
        stderr_lines = [
            line for line in result.stderr.splitlines()
            if not line.strip().startswith(("%", "0%", "1%")) and "|" not in line
        ]
        error_msg = "\n".join(stderr_lines).strip() or result.stderr[-1000:]
        raise RuntimeError(f"Demucs failed (exit code {result.returncode}):\n{error_msg}")

    # Demucs writes to: demucs_out/<model>/<stem_name>/<filename>
    model_dir = demucs_out / config.DEMUCS_MODEL
    # find the subdirectory named after the input file (stem name = track name)
    track_dirs = list(model_dir.iterdir())
    if not track_dirs:
        raise RuntimeError("Demucs produced no output directories.")
    track_dir = track_dirs[0]

    # Copy to our canonical paths
    shutil.copy(str(track_dir / "vocals.wav"), str(vocals_path))
    shutil.copy(str(track_dir / "no_vocals.wav"), str(no_vocals_path))
    logger.info("Demucs separation complete.")


# ── Spleeter (fast CPU fallback) ──────────────────────────────────────────────

def _separate_spleeter(
    audio_path: Path,
    stems_dir: Path,
    vocals_path: Path,
    no_vocals_path: Path,
) -> None:
    logger.info("Running Spleeter (2-stems, CPU) — fast but lower quality.")
    try:
        from spleeter.separator import Separator
        from spleeter.audio.adapter import AudioAdapter
    except ImportError:
        raise ImportError(
            "Spleeter not installed. Run: pip install spleeter\n"
            "Or set USE_SPLEETER=false to use Demucs."
        )

    separator = Separator("spleeter:2stems")
    adapter = AudioAdapter.default()
    waveform, sample_rate = adapter.load(str(audio_path), sample_rate=44100)
    prediction = separator.separate(waveform)

    import soundfile as sf
    sf.write(str(vocals_path), prediction["vocals"], sample_rate)
    sf.write(str(no_vocals_path), prediction["accompaniment"], sample_rate)
    logger.info("Spleeter separation complete.")


# ── Skip-separation fallback ──────────────────────────────────────────────────

def skip_separation(audio_path_44k: str | Path, job_id: str = "default") -> dict:
    """Use the raw audio as both stems (no separation).

    Useful for quick testing when you don't want to wait for Demucs.
    The final output will have the original dialogue mixed in with the dubbed
    audio (not ideal, but workable for demos).
    """
    audio_path_44k = Path(audio_path_44k)
    stems_dir = config.TEMP_DIR / job_id / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    vocals_path = stems_dir / "vocals.wav"
    no_vocals_path = stems_dir / "no_vocals.wav"

    # Create a silent no_vocals (we'll mix just the dubbed dialogue)
    audio, sr = load_audio(audio_path_44k)
    save_audio(audio, vocals_path, sr)

    silence = np.zeros_like(audio)
    save_audio(silence, no_vocals_path, sr)

    logger.warning(
        "Skipping source separation — original audio used as vocals stem. "
        "Final output will include original background audio."
    )
    return {"vocals": vocals_path, "no_vocals": no_vocals_path}
