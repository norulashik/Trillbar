"""TrillBar — CLI entry point.

Usage:
    python main.py <input_file> --lang hindi [options]

Examples:
    python main.py anime_clip.mp4 --lang hindi
    python main.py kdrama.mkv --lang telugu --skip-separation
    python main.py clip.mp4 --lang tamil --job-id my_test
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Configure logging before importing pipeline modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("trillbar")


def run_pipeline(
    input_file: str,
    target_language: str,
    job_id: str,
    skip_separation: bool = False,
    skip_prosody: bool = False,
    skip_acoustic: bool = False,
    output_filename: str | None = None,
    progress_callback=None,
    script_text: str | None = None,
) -> dict:
    """Run the full TrillBar dubbing pipeline.

    Args:
        input_file: Path to the input video or audio file.
        target_language: One of 'hindi', 'tamil', 'telugu'.
        job_id: Unique identifier for this job (used for temp file isolation).
        skip_separation: If True, skip Demucs and use raw audio as dialogue stem.
        skip_prosody: If True, skip prosody transfer (faster, lower quality).
        skip_acoustic: If True, skip acoustic matching.
        output_filename: Custom output filename.
        progress_callback: Optional callable(stage: str, pct: float) for UI updates.

    Returns:
        {
            "output_path": Path,
            "segments": list[Segment],
            "duration": float,
            "elapsed": float,
        }
    """
    from backend.pipeline import ingest, separation, transcribe, translate, synthesize, prosody, acoustic, assemble
    from backend.utils.timing import merge_short_segments

    def _progress(stage: str, pct: float):
        logger.info("[%3d%%] %s", int(pct), stage)
        if progress_callback:
            progress_callback(stage, pct)

    start_time = time.time()

    # ── Stage 1: Ingest ───────────────────────────────────────────────────
    _progress("Extracting audio from video", 5)
    audio_paths = ingest.extract_audio(input_file, job_id=job_id)
    total_duration = audio_paths["duration"]
    logger.info("Duration: %.1f s", total_duration)

    # ── Stage 2: Source Separation ────────────────────────────────────────
    if skip_separation:
        _progress("Skipping source separation (--skip-separation)", 15)
        stems = separation.skip_separation(audio_paths["full_44k"], job_id=job_id)
    else:
        _progress("Separating stems with Demucs (CPU — may take a while)", 10)
        stems = separation.separate_stems(audio_paths["full_44k"], job_id=job_id)

    # ── Stage 2b: Convert vocals to 16 kHz for ASR ────────────────────────
    vocals_16k = transcribe.convert_vocals_to_16k(stems["vocals"], job_id=job_id)

    # ── Stage 3: Transcribe + Diarize ─────────────────────────────────────
    _progress("Transcribing audio (Whisper + speaker diarization)", 25)
    segments = transcribe.transcribe_and_diarize(
        audio_16k_path=audio_paths["full_16k"],
        vocals_16k_path=vocals_16k,
    )
    segments = merge_short_segments(segments, min_duration=0.5, gap_threshold=0.3)
    logger.info("Segments after merge: %d", len(segments))

    # ── Stage 4: Extract per-segment source audio ──────────────────────────
    _progress("Extracting per-segment source audio", 35)
    segments = synthesize.extract_segment_audio(segments, stems["vocals"], job_id=job_id)

    # ── Stage 4b: Script alignment (optional) ──────────────────────────
    if script_text:
        _progress("Aligning script to segments", 38)
        from backend.pipeline import script_align
        script_lines = script_align.parse_script(script_text)
        if script_lines:
            segments = script_align.align_script_to_segments(segments, script_lines)

    # ── Stage 4c: Emotion analysis ──────────────────────────────────────
    if config.ENABLE_EMOTION:
        _progress("Analysing emotions per segment (Gemini)", 42)
        from backend.pipeline import emotion
        segments = emotion.analyze_emotions(segments)

    # ── Stage 5: Translate (emotion-aware) ──────────────────────────────
    _progress(f"Translating to {target_language.title()} (Gemini)", 45)
    segments = translate.translate_segments(segments, target_language=target_language)

    # ── Stage 6a: Build voice profiles & clone voices ─────────────────────
    _progress("Building voice profiles & cloning voices", 55)
    voice_profiles = synthesize.build_voice_profiles(segments, stems["vocals"], job_id=job_id)

    # ── Stage 5c: Synthesise translated speech ────────────────────────────
    _progress("Synthesising dubbed speech (ElevenLabs TTS)", 60)
    segments = synthesize.synthesize_segments(segments, voice_profiles, target_language, job_id=job_id)

    # ── Stage 6: Prosody transfer ─────────────────────────────────────────
    if not skip_prosody:
        _progress("Applying prosody transfer (pitch + rate matching)", 75)
        segments = prosody.apply_prosody_transfer(segments, job_id=job_id)

    # ── Stage 7: Acoustic matching ────────────────────────────────────────
    if not skip_acoustic:
        _progress("Applying acoustic character matching", 82)
        segments = acoustic.apply_acoustic_matching(segments, stems["vocals"], job_id=job_id)

    # ── Stage 8: Assemble final output ────────────────────────────────────
    _progress("Assembling final dubbed audio", 90)
    output_path = assemble.assemble_output(
        segments=segments,
        no_vocals_path=stems["no_vocals"],
        total_duration=total_duration,
        job_id=job_id,
        output_filename=output_filename,
    )

    # ── Cleanup voice profiles from ElevenLabs ────────────────────────────
    synthesize.cleanup_cloned_voices(voice_profiles)

    elapsed = time.time() - start_time
    _progress("Done!", 100)
    logger.info("Pipeline complete in %.1f s. Output: %s", elapsed, output_path)

    source_lang = segments[0].get("source_lang", "unknown") if segments else "unknown"

    return {
        "output_path": output_path,
        "segments": segments,
        "duration": total_duration,
        "elapsed": elapsed,
        "source_lang": source_lang,
    }


def run_voice_artist_pipeline(
    actor_video: str | list[str],
    dialogue_audio: str,
    job_id: str,
    output_filename: str | None = None,
    progress_callback=None,
) -> dict:
    """Voice Artist mode: clone actor's voice and apply it to user's dialogue.

    Pipeline:
      1. Extract audio from actor's video(s)
      2. Demucs separation → clean vocals (per file)
      3. Collect reference chunks from all files and clone actor's voice
      4. ElevenLabs Speech-to-Speech: user dialogue → actor's voice
      5. Output the converted audio

    Args:
        actor_video: Path (or list of paths) to the actor's video/audio files.
        dialogue_audio: Path to the voice artist's recorded dialogue.
        job_id: Unique job identifier.
        output_filename: Custom output filename.
        progress_callback: Optional callable(stage: str, pct: float).

    Returns:
        {"output_path": Path, "duration": float, "elapsed": float}
    """
    from backend import config
    from backend.pipeline import ingest, separation, synthesize
    from backend.utils.audio import load_audio, save_audio, get_duration, stereo_to_mono

    def _progress(stage: str, pct: float):
        logger.info("[%3d%%] %s", int(pct), stage)
        if progress_callback:
            progress_callback(stage, pct)

    start_time = time.time()

    # Normalize to list
    if isinstance(actor_video, str):
        actor_video = [actor_video]

    num_files = len(actor_video)

    # ── Stage 1 & 2: Extract audio + Demucs for each actor file ─────────
    all_vocals_paths = []
    separation_pct_start = 5
    separation_pct_end = 45
    pct_per_file = (separation_pct_end - separation_pct_start) / num_files

    for idx, av_path in enumerate(actor_video):
        file_label = Path(av_path).name
        base_pct = separation_pct_start + idx * pct_per_file
        file_job_id = f"{job_id}_actor{idx}" if num_files > 1 else job_id

        _progress(f"Extracting audio from actor file {idx + 1}/{num_files}: {file_label}", base_pct)
        audio_paths = ingest.extract_audio(av_path, job_id=file_job_id)
        logger.info("Actor file %d duration: %.1f s", idx + 1, audio_paths["duration"])

        _progress(f"Separating vocals {idx + 1}/{num_files}: {file_label} (CPU — may take a while)", base_pct + pct_per_file * 0.3)
        stems = separation.separate_stems(audio_paths["full_44k"], job_id=file_job_id)
        all_vocals_paths.append(stems["vocals"])

    # Keep the last stems for the result (vocals_path in output)
    last_vocals_path = all_vocals_paths[-1]

    # ── Stage 3: Extract reference chunks from ALL vocal files ──────────
    _progress("Extracting actor's voice reference from all files", 48)

    from backend.utils.audio import trim_silence, normalize_peak, reduce_noise_spectral, strip_internal_silence, match_spectral_envelope

    ref_dir = config.VOICE_PROFILES_DIR / job_id
    ref_dir.mkdir(parents=True, exist_ok=True)

    chunk_samples_at_sr = None
    ref_paths = []
    max_total_samples = None
    chunk_idx = 0
    used_samples = 0

    for voc_path in all_vocals_paths:
        if len(ref_paths) >= config.MAX_REF_CHUNKS:
            break

        vocals_audio, sr = load_audio(voc_path)
        vocals_mono = stereo_to_mono(vocals_audio)

        if chunk_samples_at_sr is None:
            chunk_samples_at_sr = int(config.REF_CHUNK_DURATION * sr)
            max_total_samples = int(config.MAX_REF_DURATION * sr)

        vocals_clean = reduce_noise_spectral(vocals_mono, sr)
        vocals_trimmed = trim_silence(vocals_clean, sr, top_db=25)
        vocals_dense = strip_internal_silence(vocals_trimmed, sr, top_db=25)
        vocals_normed = normalize_peak(vocals_dense, target_db=-3.0)

        remaining = max_total_samples - used_samples
        if remaining <= 0:
            break
        vocals_capped = vocals_normed[:remaining]

        for i in range(0, len(vocals_capped), chunk_samples_at_sr):
            if len(ref_paths) >= config.MAX_REF_CHUNKS:
                break
            chunk = vocals_capped[i:i + chunk_samples_at_sr]
            if len(chunk) < int(1.0 * sr):
                continue
            rp = ref_dir / f"actor_ref_{chunk_idx:02d}.wav"
            save_audio(chunk, rp, sr)
            ref_paths.append(rp)
            used_samples += len(chunk)
            chunk_idx += 1

    if not ref_paths:
        # Fallback: save whatever we have from the first file
        vocals_audio, sr = load_audio(all_vocals_paths[0])
        vocals_mono = stereo_to_mono(vocals_audio)
        vocals_normed = normalize_peak(vocals_mono, target_db=-3.0)
        chunk_samples_at_sr = int(config.REF_CHUNK_DURATION * sr)
        rp = ref_dir / "actor_ref_00.wav"
        save_audio(vocals_normed[:chunk_samples_at_sr], rp, sr)
        ref_paths = [rp]
        used_samples = min(len(vocals_normed), chunk_samples_at_sr)

    total_ref_dur = used_samples / sr
    logger.info(
        "Actor reference audio: %.1f s across %d chunks (from %d input files)",
        total_ref_dur, len(ref_paths), num_files,
    )

    _progress("Cloning actor's voice via ElevenLabs", 60)
    voice_id = synthesize.clone_voice_from_audio(ref_paths, speaker_id="ACTOR")
    if not voice_id:
        raise RuntimeError(
            "Voice cloning failed. Check your ELEVENLABS_API_KEY and subscription plan."
        )
    logger.info("Cloned actor voice → %s", voice_id)

    # ── Stage 4: Extract & clean dialogue audio ────────────────────────
    _progress("Preparing your dialogue audio", 65)
    dialogue_ext = Path(dialogue_audio).suffix.lower()
    if dialogue_ext in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
        dialogue_paths = ingest.extract_audio(dialogue_audio, job_id=f"{job_id}_dialogue")
        dialogue_wav = str(dialogue_paths["full_44k"])
    else:
        dialogue_wav = dialogue_audio

    # Clean dialogue: noise reduce + normalize for best STS input
    _progress("Cleaning dialogue audio for better conversion", 68)
    dlg_audio, dlg_sr = load_audio(dialogue_wav)
    dlg_mono = stereo_to_mono(dlg_audio)
    dlg_clean = reduce_noise_spectral(dlg_mono, dlg_sr)
    dlg_clean = normalize_peak(dlg_clean, target_db=-3.0)
    clean_dlg_path = config.TEMP_DIR / job_id / "dialogue_clean.wav"
    save_audio(dlg_clean, clean_dlg_path, dlg_sr)
    dialogue_wav = str(clean_dlg_path)

    # ── Stage 5: Speech-to-Speech conversion ────────────────────────────
    _progress("Converting your dialogue to actor's voice (Speech-to-Speech)", 70)

    out_dir = config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    output_name = output_filename or f"voice_artist_{job_id}.wav"
    output_path = out_dir / output_name

    synthesize.speech_to_speech(
        voice_id=voice_id,
        input_audio_path=dialogue_wav,
        output_path=output_path,
    )

    # ── Stage 6: EQ match output to actor's voice ────────────────────
    _progress("Matching output spectral profile to actor's voice", 88)
    out_audio, out_sr = load_audio(str(output_path))
    out_mono = stereo_to_mono(out_audio)

    # Load the first actor reference as the spectral target
    ref_audio, ref_sr = load_audio(str(ref_paths[0]))
    ref_mono = stereo_to_mono(ref_audio)

    matched = match_spectral_envelope(out_mono, ref_mono, out_sr, strength=0.5)
    matched = normalize_peak(matched, target_db=-3.0)
    save_audio(matched, output_path, out_sr)
    logger.info("Spectral envelope matched to actor's voice reference.")

    # ── Cleanup cloned voice ────────────────────────────────────────────
    _progress("Cleaning up cloned voice", 95)
    synthesize.cleanup_cloned_voices({"ACTOR": {"voice_id": voice_id}})

    dialogue_duration = get_duration(str(output_path))
    elapsed = time.time() - start_time
    _progress("Done!", 100)
    logger.info("Voice artist pipeline complete in %.1f s. Output: %s", elapsed, output_path)

    return {
        "output_path": output_path,
        "vocals_path": last_vocals_path,
        "duration": dialogue_duration,
        "elapsed": elapsed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Character Voice Artist Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def analyze_characters(
    source_video: str,
    job_id: str,
    skip_separation: bool = False,
    progress_callback=None,
    script_text: str | None = None,
) -> dict:
    """Phase A of multi-character pipeline: analyse source to detect characters.

    Returns:
        {
            "characters": [{"speaker_id", "segment_count", "total_duration",
                            "preview_path", "segment_ids"}],
            "segments": list[Segment],
            "stems": {"vocals": Path, "no_vocals": Path},
            "total_duration": float,
        }
    """
    from backend.pipeline import ingest, separation, transcribe, synthesize
    from backend.utils.timing import merge_short_segments

    def _progress(stage: str, pct: float):
        logger.info("[%3d%%] %s", int(pct), stage)
        if progress_callback:
            progress_callback(stage, pct)

    # Ingest
    _progress("Extracting audio from video", 5)
    audio_paths = ingest.extract_audio(source_video, job_id=job_id)

    # Separation
    if skip_separation:
        stems = separation.skip_separation(audio_paths["full_44k"], job_id=job_id)
    else:
        _progress("Separating stems with Demucs", 10)
        stems = separation.separate_stems(audio_paths["full_44k"], job_id=job_id)

    # Transcribe + Diarize
    vocals_16k = transcribe.convert_vocals_to_16k(stems["vocals"], job_id=job_id)
    _progress("Transcribing + diarizing speakers", 40)
    segments = transcribe.transcribe_and_diarize(
        audio_16k_path=audio_paths["full_16k"],
        vocals_16k_path=vocals_16k,
    )
    segments = merge_short_segments(segments, min_duration=0.5, gap_threshold=0.3)

    # Extract per-segment audio
    _progress("Extracting per-segment audio", 55)
    segments = synthesize.extract_segment_audio(segments, stems["vocals"], job_id=job_id)

    # Script alignment (optional)
    if script_text:
        _progress("Aligning script to segments", 60)
        from backend.pipeline import script_align
        script_lines = script_align.parse_script(script_text)
        if script_lines:
            segments = script_align.align_script_to_segments(segments, script_lines)

    # Emotion analysis
    if config.ENABLE_EMOTION:
        _progress("Analysing emotions", 65)
        from backend.pipeline import emotion
        segments = emotion.analyze_emotions(segments)

    # Detect characters
    _progress("Detecting characters", 80)
    characters = synthesize.detect_characters(segments, stems["vocals"], job_id=job_id)

    _progress("Analysis complete", 100)
    return {
        "characters": characters,
        "segments": segments,
        "stems": {"vocals": str(stems["vocals"]), "no_vocals": str(stems["no_vocals"])},
        "total_duration": audio_paths["duration"],
    }


def synthesize_characters(
    job_id: str,
    character_dialogues: dict[str, str],
    analysis_result: dict,
    output_filename: str | None = None,
    progress_callback=None,
) -> dict:
    """Phase B of multi-character pipeline: clone each character's voice and
    convert user's per-character dialogue recordings.

    Args:
        job_id: Same job_id as the analysis phase.
        character_dialogues: {speaker_id: path_to_user_dialogue_audio}
        analysis_result: Output from analyze_characters().
        output_filename: Custom output filename.
        progress_callback: Optional callable(stage: str, pct: float).

    Returns:
        {"output_path": Path, "per_character": {speaker_id: output_path}, ...}
    """
    from backend.pipeline import synthesize, assemble
    from backend.utils.audio import load_audio, save_audio, stereo_to_mono, get_duration
    from backend.utils.audio import reduce_noise_spectral, normalize_peak, match_spectral_envelope

    def _progress(stage: str, pct: float):
        logger.info("[%3d%%] %s", int(pct), stage)
        if progress_callback:
            progress_callback(stage, pct)

    start_time = time.time()
    segments = analysis_result["segments"]
    characters = analysis_result["characters"]
    total_duration = analysis_result["total_duration"]

    # Build a speaker→character map for easy lookup
    char_map = {c["speaker_id"]: c for c in characters}

    per_character_outputs = {}
    num_chars = len(character_dialogues)
    pct_per_char = 70 / max(num_chars, 1)

    for i, (speaker_id, dialogue_path) in enumerate(character_dialogues.items()):
        base_pct = 5 + i * pct_per_char
        char_info = char_map.get(speaker_id, {})
        label = speaker_id

        # 1) Clone this character's voice from source segments
        _progress(f"Cloning voice for {label}", base_pct)
        char_segs = [s for s in segments if s.get("speaker_id") == speaker_id]
        ref_paths = [s["source_audio_path"] for s in char_segs if s.get("source_audio_path")]
        # Use up to 5 longest segments as reference
        ref_paths.sort(key=lambda p: Path(p).stat().st_size, reverse=True)
        ref_paths = ref_paths[:config.MAX_REF_CHUNKS]

        voice_id = synthesize.clone_voice_from_audio(ref_paths, speaker_id=speaker_id)
        if not voice_id:
            logger.warning("Cloning failed for %s — skipping.", speaker_id)
            continue

        # 2) Determine dominant emotion for this character's segments
        emotions = [s.get("emotion", "neutral") for s in char_segs]
        dominant_emotion = max(set(emotions), key=emotions.count) if emotions else "neutral"
        avg_intensity = sum(s.get("emotion_intensity", 0.5) for s in char_segs) / max(len(char_segs), 1)

        # 3) Clean user dialogue
        _progress(f"Processing dialogue for {label}", base_pct + pct_per_char * 0.3)
        dlg_audio, dlg_sr = load_audio(dialogue_path)
        dlg_mono = stereo_to_mono(dlg_audio)
        dlg_clean = reduce_noise_spectral(dlg_mono, dlg_sr)
        dlg_clean = normalize_peak(dlg_clean, target_db=-3.0)
        clean_path = config.TEMP_DIR / job_id / f"dlg_clean_{speaker_id}.wav"
        save_audio(dlg_clean, clean_path, dlg_sr)

        # 4) STS: user voice → cloned voice with emotion
        _progress(f"Converting voice for {label} (emotion: {dominant_emotion})", base_pct + pct_per_char * 0.5)
        char_out = config.OUTPUT_DIR / f"char_{speaker_id}_{job_id}.wav"
        synthesize.speech_to_speech(
            voice_id=voice_id,
            input_audio_path=str(clean_path),
            output_path=char_out,
            emotion=dominant_emotion,
            emotion_intensity=avg_intensity,
        )

        # 5) Spectral match to original voice
        if ref_paths:
            ref_audio, ref_sr = load_audio(ref_paths[0])
            ref_mono = stereo_to_mono(ref_audio)
            out_audio, out_sr = load_audio(str(char_out))
            out_mono = stereo_to_mono(out_audio)
            matched = match_spectral_envelope(out_mono, ref_mono, out_sr, strength=0.5)
            matched = normalize_peak(matched, target_db=-3.0)
            save_audio(matched, char_out, out_sr)

        per_character_outputs[speaker_id] = str(char_out)

        # Cleanup cloned voice
        synthesize.cleanup_cloned_voices({speaker_id: {"voice_id": voice_id}})

    _progress("Done!", 100)
    elapsed = time.time() - start_time

    return {
        "per_character": per_character_outputs,
        "elapsed": elapsed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TrillBar — AI-powered multilingual dubbing prototype",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py anime.mp4 --lang hindi
  python main.py kdrama.mkv --lang telugu --skip-separation
  python main.py clip.mp4 --lang tamil --job-id test1 --output my_dub.wav
        """,
    )
    parser.add_argument("input", help="Input video or audio file")
    parser.add_argument(
        "--lang", required=True, choices=["hindi", "tamil", "telugu"],
        help="Target dubbing language"
    )
    parser.add_argument(
        "--job-id", default=None,
        help="Unique job ID for temp file isolation (auto-generated if not set)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output filename (saved to data/output/)"
    )
    parser.add_argument(
        "--skip-separation", action="store_true",
        help="Skip Demucs source separation (fast mode; lower quality)"
    )
    parser.add_argument(
        "--skip-prosody", action="store_true",
        help="Skip prosody transfer"
    )
    parser.add_argument(
        "--skip-acoustic", action="store_true",
        help="Skip acoustic character matching"
    )
    parser.add_argument(
        "--script", default=None,
        help="Path to a screenplay/script file (.txt) for emotion-aware dubbing"
    )
    parser.add_argument(
        "--no-emotion", action="store_true",
        help="Disable emotion analysis"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not Path(args.input).exists():
        logger.error("Input file not found: %s", args.input)
        sys.exit(1)

    # Read script file if provided
    script_text = None
    if args.script:
        script_path = Path(args.script)
        if script_path.exists():
            script_text = script_path.read_text(encoding="utf-8")
            logger.info("Loaded script: %s (%d chars)", args.script, len(script_text))
        else:
            logger.warning("Script file not found: %s — continuing without it.", args.script)

    # Temporarily disable emotion if requested
    if args.no_emotion:
        config.ENABLE_EMOTION = False

    import uuid
    job_id = args.job_id or f"job_{uuid.uuid4().hex[:8]}"
    logger.info("Starting TrillBar pipeline | job_id=%s | lang=%s", job_id, args.lang)

    result = run_pipeline(
        input_file=args.input,
        target_language=args.lang,
        job_id=job_id,
        skip_separation=args.skip_separation,
        skip_prosody=args.skip_prosody,
        skip_acoustic=args.skip_acoustic,
        output_filename=args.output,
        script_text=script_text,
    )

    print(f"\n✓ Dubbed audio saved to: {result['output_path']}")
    print(f"  Duration : {result['duration']:.1f} s")
    print(f"  Elapsed  : {result['elapsed']:.1f} s")
    print(f"  Segments : {len(result['segments'])}")


if __name__ == "__main__":
    main()
