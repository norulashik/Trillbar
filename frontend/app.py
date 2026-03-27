"""TrillBar Streamlit Frontend.

A web UI that runs the full dubbing pipeline end-to-end.
Calls the pipeline modules directly (no HTTP round-trip needed).

Run with:
    streamlit run frontend/app.py

The UI opens at http://localhost:8501
"""

import sys
import uuid
import tempfile
import logging
from pathlib import Path

import streamlit as st
import pandas as pd

# Ensure the project root is on sys.path so 'backend' is importable
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.main import run_pipeline, run_voice_artist_pipeline
from backend.config import SUPPORTED_LANGUAGES, LANGUAGE_CONFIGS

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("trillbar.ui")

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TrillBar - AI Dubbing",
    page_icon=":studio_microphone:",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    .main-title {
        text-align: center;
        color: #6c4dff;
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    .subtitle {
        text-align: center;
        color: #888;
        font-size: 1rem;
        margin-bottom: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

st.markdown('<h1 class="main-title">TrillBar</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">AI-powered multilingual dubbing &mdash; Hindi &middot; Tamil &middot; Telugu</p>',
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Mode selector
# ─────────────────────────────────────────────────────────────────────────────

mode = st.radio(
    "Mode",
    ["Translation Dubbing", "Voice Artist"],
    horizontal=True,
    help="**Translation Dubbing**: Auto-translate and dub video into another language. "
         "**Voice Artist**: Clone actor's voice and apply it to your own dialogue recording.",
)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# MODE 1: Translation Dubbing
# ─────────────────────────────────────────────────────────────────────────────

if mode == "Translation Dubbing":
    col_upload, col_options = st.columns([2, 1])

    with col_upload:
        uploaded_file = st.file_uploader(
            "Upload Video or Audio",
            type=["mp4", "mkv", "avi", "mov", "webm", "mp3", "wav", "flac", "ogg", "m4a", "aac"],
            key="trans_upload",
        )

    with col_options:
        language_display = [LANGUAGE_CONFIGS[k]["display"] for k in SUPPORTED_LANGUAGES]
        target_lang_display = st.selectbox("Target Language", language_display, index=0)
        target_lang_key = next(
            k for k, v in LANGUAGE_CONFIGS.items() if v["display"] == target_lang_display
        )

        st.markdown("**Pipeline Options**")
        skip_separation = st.checkbox(
            "Skip source separation (fast mode)", value=True
        )
        skip_prosody = st.checkbox("Skip prosody transfer", value=False)
        skip_acoustic = st.checkbox("Skip acoustic matching", value=False)

    dub_clicked = st.button("Dub Now", type="primary", use_container_width=True, key="trans_btn")

    if dub_clicked:
        if uploaded_file is None:
            st.warning("Please upload a video or audio file first.")
            st.stop()

        job_id = f"st_{uuid.uuid4().hex[:8]}"
        tmp_dir = Path(tempfile.mkdtemp())
        input_path = tmp_dir / uploaded_file.name
        input_path.write_bytes(uploaded_file.getvalue())

        progress_bar = st.progress(0, text="Starting pipeline...")
        status_container = st.status("Running dubbing pipeline...", expanded=True)

        def progress_cb(stage: str, pct: float):
            pct_int = int(pct)
            progress_bar.progress(min(pct_int, 100) / 100, text=stage)
            status_container.write(f"`[{pct_int:3d}%]` {stage}")

        try:
            result = run_pipeline(
                input_file=str(input_path),
                target_language=target_lang_key,
                job_id=job_id,
                skip_separation=skip_separation,
                skip_prosody=skip_prosody,
                skip_acoustic=skip_acoustic,
                output_filename=f"dubbed_{job_id}.wav",
                progress_callback=progress_cb,
            )
            status_container.update(label="Dubbing complete!", state="complete")
            progress_bar.progress(1.0, text="Done!")
            st.session_state["result"] = result
            st.session_state["result_mode"] = "translation"
            st.session_state["input_path"] = str(input_path)

        except Exception as e:
            status_container.update(label=f"Pipeline error: {e}", state="error")
            logger.exception("Pipeline error")
            st.error(f"Pipeline failed: {e}")
            st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# MODE 2: Voice Artist
# ─────────────────────────────────────────────────────────────────────────────

elif mode == "Voice Artist":
    st.markdown(
        "Upload the **actor's video** (to clone their voice) and "
        "**your dialogue recording** (your voice will be converted to the actor's voice)."
    )

    col_actor, col_dialogue = st.columns(2)

    with col_actor:
        actor_files = st.file_uploader(
            "Actor's Video / Audio (voice to clone)",
            type=["mp4", "mkv", "avi", "mov", "webm", "mp3", "wav", "flac", "ogg", "m4a", "aac"],
            key="va_actor",
            accept_multiple_files=True,
            help="Upload multiple clips of the actor for better voice cloning quality.",
        )

    with col_dialogue:
        dialogue_file = st.file_uploader(
            "Your Dialogue Recording",
            type=["mp4", "mkv", "avi", "mov", "webm", "mp3", "wav", "flac", "ogg", "m4a", "aac"],
            key="va_dialogue",
        )

    if actor_files:
        st.caption(f"{len(actor_files)} file(s) selected for voice cloning.")

    st.info(
        "**How it works:** Demucs will separate the actor's vocals cleanly, "
        "then ElevenLabs clones that voice and applies it to your dialogue via Speech-to-Speech. "
        "Upload **multiple clips** of the actor for higher-fidelity cloning. "
        "Demucs takes ~40-70 min on CPU for a 5-min clip."
    )

    va_clicked = st.button("Convert Voice", type="primary", use_container_width=True, key="va_btn")

    if va_clicked:
        if not actor_files:
            st.warning("Please upload the actor's video/audio.")
            st.stop()
        if dialogue_file is None:
            st.warning("Please upload your dialogue recording.")
            st.stop()

        job_id = f"va_{uuid.uuid4().hex[:8]}"
        tmp_dir = Path(tempfile.mkdtemp())

        actor_paths = []
        for af in actor_files:
            ap = tmp_dir / af.name
            ap.write_bytes(af.getvalue())
            actor_paths.append(str(ap))

        dialogue_path = tmp_dir / dialogue_file.name
        dialogue_path.write_bytes(dialogue_file.getvalue())

        progress_bar = st.progress(0, text="Starting voice artist pipeline...")
        status_container = st.status("Cloning actor's voice and converting...", expanded=True)

        def va_progress_cb(stage: str, pct: float):
            pct_int = int(pct)
            progress_bar.progress(min(pct_int, 100) / 100, text=stage)
            status_container.write(f"`[{pct_int:3d}%]` {stage}")

        try:
            result = run_voice_artist_pipeline(
                actor_video=actor_paths,
                dialogue_audio=str(dialogue_path),
                job_id=job_id,
                output_filename=f"voice_artist_{job_id}.wav",
                progress_callback=va_progress_cb,
            )
            status_container.update(label="Voice conversion complete!", state="complete")
            progress_bar.progress(1.0, text="Done!")
            st.session_state["result"] = result
            st.session_state["result_mode"] = "voice_artist"
            st.session_state["input_path"] = str(dialogue_path)

        except Exception as e:
            status_container.update(label=f"Pipeline error: {e}", state="error")
            logger.exception("Pipeline error")
            st.error(f"Pipeline failed: {e}")
            st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Results display
# ─────────────────────────────────────────────────────────────────────────────

if "result" in st.session_state:
    result = st.session_state["result"]
    result_mode = st.session_state.get("result_mode", "translation")
    input_path_str = st.session_state.get("input_path")

    st.divider()

    if result_mode == "voice_artist":
        st.success(
            f"Done in {result['elapsed']:.0f}s  |  "
            f"{result['duration']:.1f}s output duration"
        )

        col_vocals, col_orig, col_converted = st.columns(3)
        with col_vocals:
            st.subheader("Actor's Clean Voice")
            vocals_path = result.get("vocals_path")
            if vocals_path and Path(str(vocals_path)).exists():
                st.audio(str(vocals_path))
            else:
                st.info("Vocals file not available.")

        with col_orig:
            st.subheader("Your Dialogue")
            if input_path_str and Path(input_path_str).exists():
                st.audio(input_path_str)
            else:
                st.info("Original file no longer available.")

        with col_converted:
            st.subheader("Converted (Actor's Voice)")
            output_path = Path(str(result["output_path"]))
            if output_path.exists():
                st.audio(str(output_path))
            else:
                st.warning("Output file not found.")

    else:
        st.success(
            f"Done in {result['elapsed']:.0f}s  |  "
            f"{len(result.get('segments', []))} segments  |  "
            f"{result['duration']:.1f}s duration"
        )

        col_orig, col_dubbed = st.columns(2)
        with col_orig:
            st.subheader("Original Audio")
            if input_path_str and Path(input_path_str).exists():
                st.audio(input_path_str)
            else:
                st.info("Original file no longer available.")

        with col_dubbed:
            st.subheader("Dubbed Audio")
            output_path = Path(str(result["output_path"]))
            if output_path.exists():
                st.audio(str(output_path))
            else:
                st.warning("Output file not found.")

    # Download button
    output_path = Path(str(result["output_path"]))
    if output_path.exists():
        st.download_button(
            label="Download Output Audio",
            data=output_path.read_bytes(),
            file_name=output_path.name,
            mime="audio/wav",
            use_container_width=True,
        )

    # Transcript table (translation mode only)
    segments = result.get("segments", [])
    if segments and result_mode == "translation":
        st.subheader("Transcript")
        rows = [
            {
                "Speaker": seg.get("speaker_id", "?"),
                "Original": seg.get("source_text", ""),
                "Translated": seg.get("translated_text", ""),
                "Time": f"{seg.get('start', 0):.1f}s - {seg.get('end', 0):.1f}s",
            }
            for seg in segments
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "**TrillBar Prototype** · "
    "Translation: Demucs → Whisper → Gemini → ElevenLabs TTS · "
    "Voice Artist: Demucs → ElevenLabs Clone → Speech-to-Speech  \n"
    "_Supported inputs: MP4, MKV, AVI, MP3, WAV, FLAC_"
)
