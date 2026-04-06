"""Module 4 — Voice Synthesis & Voice Cloning.

Flow per speaker:
  1. Extract a clean 5–12 s reference clip from the vocals stem.
  2. Upload reference to ElevenLabs → get a cloned voice_id.
  3. For each segment belonging to that speaker, call ElevenLabs TTS
     with the cloned voice_id to synthesise the translated text.
  4. (Optional) Delete cloned voices from ElevenLabs after the job is done.

If ELEVENLABS_API_KEY is not set or voice cloning fails (free-tier), a
default pre-existing multilingual voice is used as fallback.

If TTS_BACKEND=sarvam, Sarvam AI's text-to-speech API is used instead
(better quality for Tamil / Telugu).
"""

import logging
import os
import time
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from backend import config
from backend.utils.audio import load_audio, save_audio, rms_energy, stereo_to_mono, trim_silence, normalize_peak
from backend.utils.timing import Segment

logger = logging.getLogger(__name__)

# ── Emotion → ElevenLabs voice_settings mapping ──────────────────────────────
# Each emotion maps to (style, stability, similarity_boost).
# emotion_intensity (0–1) interpolates between neutral and the target row.
EMOTION_VOICE_SETTINGS: dict[str, tuple[float, float, float]] = {
    "neutral":  (0.00, 0.50, 1.00),
    "happy":    (0.35, 0.35, 0.95),
    "excited":  (0.45, 0.30, 0.90),
    "angry":    (0.50, 0.30, 0.90),
    "sad":      (0.25, 0.45, 1.00),
    "fear":     (0.40, 0.30, 0.95),
    "surprise": (0.45, 0.30, 0.90),
    "calm":     (0.15, 0.55, 1.00),
    "disgust":  (0.35, 0.40, 0.95),
}

def _emotion_voice_settings(emotion: str | None, intensity: float = 1.0) -> dict:
    """Return ElevenLabs voice_settings dict modulated by emotion."""
    neutral = EMOTION_VOICE_SETTINGS["neutral"]
    target = EMOTION_VOICE_SETTINGS.get(emotion or "neutral", neutral)
    t = max(0.0, min(1.0, intensity))
    style = neutral[0] + t * (target[0] - neutral[0])
    stability = neutral[1] + t * (target[1] - neutral[1])
    sim_boost = neutral[2] + t * (target[2] - neutral[2])
    return {
        "stability": round(stability, 2),
        "similarity_boost": round(sim_boost, 2),
        "style": round(style, 2),
        "use_speaker_boost": True,
    }


# ── Voice profile store: speaker_id → {voice_id, reference_path} ─────────────
_voice_profiles: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_voice_profiles(
    segments: list[Segment],
    vocals_44k_path: str | Path,
    job_id: str = "default",
) -> dict[str, dict]:
    """Extract reference audio and clone a voice for each unique speaker.

    Returns:
        {speaker_id: {"reference_path": Path, "voice_id": str | None}}
    """
    vocals_44k_path = Path(vocals_44k_path)
    profiles_dir = config.VOICE_PROFILES_DIR / job_id
    profiles_dir.mkdir(parents=True, exist_ok=True)

    audio_44k, sr = load_audio(vocals_44k_path)
    audio_mono = stereo_to_mono(audio_44k)

    speakers = {}
    for seg in segments:
        sid = seg.get("speaker_id", "SPEAKER_00")
        if sid not in speakers:
            speakers[sid] = []
        speakers[sid].append(seg)

    profiles: dict[str, dict] = {}

    for speaker_id, speaker_segs in speakers.items():
        ref_path = profiles_dir / f"{speaker_id}_ref.wav"

        if not ref_path.exists():
            ref_audio = _extract_reference_audio(
                audio_mono, sr, speaker_segs
            )
            save_audio(ref_audio, ref_path, sr)
            logger.info(
                "Extracted reference audio for %s (%.1f s)",
                speaker_id,
                len(ref_audio) / sr,
            )

        voice_id = _clone_voice(speaker_id, ref_path)
        profiles[speaker_id] = {
            "reference_path": ref_path,
            "voice_id": voice_id,
        }

    _voice_profiles.update(profiles)
    return profiles


def synthesize_segments(
    segments: list[Segment],
    voice_profiles: dict[str, dict],
    target_language: str,
    job_id: str = "default",
) -> list[Segment]:
    """Synthesise translated text for every segment using cloned voices.

    Adds 'synth_audio_path' to each segment and returns the updated list.
    """
    lang_cfg = config.LANGUAGE_CONFIGS[target_language]
    synth_dir = config.TEMP_DIR / job_id / "synth"
    synth_dir.mkdir(parents=True, exist_ok=True)

    result = []
    for seg in segments:
        text = seg.get("translated_text", "").strip()
        if not text:
            result.append(dict(seg))
            continue

        speaker_id = seg.get("speaker_id", "SPEAKER_00")
        voice_id = voice_profiles.get(speaker_id, {}).get("voice_id")

        out_path = synth_dir / f"seg_{seg['id']:04d}.wav"

        if not out_path.exists():
            _synthesize_one(
                text=text,
                voice_id=voice_id,
                lang_cfg=lang_cfg,
                target_language=target_language,
                out_path=out_path,
                emotion=seg.get("emotion"),
                emotion_intensity=seg.get("emotion_intensity", 1.0),
            )
            time.sleep(0.25)  # polite rate limit

        new_seg = dict(seg)
        new_seg["synth_audio_path"] = str(out_path)
        result.append(new_seg)
        logger.debug("Synthesised segment %d → %s", seg["id"], out_path.name)

    logger.info("Synthesis complete: %d segments.", len(result))
    return result


def cleanup_cloned_voices(voice_profiles: dict[str, dict]) -> None:
    """Delete cloned voices from ElevenLabs to free quota."""
    if not config.ELEVENLABS_API_KEY:
        return
    for speaker_id, profile in voice_profiles.items():
        vid = profile.get("voice_id")
        if vid and not _is_fallback_voice(vid):
            try:
                _delete_voice(vid)
                logger.info("Deleted cloned voice for %s (%s)", speaker_id, vid)
            except Exception as e:
                logger.warning("Could not delete voice %s: %s", vid, e)


# ─────────────────────────────────────────────────────────────────────────────
# Reference audio extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_reference_audio(
    mono_audio: np.ndarray,
    sr: int,
    segments: list[Segment],
) -> np.ndarray:
    """Pick the single best segment for voice reference (cleanest, right length)."""
    min_samples = int(config.MIN_REF_DURATION * sr)
    max_samples = int(config.MAX_REF_DURATION * sr)
    total_samples = len(mono_audio)

    # Score each segment by (duration within target range) * RMS energy
    best_score = -1.0
    best_clip = None

    for seg in segments:
        start = int(seg["start"] * sr)
        end = int(seg["end"] * sr)
        start = max(0, start)
        end = min(total_samples, end)
        clip = mono_audio[start:end]

        n = len(clip)
        if n < min_samples:
            continue  # too short

        # Trim to max duration
        clip = clip[:max_samples]
        score = rms_energy(clip) * min(n, max_samples)
        if score > best_score:
            best_score = score
            best_clip = clip

    if best_clip is None:
        # Fallback: concatenate all segments until we hit MIN_REF_DURATION
        chunks = []
        total = 0
        for seg in segments:
            start = max(0, int(seg["start"] * sr))
            end = min(total_samples, int(seg["end"] * sr))
            chunk = mono_audio[start:end]
            chunks.append(chunk)
            total += len(chunk)
            if total >= min_samples:
                break
        best_clip = np.concatenate(chunks)[:max_samples] if chunks else np.zeros(min_samples)

    return best_clip


# ─────────────────────────────────────────────────────────────────────────────
# ElevenLabs API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clone_voice(speaker_id: str, ref_paths: list[Path] | Path) -> str | None:
    """Upload reference audio file(s) to ElevenLabs and return the new voice_id.

    Supports multiple reference files for higher-fidelity cloning.
    Returns None if API key is missing; returns fallback voice_id on error.
    """
    if not config.ELEVENLABS_API_KEY:
        logger.warning("No ELEVENLABS_API_KEY — using fallback voice.")
        return None

    # Normalize to list
    if isinstance(ref_paths, Path):
        ref_paths = [ref_paths]

    try:
        url = f"{config.ELEVENLABS_BASE_URL}/voices/add"
        headers = {"xi-api-key": config.ELEVENLABS_API_KEY}

        # Build multipart files list — ElevenLabs accepts multiple "files" fields
        file_handles = []
        files_list = []
        for rp in ref_paths:
            fh = open(rp, "rb")
            file_handles.append(fh)
            files_list.append(("files", (rp.name, fh, "audio/wav")))

        data = {
            "name": f"TrillBar_{speaker_id}_{int(time.time())}",
            "description": "Auto-cloned voice for TrillBar prototype",
            "labels": '{"use_case": "dubbing", "source": "trillbar"}',
            "remove_background_noise": "true",
        }

        try:
            resp = requests.post(
                url, headers=headers, files=files_list, data=data, timeout=120,
            )
        finally:
            for fh in file_handles:
                fh.close()

        if resp.status_code == 422:
            logger.warning(
                "ElevenLabs voice cloning returned 422 (likely free-tier restriction). "
                "Falling back to default voice."
            )
            return None

        resp.raise_for_status()
        voice_id = resp.json()["voice_id"]
        logger.info(
            "Cloned voice for %s → voice_id=%s (%d reference files)",
            speaker_id, voice_id, len(ref_paths),
        )
        return voice_id

    except requests.exceptions.HTTPError as e:
        logger.warning("Voice cloning failed for %s: %s — response: %s", speaker_id, e, e.response.text[:500] if e.response else "no response")
        return None
    except Exception as e:
        logger.warning("Voice cloning failed for %s: %s — using fallback.", speaker_id, e)
        return None


def _synthesize_one(
    text: str,
    voice_id: str | None,
    lang_cfg: dict,
    target_language: str,
    out_path: Path,
    emotion: str | None = None,
    emotion_intensity: float = 1.0,
) -> None:
    """Call TTS API and save result to out_path (WAV)."""
    if config.TTS_BACKEND == "sarvam" and config.SARVAM_API_KEY:
        _synth_sarvam(text, lang_cfg["sarvam_code"], out_path)
        return

    # ElevenLabs (default)
    _synth_elevenlabs(text, voice_id, lang_cfg["elevenlabs_code"], target_language, out_path,
                      emotion=emotion, emotion_intensity=emotion_intensity)


def _synth_elevenlabs(
    text: str,
    voice_id: str | None,
    lang_code: str,
    target_language: str,
    out_path: Path,
    emotion: str | None = None,
    emotion_intensity: float = 1.0,
) -> None:
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not set. Cannot synthesise speech. "
            "Please add it to your .env file."
        )

    # Use cloned voice or fallback
    vid = voice_id or config.ELEVENLABS_FALLBACK_VOICES.get(target_language, "pNInz6obpgDQGcFmaJgB")

    url = f"{config.ELEVENLABS_BASE_URL}/text-to-speech/{vid}"
    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    voice_settings = _emotion_voice_settings(emotion, emotion_intensity)
    payload = {
        "text": text,
        "model_id": config.ELEVENLABS_MODEL,
        "language_code": lang_code,
        "voice_settings": voice_settings,
    }

    resp = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
    resp.raise_for_status()

    # Save as MP3 first, then convert to WAV
    mp3_path = out_path.with_suffix(".mp3")
    with open(mp3_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    _mp3_to_wav(mp3_path, out_path)
    mp3_path.unlink(missing_ok=True)


def _synth_sarvam(text: str, lang_code: str, out_path: Path) -> None:
    """Call Sarvam AI TTS endpoint."""
    headers = {
        "api-subscription-key": config.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": [text],
        "target_language_code": lang_code,
        "speaker": "meera",       # default Indian female voice
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.0,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": "bulbul:v1",
    }
    resp = requests.post(config.SARVAM_TTS_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()

    import base64
    audio_b64 = resp.json()["audios"][0]
    audio_bytes = base64.b64decode(audio_b64)

    wav_path = out_path
    with open(wav_path, "wb") as f:
        f.write(audio_bytes)


def _mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
    """Convert MP3 to WAV using ffmpeg."""
    import subprocess
    from backend.pipeline.ingest import _ffmpeg_bin
    cmd = [
        _ffmpeg_bin(), "-y",
        "-i", str(mp3_path),
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"MP3→WAV conversion failed:\n{result.stderr}")


def _delete_voice(voice_id: str) -> None:
    url = f"{config.ELEVENLABS_BASE_URL}/voices/{voice_id}"
    headers = {"xi-api-key": config.ELEVENLABS_API_KEY}
    resp = requests.delete(url, headers=headers, timeout=30)
    resp.raise_for_status()


def _is_fallback_voice(voice_id: str) -> bool:
    return voice_id in set(config.ELEVENLABS_FALLBACK_VOICES.values())


# ─────────────────────────────────────────────────────────────────────────────
# Speech-to-Speech (Voice Artist mode)
# ─────────────────────────────────────────────────────────────────────────────

def clone_voice_from_audio(
    ref_audio_paths: str | Path | list[str | Path],
    speaker_id: str = "ACTOR",
) -> str | None:
    """Clone a voice from one or more reference audio files. Returns voice_id."""
    if isinstance(ref_audio_paths, (str, Path)):
        ref_audio_paths = [Path(ref_audio_paths)]
    else:
        ref_audio_paths = [Path(p) for p in ref_audio_paths]
    return _clone_voice(speaker_id, ref_audio_paths)


def speech_to_speech(
    voice_id: str,
    input_audio_path: str | Path,
    output_path: str | Path,
    max_chunk_sec: float = 45.0,
    emotion: str | None = None,
    emotion_intensity: float = 1.0,
) -> Path:
    """Convert input audio to the cloned voice using ElevenLabs Speech-to-Speech.

    Long audio is split into chunks (default 30s) for better quality,
    then reassembled. ElevenLabs produces more accurate clones on
    shorter segments.

    Args:
        voice_id: ElevenLabs voice ID (from cloning).
        input_audio_path: Path to the voice artist's dialogue audio.
        output_path: Where to save the converted WAV.
        max_chunk_sec: Maximum chunk duration in seconds for STS calls.

    Returns:
        Path to the output WAV file.
    """
    input_audio_path = Path(input_audio_path)
    output_path = Path(output_path)

    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not set.")

    from backend.utils.audio import load_audio, save_audio, get_duration

    duration = get_duration(str(input_audio_path))

    if duration <= max_chunk_sec:
        # Short audio — single API call
        _sts_single(voice_id, input_audio_path, output_path,
                     emotion=emotion, emotion_intensity=emotion_intensity)
    else:
        # Long audio — split into chunks, convert each, reassemble
        audio, sr = load_audio(str(input_audio_path))
        if audio.ndim == 2:
            audio = audio.mean(axis=0)

        chunk_samples = int(max_chunk_sec * sr)
        chunks_dir = output_path.parent / "sts_chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        converted_chunks = []
        num_chunks = (len(audio) + chunk_samples - 1) // chunk_samples
        for i in range(0, len(audio), chunk_samples):
            chunk_idx = i // chunk_samples
            chunk = audio[i:i + chunk_samples]
            chunk_path = chunks_dir / f"chunk_{chunk_idx:03d}.wav"
            save_audio(chunk, chunk_path, sr)

            out_chunk = chunks_dir / f"converted_{chunk_idx:03d}.wav"
            logger.info("STS chunk %d/%d (%.1f s)", chunk_idx + 1, num_chunks, len(chunk) / sr)
            _sts_single(voice_id, chunk_path, out_chunk,
                         emotion=emotion, emotion_intensity=emotion_intensity)
            time.sleep(0.5)  # rate limit

            conv_audio, conv_sr = load_audio(str(out_chunk))
            if conv_audio.ndim == 2:
                conv_audio = conv_audio.mean(axis=0)
            converted_chunks.append(conv_audio)

        # Reassemble with short crossfade
        crossfade = int(0.02 * sr)  # 20ms
        assembled = converted_chunks[0]
        for chunk in converted_chunks[1:]:
            overlap = min(crossfade, len(assembled), len(chunk))
            if overlap > 0:
                fade_out = np.linspace(1.0, 0.0, overlap)
                fade_in = np.linspace(0.0, 1.0, overlap)
                assembled[-overlap:] *= fade_out
                chunk = chunk.copy()
                chunk[:overlap] *= fade_in
                assembled[-overlap:] += chunk[:overlap]
                assembled = np.concatenate([assembled, chunk[overlap:]])
            else:
                assembled = np.concatenate([assembled, chunk])

        save_audio(assembled, output_path, sr)
        logger.info("Reassembled %d chunks → %s", len(converted_chunks), output_path.name)

    return output_path


def _sts_single(
    voice_id: str,
    input_path: Path,
    output_path: Path,
    emotion: str | None = None,
    emotion_intensity: float = 1.0,
) -> None:
    """Single Speech-to-Speech API call."""
    url = f"{config.ELEVENLABS_BASE_URL}/speech-to-speech/{voice_id}"
    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
    }
    # Use emotion-aware settings, with STS-specific base (higher stability)
    vs = _emotion_voice_settings(emotion, emotion_intensity)
    vs["stability"] = max(vs["stability"], 0.45)  # STS needs slightly higher stability
    import json as _json
    data = {
        "model_id": "eleven_multilingual_sts_v2",
        "output_format": "mp3_44100_192",
        "voice_settings": _json.dumps(vs),
    }

    with open(input_path, "rb") as f:
        files = {"audio": (input_path.name, f, "audio/wav")}
        resp = requests.post(
            url, headers=headers, data=data, files=files,
            stream=True, timeout=180,
        )

    if resp.status_code != 200:
        logger.error("STS error %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()

    mp3_path = output_path.with_suffix(".mp3")
    with open(mp3_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    _mp3_to_wav(mp3_path, output_path)
    mp3_path.unlink(missing_ok=True)

    logger.info("Speech-to-speech conversion complete → %s", output_path.name)


# ─────────────────────────────────────────────────────────────────────────────
# Segment reference audio extractor (for prosody module)
# ─────────────────────────────────────────────────────────────────────────────

def extract_segment_audio(
    segments: list[Segment],
    vocals_44k_path: str | Path,
    job_id: str = "default",
) -> list[Segment]:
    """Slice the vocals stem per segment and store in source_audio_path."""
    vocals_path = Path(vocals_44k_path)
    audio, sr = load_audio(vocals_path)
    audio_mono = stereo_to_mono(audio)

    segs_dir = config.TEMP_DIR / job_id / "source_segs"
    segs_dir.mkdir(parents=True, exist_ok=True)

    result = []
    total_samples = len(audio_mono)
    for seg in segments:
        start = max(0, int(seg["start"] * sr))
        end = min(total_samples, int(seg["end"] * sr))
        clip = audio_mono[start:end]

        seg_path = segs_dir / f"src_{seg['id']:04d}.wav"
        if not seg_path.exists():
            save_audio(clip, seg_path, sr)

        new_seg = dict(seg)
        new_seg["source_audio_path"] = str(seg_path)
        result.append(new_seg)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Character detection (for multi-character mode)
# ─────────────────────────────────────────────────────────────────────────────

def detect_characters(
    segments: list[Segment],
    vocals_44k_path: str | Path,
    job_id: str = "default",
) -> list[dict]:
    """Group segments by speaker and extract a preview audio clip per character.

    Returns:
        [{"speaker_id": str, "segment_count": int, "total_duration": float,
          "preview_path": str, "segment_ids": list[int]}]
    """
    vocals_path = Path(vocals_44k_path)
    audio, sr = load_audio(vocals_path)
    audio_mono = stereo_to_mono(audio)

    preview_dir = config.TEMP_DIR / job_id / "char_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    # Group by speaker
    speakers: dict[str, list[Segment]] = {}
    for seg in segments:
        sid = seg.get("speaker_id", "SPEAKER_00")
        speakers.setdefault(sid, []).append(seg)

    characters = []
    total_samples = len(audio_mono)
    for sid, segs in sorted(speakers.items()):
        total_dur = sum(s["end"] - s["start"] for s in segs)

        # Extract ~5s preview from the longest contiguous segment
        best_seg = max(segs, key=lambda s: s["end"] - s["start"])
        start = max(0, int(best_seg["start"] * sr))
        end = min(total_samples, int(best_seg["end"] * sr))
        preview_clip = audio_mono[start:end]
        # Cap at 5 seconds
        max_samples = int(5.0 * sr)
        if len(preview_clip) > max_samples:
            preview_clip = preview_clip[:max_samples]

        preview_path = preview_dir / f"preview_{sid}.wav"
        save_audio(preview_clip, preview_path, sr)

        characters.append({
            "speaker_id": sid,
            "segment_count": len(segs),
            "total_duration": round(total_dur, 1),
            "preview_path": str(preview_path),
            "segment_ids": [s["id"] for s in segs],
        })

    logger.info("Detected %d characters: %s", len(characters),
                ", ".join(f"{c['speaker_id']}({c['segment_count']} segs)" for c in characters))
    return characters
