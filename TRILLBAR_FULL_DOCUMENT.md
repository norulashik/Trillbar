# TrillBar — Complete System Documentation

> AI-Powered Multilingual Dubbing for India's OTT Era
> Prototype v0.1 · Hindi · Tamil · Telugu · CPU-only

---

## Table of Contents

1. [What is TrillBar?](#1-what-is-trillbar)
2. [The Problem We Solve](#2-the-problem-we-solve)
3. [Simple User Workflow](#3-simple-user-workflow-non-technical)
4. [What Goes In → What Comes Out](#4-what-goes-in--what-comes-out)
5. [Full Technical Architecture](#5-full-technical-architecture)
6. [Pipeline — Stage by Stage](#6-pipeline--stage-by-stage)
7. [Technology Stack](#7-technology-stack)
8. [Project File Structure](#8-project-file-structure)
9. [How to Run (Setup Guide)](#9-how-to-run-setup-guide)
10. [API Reference](#10-api-reference)
11. [Prototype vs Production](#11-prototype-vs-production)
12. [Limitations & Known Issues](#12-limitations--known-issues)

---

## 1. What is TrillBar?

TrillBar is an **end-to-end AI dubbing platform** that takes a video or audio clip in any language (Japanese anime, Korean drama, Turkish series, etc.) and produces a **professionally dubbed audio track** in Hindi, Tamil, or Telugu — in hours instead of weeks, at a fraction of traditional studio cost.

It is **not** just a translator. It:

- Preserves the **original speaker's voice character** (same voice, different language)
- Matches the **emotional tone** of the original performance (pitch, energy, speaking pace)
- Keeps the **background music and sound effects** intact
- Produces output that sounds like it was **recorded in the same studio** as the original

---

## 2. The Problem We Solve

| Problem | Traditional Studio | TrillBar |
|---|---|---|
| Cost per minute | ₹6,000–18,000 | ₹400–900 |
| Time per 30-min episode | 2–4 weeks | 4–8 hours |
| Languages at once | 1 | Up to 8 |
| Voice consistency | Varies (human actors) | Guaranteed (AI clone) |
| Regional language coverage | Hindi + Tamil only | 22 languages (roadmap) |

**The scale problem:** Netflix alone has 36,000+ hours of non-English content. Dubbing even 10% into 4 Indian languages traditionally would take **40+ years** and cost **₹12,000 Crore**. TrillBar can close this gap in months.

---

## 3. Simple User Workflow (Non-Technical)

This section is written for anyone — no tech knowledge required.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   STEP 1 — You upload a video or audio clip                     │
│                                                                 │
│   📁  Any format works: MP4, MKV, AVI, MP3, WAV                │
│        Example: a 5-minute anime scene in Japanese              │
│                                                                 │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   STEP 2 — You pick the target language                         │
│                                                                 │
│        🇮🇳  Hindi    🇮🇳  Tamil    🇮🇳  Telugu                     │
│                                                                 │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   STEP 3 — You click "Dub Now" and wait                         │
│                                                                 │
│   The system automatically does everything behind the scenes:   │
│   • Listens to the video and understands who is speaking        │
│   • Reads and translates every line of dialogue                 │
│   • Learns what each character's voice sounds like              │
│   • Speaks the translated dialogue in that same voice           │
│   • Matches the emotion (happy, angry, sad, etc.)               │
│   • Puts the music and sound effects back in                    │
│                                                                 │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   STEP 4 — You get the dubbed audio file                        │
│                                                                 │
│   🎵  A ready-to-use audio file in your chosen language         │
│   📝  A transcript showing original + translated text           │
│   ⬇   Download button — save it to your device                 │
│                                                                 │
│   The dubbed audio can be paired back with the original video   │
│   in any video editor.                                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### What does it actually feel like to use it?

Think of it like Google Translate — but instead of text, it translates **voices, emotions, and audio performances**. You press a button, the AI handles everything, and you get a result in your language spoken in the original character's voice.

---

## 4. What Goes In → What Comes Out

### INPUT

| Property | Details |
|---|---|
| **File type** | Video: `.mp4`, `.mkv`, `.avi`, `.mov` · Audio: `.mp3`, `.wav`, `.flac` |
| **Recommended length** | 1–10 minutes (prototype) |
| **Source language** | Any — auto-detected (Japanese, Korean, Chinese, Turkish, Spanish, English, etc.) |
| **Number of speakers** | 1 or more — each speaker gets their own cloned voice |
| **Audio quality** | Any — source separation cleans background noise |

**Example inputs:**
- A 3-minute anime scene (Japanese, multiple characters)
- A 5-minute K-drama dialogue clip (Korean, 2 speakers)
- A 2-minute Turkish historical drama clip (with orchestral background music)

---

### WHAT HAPPENS INSIDE (simplified)

```
Your video/audio
       │
       ▼
 🔊 LISTEN     →  The AI hears and separates the voices from the music
       │
       ▼
 📝 READ       →  The AI transcribes every word spoken, with exact timing
       │
       ▼
 🌐 TRANSLATE  →  Every line is translated into Hindi/Tamil/Telugu naturally
       │
       ▼
 🎭 CLONE      →  Each character's voice is learned and recreated by AI
       │
       ▼
 🎙 SPEAK      →  The AI speaks the translated lines in the cloned voices
       │
       ▼
 🎵 MIX        →  Original music + sound effects are added back in
       │
       ▼
 📦 OUTPUT     →  Final dubbed audio file, ready to use
```

---

### OUTPUT

| Property | Details |
|---|---|
| **File format** | `.wav` (44.1 kHz, 16-bit, stereo) |
| **Content** | Dubbed dialogue + original background music + original SFX |
| **Loudness** | Normalised to EBU R128 broadcast standard (-16 LUFS) |
| **Voice quality** | AI-cloned voice of original speakers |
| **Emotional fidelity** | Pitch and speaking pace matched to original performance |
| **Transcript** | Side-by-side table: Original text | Translated text | Speaker | Timestamp |
| **Save location** | `data/output/dubbed_{job_id}.wav` |

**Example output:**
- `dubbed_anime_hindi.wav` — 3-minute audio in Hindi, with original background music, Naruto's voice speaking Hindi
- Transcript table with 24 segments, showing each line in Japanese and Hindi

---

## 5. Full Technical Architecture

```
╔══════════════════════════════════════════════════════════════════════════╗
║                        TRILLBAR SYSTEM OVERVIEW                         ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║   ┌──────────────┐     HTTP/Upload      ┌────────────────────────────┐   ║
║   │  GRADIO UI   │ ─────────────────▶  │       FASTAPI BACKEND      │   ║
║   │  (Browser)   │ ◀─────────────────  │  POST /dub                 │   ║
║   │ gradio_ui.py │   Progress/Result   │  GET  /status/{id}         │   ║
║   └──────────────┘                     │  GET  /download/{id}       │   ║
║                                        │  GET  /transcript/{id}     │   ║
║   ┌──────────────┐                     └────────────┬───────────────┘   ║
║   │  CLI (main)  │                                  │                   ║
║   │  main.py     │ ─────────────────────────────────┘                   ║
║   └──────────────┘         calls run_pipeline()                         ║
║                                        │                                ║
║                         ┌─────────────▼──────────────┐                  ║
║                         │       PIPELINE ENGINE       │                  ║
║                         │                             │                  ║
║   ┌─────────────────────▼──────────────────────────┐ │                  ║
║   │  Stage 1: ingest.py                            │ │                  ║
║   │  ffmpeg → full_44k.wav + full_16k.wav          │ │                  ║
║   └─────────────────────┬──────────────────────────┘ │                  ║
║   ┌─────────────────────▼──────────────────────────┐ │                  ║
║   │  Stage 2a: separation.py                       │ │                  ║
║   │  Demucs → vocals.wav + no_vocals.wav           │ │                  ║
║   └──────────┬──────────────────────┬──────────────┘ │                  ║
║   ┌──────────▼──────────┐  ┌────────▼────────────┐   │                  ║
║   │  Stage 2b: ASR      │  │ no_vocals (music)   │   │                  ║
║   │  transcribe.py      │  │ kept for final mix  │   │                  ║
║   │  Whisper+pyannote   │  └────────┬────────────┘   │                  ║
║   └──────────┬──────────┘           │                │                  ║
║   ┌──────────▼──────────────────┐   │                │                  ║
║   │  Stage 3: translate.py      │   │                │                  ║
║   │  Gemini 1.5 Flash           │   │                │                  ║
║   │  (isochrony-aware)          │   │                │                  ║
║   └──────────┬──────────────────┘   │                │                  ║
║   ┌──────────▼──────────────────┐   │                │                  ║
║   │  Stage 4: synthesize.py     │   │                │                  ║
║   │  ElevenLabs API             │   │                │                  ║
║   │  Voice Clone + TTS          │   │                │                  ║
║   └──────────┬──────────────────┘   │                │                  ║
║   ┌──────────▼──────────────────┐   │                │                  ║
║   │  Stage 5a: prosody.py       │   │                │                  ║
║   │  parselmouth (F0) +         │   │                │                  ║
║   │  librosa (pitch/rate)       │   │                │                  ║
║   └──────────┬──────────────────┘   │                │                  ║
║   ┌──────────▼──────────────────┐   │                │                  ║
║   │  Stage 5b: acoustic.py      │   │                │                  ║
║   │  librosa spectral matching  │   │                │                  ║
║   └──────────┬──────────────────┘   │                │                  ║
║   ┌──────────▼──────────────────────▼──────────────┐ │                  ║
║   │  Stage 6: assemble.py                          │ │                  ║
║   │  Dialogue track + Music stem mix               │ │                  ║
║   │  pyloudnorm → EBU R128                         │ │                  ║
║   └──────────────────────┬──────────────────────────┘ │                  ║
║                          │                             │                  ║
║                          ▼                             │                  ║
║                  dubbed_{id}.wav ◀──────────────────────┘                ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 6. Pipeline — Stage by Stage

### Stage 1 — Ingestion & Preprocessing

**Module:** `pipeline/ingest.py`
**Tool:** `ffmpeg` (auto-resolved from bundled binary)

```
Input: any video/audio file (MP4, MKV, MP3, WAV, etc.)
         │
         ├──▶  full_44k.wav  (44.1 kHz stereo)   ← used for mixing
         └──▶  full_16k.wav  (16 kHz mono)        ← used for AI models
```

| Output file | Sample rate | Channels | Used for |
|---|---|---|---|
| `full_44k.wav` | 44,100 Hz | Stereo | Source separation + final mix |
| `full_16k.wav` | 16,000 Hz | Mono | ASR (Whisper) + diarization |

---

### Stage 2a — Audio Deconstruction (Source Separation)

**Module:** `pipeline/separation.py`
**Model:** Demucs `htdemucs` (CPU mode) · Fast fallback: Spleeter

```
full_44k.wav
    │
    ├──▶  vocals.wav      (dialogue / voices only)
    └──▶  no_vocals.wav   (music + sound effects — preserved intact)
```

**Why?** This is the critical first step. Without separating voices from background music, the AI cannot cleanly hear the dialogue, and the final output will have double audio — original dialogue + dubbed dialogue both playing at once.

| Mode | Speed (5-min clip) | Quality |
|---|---|---|
| Demucs (default) | ~40–70 min on CPU | High (SDR > 14 dB) |
| Spleeter (fast mode) | ~5–10 min on CPU | Medium |
| Skip separation | Instant | Low (no isolation) |

---

### Stage 2b — Transcription + Speaker Diarization

**Module:** `pipeline/transcribe.py`
**Models:** `faster-whisper` (base, CPU) + `pyannote-audio 3.x` (CPU)

```
vocals.wav
    │
    ├── [Whisper]    → WHO SAID WHAT + WHEN
    │                  {text, start_time, end_time, language}
    │
    └── [Pyannote]  → WHO IS SPEAKING
                       {SPEAKER_00: 0.5s–4.2s, SPEAKER_01: 4.5s–7.1s, ...}

Merged output: [{id, speaker_id, start, end, duration, source_text, language}]
```

**Example segment output:**
```json
{
  "id": 3,
  "speaker_id": "SPEAKER_00",
  "start": 12.4,
  "end": 15.1,
  "duration": 2.7,
  "source_text": "私はずっとここにいる",
  "source_lang": "ja"
}
```

---

### Stage 3 — Translation & Script Generation

**Module:** `pipeline/translate.py`
**Model:** Google Gemini 1.5 Flash API

**Key innovation — isochrony-aware prompting:**

Every translation request tells Gemini not just *what* to translate, but *how long the spoken result must be*. This means the translated text is naturally sized to fit the original timing slot — without the AI needing a dedicated lip-sync alignment model.

```
Prompt sent to Gemini:
────────────────────────────────────────────────────────────────────
"You are a professional dubbing translator for Indian OTT platforms.
 Time budget: 2.7 seconds.
 Translate this Japanese dialogue into Hindi.
 The translation MUST be speakable in under 2.7 seconds.
 Source text: 私はずっとここにいる"
────────────────────────────────────────────────────────────────────
Gemini response: "मैं हमेशा यहाँ रहूँगा"  ← fits in 2.7 seconds ✓
```

**Output per segment:**
```json
{
  "translated_text": "मैं हमेशा यहाँ रहूँगा",
  "target_lang": "hindi"
}
```

---

### Stage 4 — Voice Synthesis & Voice Cloning

**Module:** `pipeline/synthesize.py`
**API:** ElevenLabs `eleven_multilingual_v2` · Fallback: Sarvam AI

This is the **voice identity preservation** stage — the core differentiator of TrillBar.

```
Step 4a — Reference Extraction
  vocals.wav → pick cleanest 5–12 seconds per unique speaker
  → SPEAKER_00_ref.wav, SPEAKER_01_ref.wav, ...

Step 4b — Voice Cloning
  SPEAKER_00_ref.wav → [ElevenLabs API] → voice_id: "el_abc123"
  (The AI learns: timbre, breathiness, texture, vocal identity)

Step 4c — TTS Synthesis
  For each segment:
  translated_text + voice_id + language_code
  → [ElevenLabs TTS API] → seg_0003.wav  (spoken in cloned voice)
```

**ElevenLabs multilingual v2 supports:**
- Hindi (`hi`) · Tamil (`ta`) · Telugu (`te`)
- Cloned voice + target language = same character, new language

**Fallback behaviour:**
- No API key → error with clear message
- Free tier (no cloning) → uses a default multilingual voice
- Cloning API call fails → falls back to default voice, continues pipeline

---

### Stage 5a — Prosody Transfer

**Module:** `pipeline/prosody.py`
**Tools:** `parselmouth` (Praat) + `librosa`

Prosody = the music of speech: pitch, pace, energy, rhythm.

Without this stage, the dubbed voice would sound flat and emotionless even if the words are correct. This stage makes a crying character *sound* like they're crying in Hindi, not just saying crying words in a neutral voice.

```
Source segment (Japanese):  ~220 Hz average pitch, fast pace, high energy
                                            │
                                    [parselmouth]
                                    extract F0 curve
                                            │
Synthesised segment (Hindi): ~180 Hz average pitch, normal pace
                                            │
                                    [librosa pitch_shift]
                                    shift +2.4 semitones to match source
                                            │
                                    [librosa time_stretch]
                                    stretch to fit 2.7s duration window
                                            │
Result: Hindi speech at ~220 Hz, fast pace, high energy  ✓
```

**Three operations applied:**
1. **Pitch shift** — match F0 (fundamental frequency) mean from source
2. **Time stretch** — fit within original segment duration (±30% tolerance)
3. **Energy match** — match RMS loudness level of source segment

---

### Stage 5b — Acoustic Character Matching

**Module:** `pipeline/acoustic.py`
**Tools:** `librosa` STFT

This stage makes the dubbed voice sound like it was recorded in the **same room with the same microphone** as the original — not like a clean studio overdub.

```
Source recording fingerprint:  bright, slightly boomy (orchestral room)
Synthesised voice:             clean, flat (studio TTS output)
                                        │
                           [STFT spectral centroid analysis]
                           compute target tonal balance
                                        │
                           [Per-band gain adjustment]
                           darken/brighten synthesised audio
                           to match source spectral profile
                                        │
Result: dubbed voice sounds "placed" in the original scene  ✓
```

---

### Stage 6 — Assembly, Mix & Loudness Normalisation

**Module:** `pipeline/assemble.py`
**Tools:** `numpy` + `pyloudnorm`

```
Timeline (total_duration = 180 seconds example):

no_vocals.wav  ████████████████████████████████████████████████ (music+sfx, full length)
               │  at -3 dB to sit behind dialogue
               │
Dialogue track:
  seg_0000.wav ██                                               (0.0s – 1.8s)
  seg_0001.wav      ████                                        (2.5s – 5.2s)
  seg_0002.wav              ██                                  (6.1s – 7.8s)
  ...

Mixed output = music × 0.707 + dialogue × 1.0

↓ pyloudnorm → EBU R128 loudness normalisation → -16 LUFS
↓ peak limit → -1.0 dBFS

Output: dubbed_{job_id}.wav  (broadcast-ready)
```

**EBU R128** is the loudness standard used by Netflix, Spotify, and all major streaming platforms. The output is mix-ready with no additional processing needed.

---

## 7. Technology Stack

### AI / ML Models

| Component | Model / Tool | Purpose | Runs on |
|---|---|---|---|
| Source separation | Demucs `htdemucs` | Split dialogue from music | CPU ✓ |
| Speech recognition | faster-whisper `base` | Transcribe speech to text | CPU ✓ |
| Speaker diarization | pyannote-audio 3.x | Who speaks when | CPU ✓ |
| Translation | Google Gemini 1.5 Flash | Source → Hindi/Tamil/Telugu | API (cloud) |
| Voice cloning | ElevenLabs Instant Cloning | Learn speaker voice identity | API (cloud) |
| TTS synthesis | ElevenLabs `eleven_multilingual_v2` | Speak translated text | API (cloud) |
| Pitch analysis | Praat via parselmouth | Extract F0 (fundamental frequency) | CPU ✓ |
| Pitch/rate adjust | librosa | Shift pitch, stretch time | CPU ✓ |
| Acoustic matching | librosa STFT | Match tonal fingerprint | CPU ✓ |
| Loudness norm | pyloudnorm (EBU R128) | Broadcast loudness standard | CPU ✓ |

### Python Libraries

| Library | Version | Role |
|---|---|---|
| `librosa` | ≥0.10 | Core audio processing |
| `soundfile` | ≥0.12 | Audio file I/O |
| `pydub` | ≥0.25 | Audio segment mixing |
| `praat-parselmouth` | ≥0.4.3 | Praat (speech science tool) |
| `faster-whisper` | ≥1.0 | OpenAI Whisper, optimised for CPU |
| `demucs` | ≥4.0 | Meta's source separation model |
| `pyannote.audio` | ≥3.1 | Speaker diarization |
| `google-generativeai` | ≥0.7 | Gemini API SDK |
| `requests` | ≥2.31 | ElevenLabs/Sarvam API calls |
| `fastapi` | ≥0.104 | REST API backend |
| `gradio` | 4.x | Web UI |
| `pyloudnorm` | ≥0.1.1 | EBU R128 loudness |

### External Services (APIs)

| Service | Used for | Cost model | Required |
|---|---|---|---|
| Google Gemini API | Translation | Pay-per-token (~free for prototype) | ✅ Yes |
| ElevenLabs API | Voice cloning + TTS | Creator plan ($22/mo) for cloning | ✅ Yes |
| HuggingFace Hub | Download pyannote models | Free (token required) | Optional |
| Sarvam AI | Indian-language TTS alternative | API subscription | Optional |

---

## 8. Project File Structure

```
trillbar/
│
├── 📄 main.py               ← CLI: python main.py clip.mp4 --lang hindi
├── 📄 api.py                ← FastAPI REST backend
├── 📄 gradio_ui.py          ← Gradio web UI (browser interface)
├── 📄 config.py             ← All configuration (reads from .env)
├── 📄 requirements.txt      ← Python dependencies
├── 📄 .env.example          ← Template — copy to .env and fill in keys
│
├── 📁 pipeline/             ← Core processing modules
│   ├── ingest.py            Stage 1: Extract audio from video
│   ├── separation.py        Stage 2a: Demucs source separation
│   ├── transcribe.py        Stage 2b: Whisper ASR + pyannote diarization
│   ├── translate.py         Stage 3: Gemini translation
│   ├── synthesize.py        Stage 4: ElevenLabs voice cloning + TTS
│   ├── prosody.py           Stage 5a: Pitch + rate matching
│   ├── acoustic.py          Stage 5b: Spectral acoustic matching
│   └── assemble.py          Stage 6: Final audio assembly + loudness
│
├── 📁 utils/                ← Shared helpers
│   ├── audio.py             Audio I/O, normalise, mix, convert
│   └── timing.py            Segment data structures, SRT export
│
└── 📁 data/                 ← Runtime data (auto-created)
    ├── voice_profiles/      Extracted reference audio per speaker
    ├── output/              Final dubbed audio files
    └── temp/                Intermediate files per job
        └── {job_id}/
            ├── full_44k.wav
            ├── full_16k.wav
            ├── stems/
            │   ├── vocals.wav
            │   └── no_vocals.wav
            ├── source_segs/    Per-segment source audio slices
            ├── synth/          TTS output per segment
            ├── adjusted/       After prosody transfer
            └── matched/        After acoustic matching
```

---

## 9. How to Run (Setup Guide)

### Prerequisites

- Python 3.10 or higher
- Internet connection (for Gemini + ElevenLabs API calls)
- API keys (see below)

### Step 1 — Get API Keys

| Key | Where to get it | Free? |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) | ✅ Free tier available |
| `ELEVENLABS_API_KEY` | elevenlabs.io → Profile → API Key | ⚠️ Creator plan ($22/mo) for voice cloning |
| `HUGGINGFACE_TOKEN` | huggingface.co → Settings → Tokens | ✅ Free |

> For HuggingFace: Also accept the model license at
> `huggingface.co/pyannote/speaker-diarization-3.1`

### Step 2 — Set Up Environment

```bash
# Copy the template
cp .env.example .env

# Edit .env and add your keys:
# GEMINI_API_KEY=AIza...
# ELEVENLABS_API_KEY=sk_...
# HUGGINGFACE_TOKEN=hf_...
```

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Run (choose one)

#### Option A: Web UI (recommended for demos)

```bash
python gradio_ui.py
```
Then open your browser at: `http://localhost:7860`

Upload your video, pick a language, click **Dub Now**.

---

#### Option B: Command Line

```bash
# Full pipeline (Demucs separation — slow on CPU)
python main.py my_anime_clip.mp4 --lang hindi

# Fast mode (skip source separation — good for testing)
python main.py my_anime_clip.mp4 --lang hindi --skip-separation

# Telugu, with a custom output filename
python main.py kdrama.mkv --lang telugu --output dubbed_kdrama_telugu.wav

# Tamil, verbose logging
python main.py clip.mp4 --lang tamil --verbose
```

**All CLI flags:**

| Flag | Description |
|---|---|
| `--lang` | Target language: `hindi`, `tamil`, `telugu` (required) |
| `--skip-separation` | Skip Demucs (much faster, lower quality) |
| `--skip-prosody` | Skip pitch/rate matching |
| `--skip-acoustic` | Skip spectral matching |
| `--job-id` | Custom job ID for temp file isolation |
| `--output` | Custom output filename |
| `--verbose` | Debug-level logging |

---

#### Option C: REST API

```bash
# Start the server
uvicorn api:app --host 0.0.0.0 --port 8000

# Submit a job
curl -X POST http://localhost:8000/dub \
  -F "file=@my_clip.mp4" \
  -F "target_language=hindi" \
  -F "skip_separation=false"

# Poll for status
curl http://localhost:8000/status/{job_id}

# Download when done
curl http://localhost:8000/download/{job_id} -o dubbed.wav

# Get transcript
curl http://localhost:8000/transcript/{job_id}
```

---

### Expected Processing Times (CPU)

| Stage | Time (5-min clip) | Notes |
|---|---|---|
| Audio extraction | < 30 sec | Fast (ffmpeg) |
| Source separation | 40–70 min | Demucs on CPU — skip with `--skip-separation` for testing |
| Transcription + diarization | 5–15 min | Whisper base on CPU |
| Translation | 1–3 min | Gemini API — fast |
| Voice cloning | 1–2 min | ElevenLabs API — one call per speaker |
| TTS synthesis | 5–15 min | ElevenLabs API — one call per segment (~20–40 calls) |
| Prosody + acoustic | 2–5 min | librosa on CPU |
| Assembly | < 1 min | numpy mixing |
| **Total (with separation)** | **~1.5–2 hours** | For a 5-min clip |
| **Total (skip separation)** | **~15–30 min** | Good for testing |

---

## 10. API Reference

### `POST /dub`

Submit a dubbing job.

**Request (multipart form):**

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | ✅ | Video or audio file |
| `target_language` | string | ✅ | `hindi`, `tamil`, or `telugu` |
| `skip_separation` | bool | — | Skip Demucs (default: false) |
| `skip_prosody` | bool | — | Skip prosody transfer (default: false) |
| `skip_acoustic` | bool | — | Skip acoustic matching (default: false) |

**Response:**
```json
{ "job_id": "a3f7b2c1d9", "status": "queued" }
```

---

### `GET /status/{job_id}`

Poll job progress.

**Response:**
```json
{
  "id": "a3f7b2c1d9",
  "status": "running",
  "stage": "Synthesising dubbed speech (ElevenLabs TTS)",
  "progress": 60,
  "target_language": "hindi",
  "input_file": "anime_clip.mp4",
  "duration": null,
  "elapsed": null,
  "error": null,
  "ready": false
}
```

**Status values:** `queued` → `running` → `done` | `error`

---

### `GET /download/{job_id}`

Download the finished `.wav` file. Returns 409 if job is not done yet.

---

### `GET /transcript/{job_id}`

Get the full transcript.

**Response:**
```json
{
  "job_id": "a3f7b2c1d9",
  "segments": [
    {
      "id": 0,
      "speaker_id": "SPEAKER_00",
      "start": 1.2,
      "end": 3.9,
      "source_text": "君はどこへ行くの？",
      "translated_text": "तुम कहाँ जा रहे हो?"
    }
  ]
}
```

---

### `GET /health`

Health check. Returns `{ "status": "ok", "version": "0.1.0" }`.

---

## 11. Prototype vs Production

| Feature | Prototype (now) | Production (roadmap) |
|---|---|---|
| Languages | Hindi, Tamil, Telugu | 22 scheduled Indian languages |
| TTS model | ElevenLabs API | VITS-2 + GE2E + HiFi-GAN (local) |
| Voice cloning | ElevenLabs Instant Clone | VALL-E codec language model |
| Emotion transfer | F0 + rate + energy matching | Full GST (Global Style Tokens) |
| Acoustic matching | Spectral centroid (librosa) | WORLD vocoder spectral envelope |
| Source separation | Standard htdemucs | htdemucs fine-tuned on Indian film audio |
| Translation | Gemini (isochrony hint) | AI dialogue adaptation engine |
| Dialogue timing | Prompt-based isochrony | CTC phoneme-alignment scoring |
| Lip sync | ❌ Not included | Wav2Lip + VideoReTalking |
| Regional dialects | ❌ Not included | AI dialect engine (Mumbai Hindi, etc.) |
| Editor layer | ❌ Not included | Browser QA workstation |
| Compute | CPU-only (API for heavy ML) | GPU cluster |
| Turnaround (30-min ep.) | Several hours | 4–8 hours |
| MOS target | 3.5+ / 5.0 | 4.21+ / 5.0 |

---

## 12. Limitations & Known Issues

### Prototype Limitations

| Limitation | Impact | Workaround |
|---|---|---|
| Demucs is very slow on CPU | 40–70 min for 5-min clip | Use `--skip-separation` for testing |
| ElevenLabs requires paid plan for voice cloning | Free tier uses a default voice (no identity) | Get Creator plan ($22/mo) or use Sarvam AI |
| No lip sync | Video requires manual sync in a video editor | Planned for production |
| No UI editor | Cannot fine-tune individual segments | CLI for now |
| Recommended max 10-min clips | Longer clips → very long processing time | Split into segments before uploading |
| pyannote needs HuggingFace token | Without it, all segments assigned to one speaker | Set HUGGINGFACE_TOKEN in .env |
| Gemini translation not perfect | Cultural nuance may be lost on idioms | Review transcript and re-translate if needed |

### Quality Expectations (Prototype)

| Metric | Prototype target | Production target |
|---|---|---|
| MOS (naturalness) | 3.2–3.8 / 5.0 | 4.1–4.3 / 5.0 |
| Voice similarity | Moderate | High (VALL-E codec) |
| Emotional fidelity | ~70% of original | ~87% (full GST) |
| Timing accuracy | ±15% of original | ±5% (phoneme alignment) |
| Acoustic naturalness | Basic | Full room IR transfer |

---

## Data Flow Summary (One-page view)

```
INPUT: anime_clip.mp4 (Japanese, 5 min, 2 speakers, orchestral background)
  │
  │  [ffmpeg]
  ├──▶ full_44k.wav  ──────────────────────────────────────────────────────┐
  └──▶ full_16k.wav                                                        │
            │                                                              │
            │  [Demucs htdemucs]                                           │
            ├──▶ vocals.wav     (dialogue only)                            │
            └──▶ no_vocals.wav  (music+SFX) ─────────────────────────────┐│
                      │                                                   ││
                      │  [faster-whisper + pyannote]                      ││
                      ▼                                                   ││
               Segments: 28 segments, 2 speakers                         ││
               [{id:0, speaker:00, 1.2s–3.9s, "君はどこへ行くの？"}, ...]  ││
                      │                                                   ││
                      │  [Gemini 1.5 Flash]                               ││
                      ▼                                                   ││
               Translated: [{translated_text: "तुम कहाँ जा रहे हो?"}, ...]  ││
                      │                                                   ││
                      │  [ElevenLabs: voice clone + TTS]                  ││
                      ▼                                                   ││
               Synthesised: [seg_0000.wav, seg_0001.wav, ...] (Hindi)    ││
                      │                                                   ││
                      │  [parselmouth + librosa: F0 shift + time stretch] ││
                      ▼                                                   ││
               Adjusted:   [adj_0000.wav, adj_0001.wav, ...]             ││
                      │                                                   ││
                      │  [librosa STFT: spectral centroid EQ]             ││
                      ▼                                                   ││
               Matched:    [matched_0000.wav, matched_0001.wav, ...]     ││
                      │                                                   ││
                      └─────────────────────┐                            ││
                                            │  [numpy mix + pyloudnorm]  ││
                                            ◀────────────────────────────┘│
                                            ◀────────────────────────────┘
                                            │
                                            ▼
OUTPUT: data/output/dubbed_a3f7b2c1.wav
        - 5 min stereo WAV, 44.1 kHz
        - Hindi dialogue in SPEAKER_00's cloned voice + SPEAKER_01's cloned voice
        - Original orchestral music preserved
        - EBU R128 normalised (-16 LUFS)
        - Pitch-matched to original emotional performance

ALSO:  Transcript table (28 rows):
        Speaker    | Japanese          | Hindi               | Time
        SPEAKER_00 | 君はどこへ行くの？  | तुम कहाँ जा रहे हो?  | 1.2s – 3.9s
        ...
```

---

*TrillBar Prototype v0.1 · Built for India's OTT Era · 2025*
