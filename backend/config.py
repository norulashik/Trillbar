"""Central configuration — reads from .env / environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ASSEMBLYAI_API_KEY: str = os.getenv("ASSEMBLYAI_API_KEY", "")
SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
SYNCLABS_API_KEY: str = os.getenv("SYNCLABS_API_KEY", "")
# Externally reachable URL of this backend (used by SyncLabs to fetch video/audio)
# For local dev: run `ngrok http 8000` and paste the https URL here
SYNCLABS_PUBLIC_BASE_URL: str = os.getenv("SYNCLABS_PUBLIC_BASE_URL", "").rstrip("/")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
VOICE_PROFILES_DIR = DATA_DIR / "voice_profiles"
OUTPUT_DIR = DATA_DIR / "output"
TEMP_DIR = DATA_DIR / "temp"

for _d in [VOICE_PROFILES_DIR, OUTPUT_DIR, TEMP_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── TTS Backend ───────────────────────────────────────────────────────────────
TTS_BACKEND: str = os.getenv("TTS_BACKEND", "elevenlabs")  # "elevenlabs" | "sarvam"

# ── ElevenLabs ────────────────────────────────────────────────────────────────
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# ── Sarvam AI ─────────────────────────────────────────────────────────────────
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# ── Language Registry ─────────────────────────────────────────────────────────
LANGUAGE_CONFIGS: dict = {
    "hindi":     {"display": "Hindi",     "assemblyai_code": "hi", "elevenlabs_code": "hi", "sarvam_code": "hi-IN"},
    "tamil":     {"display": "Tamil",     "assemblyai_code": "ta", "elevenlabs_code": "ta", "sarvam_code": "ta-IN"},
    "telugu":    {"display": "Telugu",    "assemblyai_code": "te", "elevenlabs_code": "te", "sarvam_code": "te-IN"},
    "kannada":   {"display": "Kannada",   "assemblyai_code": "kn", "elevenlabs_code": "kn", "sarvam_code": "kn-IN"},
    "malayalam": {"display": "Malayalam", "assemblyai_code": "ml", "elevenlabs_code": "ml", "sarvam_code": "ml-IN"},
    "bengali":   {"display": "Bengali",   "assemblyai_code": "bn", "elevenlabs_code": "bn", "sarvam_code": "bn-IN"},
    "marathi":   {"display": "Marathi",   "assemblyai_code": "mr", "elevenlabs_code": "mr", "sarvam_code": "mr-IN"},
}

SUPPORTED_LANGUAGES = list(LANGUAGE_CONFIGS.keys())

# Default ElevenLabs fallback voices (free-tier, when voice cloning fails)
ELEVENLABS_FALLBACK_VOICES: dict = {
    "hindi":  "pNInz6obpgDQGcFmaJgB",   # Adam — multilingual v2
    "tamil":  "pNInz6obpgDQGcFmaJgB",
    "telugu": "pNInz6obpgDQGcFmaJgB",
}

# ── Audio Config ──────────────────────────────────────────────────────────────
SAMPLE_RATE = 44100          # output / mixing sample rate
MIN_REF_DURATION = 5.0       # minimum reference audio for voice cloning (s)
MAX_REF_DURATION = 45.0      # maximum reference audio for voice cloning (s)
REF_CHUNK_DURATION = 8.0     # target duration per reference chunk (s)
MAX_REF_CHUNKS = 5           # max files to upload to ElevenLabs (Starter plan limit)

# Time-stretch tolerance: ±STRETCH_TOLERANCE before padding/truncating
STRETCH_TOLERANCE = 0.30     # ±30 %

# ── Translation ───────────────────────────────────────────────────────────────
GEMINI_TRANSLATE_MODEL = "gemini-2.5-flash"

# ── Emotion-Aware Dubbing ─────────────────────────────────────────────────────
ENABLE_EMOTION: bool = os.getenv("ENABLE_EMOTION", "true").lower() == "true"
# Use Gemini audio input for richer emotion analysis (analyzes actual WAV, not just text)
GEMINI_AUDIO_EMOTION: bool = os.getenv("GEMINI_AUDIO_EMOTION", "true").lower() == "true"
GEMINI_AUDIO_MODEL: str = os.getenv("GEMINI_AUDIO_MODEL", "gemini-2.5-flash")

# ── ElevenLabs v3 Audio Tags ──────────────────────────────────────────────────
# Set to "true" once v3 model access is confirmed on your ElevenLabs plan
ELEVENLABS_USE_AUDIO_TAGS: bool = os.getenv("ELEVENLABS_USE_AUDIO_TAGS", "false").lower() == "true"

# ── Quality Assessment ────────────────────────────────────────────────────────
ENABLE_QUALITY_CHECK: bool = os.getenv("ENABLE_QUALITY_CHECK", "false").lower() == "true"
QUALITY_CHECK_GEMINI: bool = os.getenv("QUALITY_CHECK_GEMINI", "false").lower() == "true"
MOS_THRESHOLD: float = float(os.getenv("MOS_THRESHOLD", "3.5"))
