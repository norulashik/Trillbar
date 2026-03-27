"""Central configuration — reads from .env / environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
HUGGINGFACE_TOKEN: str = os.getenv("HUGGINGFACE_TOKEN", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
VOICE_PROFILES_DIR = DATA_DIR / "voice_profiles"
OUTPUT_DIR = DATA_DIR / "output"
TEMP_DIR = DATA_DIR / "temp"

for _d in [VOICE_PROFILES_DIR, OUTPUT_DIR, TEMP_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Model Config ──────────────────────────────────────────────────────────────
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
DEMUCS_MODEL: str = os.getenv("DEMUCS_MODEL", "htdemucs_ft")
USE_SPLEETER: bool = os.getenv("USE_SPLEETER", "false").lower() == "true"
TTS_BACKEND: str = os.getenv("TTS_BACKEND", "elevenlabs")  # "elevenlabs" | "sarvam"

# ── ElevenLabs ────────────────────────────────────────────────────────────────
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# ── Sarvam AI ─────────────────────────────────────────────────────────────────
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# ── Language Registry ─────────────────────────────────────────────────────────
LANGUAGE_CONFIGS: dict = {
    "hindi": {
        "display": "Hindi",
        "whisper_code": "hi",
        "elevenlabs_code": "hi",
        "sarvam_code": "hi-IN",
    },
    "tamil": {
        "display": "Tamil",
        "whisper_code": "ta",
        "elevenlabs_code": "ta",
        "sarvam_code": "ta-IN",
    },
    "telugu": {
        "display": "Telugu",
        "whisper_code": "te",
        "elevenlabs_code": "te",
        "sarvam_code": "te-IN",
    },
}

SUPPORTED_LANGUAGES = list(LANGUAGE_CONFIGS.keys())

# Default ElevenLabs voices to use when voice cloning is not available
# (free-tier fallback).  Choose multilingual voices.
ELEVENLABS_FALLBACK_VOICES: dict = {
    "hindi": "pNInz6obpgDQGcFmaJgB",   # Adam — works with multilingual v2
    "tamil": "pNInz6obpgDQGcFmaJgB",
    "telugu": "pNInz6obpgDQGcFmaJgB",
}

# ── Audio Config ──────────────────────────────────────────────────────────────
SAMPLE_RATE = 44100          # output / mixing sample rate
ML_SAMPLE_RATE = 16000       # ASR / diarization sample rate
MIN_REF_DURATION = 5.0       # minimum reference audio for voice cloning (s)
MAX_REF_DURATION = 45.0      # maximum reference audio for voice cloning (s)
REF_CHUNK_DURATION = 8.0     # target duration per reference chunk (s)
MAX_REF_CHUNKS = 5           # max files to upload to ElevenLabs (Starter plan limit)

# Time-stretch tolerance: synthesized audio is stretched/squeezed to fit the
# original segment duration within ±STRETCH_TOLERANCE.  Beyond that, we pad
# or truncate rather than distort too aggressively.
STRETCH_TOLERANCE = 0.30     # ±30 %

# ── Translation ───────────────────────────────────────────────────────────────
GEMINI_TRANSLATE_MODEL = "gemini-2.5-flash"   # fast + cheap
