# -*- coding: utf-8 -*-
"""TrillBar Streamlit Frontend.

A web UI that talks to the FastAPI backend via HTTP.
Run the backend first:  python run_api.py
Then run:               streamlit run frontend/app.py
"""

import time
import logging
from collections import Counter

import streamlit as st
import pandas as pd
import requests

API_BASE = "http://localhost:8005"
SUPPORTED_LANGUAGES = ["hindi", "tamil", "telugu"]
LANG_DISPLAY = {"hindi": "Hindi", "tamil": "Tamil", "telugu": "Telugu"}
MEDIA_TYPES = ["mp4", "mkv", "avi", "mov", "webm", "mp3", "wav", "flac", "ogg", "m4a", "aac"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("trillbar.ui")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_backend():
    """Verify backend is reachable."""
    try:
        r = requests.get(f"{API_BASE}/health", timeout=10)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout, requests.ReadTimeout):
        return False


def _poll_job(job_id: str, progress_bar, status_container, done_statuses=("done",)):
    """Poll /status/{job_id} every 2s until terminal state. Returns final status dict."""
    last_stage = None
    while True:
        try:
            r = requests.get(f"{API_BASE}/status/{job_id}", timeout=10)
            status = r.json()
        except Exception as e:
            status_container.write(f"Polling error: {e}")
            time.sleep(2)
            continue

        pct = status.get("progress", 0)
        stage = status.get("stage", "")
        progress_bar.progress(min(pct, 100) / 100, text=stage)

        # Only write to status container when stage changes
        if stage != last_stage:
            status_container.write(f"`[{pct:3d}%]` {stage}")
            last_stage = stage

        if status["status"] in done_statuses:
            return status
        if status["status"] == "error":
            return status

        time.sleep(2)


# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TrillBar - AI Dubbing",
    page_icon=":studio_microphone:",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main-title { text-align: center; color: #6c4dff; font-size: 2.5rem; font-weight: 700; margin-bottom: 0; }
    .subtitle { text-align: center; color: #888; font-size: 1rem; margin-bottom: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<h1 class="main-title">TrillBar</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">AI-powered multilingual dubbing &mdash; Hindi &middot; Tamil &middot; Telugu</p>',
    unsafe_allow_html=True,
)

# Backend check
if not _check_backend():
    st.error(
        "Backend not reachable at `{}`.\n\n"
        "Start it with: `python run_api.py`".format(API_BASE)
    )
    st.stop()

# ── Mode Selector ────────────────────────────────────────────────────────────

mode = st.radio(
    "Mode",
    ["Translation Dubbing", "Voice Artist", "Multi-Character Dubbing"],
    horizontal=True,
    help="**Translation Dubbing**: Auto-translate and dub video into another language. "
         "**Voice Artist**: Clone actor's voice and apply it to your own dialogue recording. "
         "**Multi-Character Dubbing**: Separate characters, dub each one individually.",
)

# ── Emotion Explainer ────────────────────────────────────────────────────────

with st.expander("How does emotion-aware dubbing work?"):
    st.markdown("""
1. **Detect** -- Gemini analyses each transcribed segment's text + surrounding context to detect emotion (happy/angry/sad/etc.), intensity (0--1), and an acting direction.
2. **Translate** -- Emotion context is injected into the Gemini translation prompt so the translated text preserves the emotional register.
3. **Synthesise** -- ElevenLabs `style` and `stability` parameters are dynamically set per emotion (angry = more expressive, sad = softer delivery).
4. **Prosody** -- Pitch is shifted based on emotion (angry +2 semitones, sad -1.5) on top of source F0 matching.
5. **Script** -- If a screenplay is uploaded, stage directions like *(whispering)* feed into emotion detection for more accurate results.

The source language is **auto-detected** by Whisper -- you don't need to specify it.
""")

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# MODE 1: Translation Dubbing
# ═══════════════════════════════════════════════════════════════════════════════

if mode == "Translation Dubbing":
    col_upload, col_options = st.columns([2, 1])

    with col_upload:
        uploaded_file = st.file_uploader(
            "Upload Video or Audio", type=MEDIA_TYPES, key="trans_upload",
        )

    with col_options:
        target_lang_display = st.selectbox(
            "Target Language",
            [LANG_DISPLAY[k] for k in SUPPORTED_LANGUAGES],
            index=0,
        )
        target_lang_key = next(k for k, v in LANG_DISPLAY.items() if v == target_lang_display)

        st.markdown("**Pipeline Options**")
        skip_separation = st.checkbox("Skip source separation (fast mode)", value=True)
        skip_prosody = st.checkbox("Skip prosody transfer", value=False)
        skip_acoustic = st.checkbox("Skip acoustic matching", value=False)

    script_file = st.file_uploader(
        "Script / Screenplay (optional)", type=["txt"], key="trans_script",
        help="Upload a script file (CHARACTER: dialogue format) for better emotion detection.",
    )

    dub_clicked = st.button("Dub Now", type="primary", use_container_width=True, key="trans_btn")

    if dub_clicked:
        if uploaded_file is None:
            st.warning("Please upload a video or audio file first.")
            st.stop()

        progress_bar = st.progress(0, text="Submitting job...")
        status_container = st.status("Running dubbing pipeline...", expanded=True)

        # Build form data
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        data = {
            "target_language": target_lang_key,
            "skip_separation": str(skip_separation).lower(),
            "skip_prosody": str(skip_prosody).lower(),
            "skip_acoustic": str(skip_acoustic).lower(),
        }
        if script_file is not None:
            data["script_text"] = script_file.getvalue().decode("utf-8", errors="replace")

        try:
            r = requests.post(f"{API_BASE}/dub", files=files, data=data, timeout=30)
            r.raise_for_status()
            job_id = r.json()["job_id"]
        except Exception as e:
            st.error(f"Failed to submit job: {e}")
            st.stop()

        # Poll until done
        final = _poll_job(job_id, progress_bar, status_container)

        if final["status"] == "error":
            status_container.update(label=f"Pipeline error: {final['error']}", state="error")
            st.error(f"Pipeline failed: {final['error']}")
            st.stop()

        status_container.update(label="Dubbing complete!", state="complete")
        progress_bar.progress(1.0, text="Done!")

        # Show success banner with source language
        src_lang = final.get("source_lang") or "unknown"
        st.success(
            f"Done in {final.get('elapsed', 0):.0f}s  |  "
            f"Detected source: **{src_lang.title()}**  |  "
            f"{final.get('duration', 0):.1f}s duration"
        )

        # Audio playback
        col_orig, col_dubbed = st.columns(2)
        with col_orig:
            st.subheader("Original Audio")
            st.audio(uploaded_file.getvalue(), format=f"audio/{uploaded_file.name.rsplit('.', 1)[-1]}")
        with col_dubbed:
            st.subheader("Dubbed Audio")
            audio_resp = requests.get(f"{API_BASE}/download/{job_id}", timeout=60)
            if audio_resp.status_code == 200:
                st.audio(audio_resp.content, format="audio/wav")
                st.download_button(
                    "Download Dubbed Audio", data=audio_resp.content,
                    file_name=f"dubbed_{job_id}.wav", mime="audio/wav",
                    use_container_width=True,
                )

        # Transcript with emotion
        try:
            tr = requests.get(f"{API_BASE}/transcript/{job_id}", timeout=10)
            segments = tr.json().get("segments", [])
        except Exception:
            segments = []

        if segments:
            # Emotion summary
            emotions = [s.get("emotion", "neutral") for s in segments]
            counts = Counter(emotions)
            if len(counts) > 1 or list(counts.keys()) != ["neutral"]:
                st.subheader("Emotion Summary")
                cols = st.columns(len(counts))
                for i, (emo, cnt) in enumerate(counts.most_common()):
                    cols[i].metric(emo.title(), f"{cnt} segment{'s' if cnt != 1 else ''}")

            st.subheader("Transcript")
            rows = [
                {
                    "Speaker": s.get("speaker_id", "?"),
                    "Emotion": f"{s.get('emotion', '-')} ({s.get('emotion_intensity', 0):.1f})",
                    "Direction": s.get("delivery_direction", ""),
                    "Original": s.get("source_text", ""),
                    "Translated": s.get("translated_text", ""),
                    "Time": f"{s.get('start', 0):.1f}s - {s.get('end', 0):.1f}s",
                }
                for s in segments
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MODE 2: Voice Artist
# ═══════════════════════════════════════════════════════════════════════════════

elif mode == "Voice Artist":
    st.markdown(
        "Upload the **actor's video** (to clone their voice) and "
        "**your dialogue recording** (your voice will be converted to the actor's voice)."
    )

    col_actor, col_dialogue = st.columns(2)
    with col_actor:
        actor_files = st.file_uploader(
            "Actor's Video / Audio (voice to clone)",
            type=MEDIA_TYPES, key="va_actor", accept_multiple_files=True,
            help="Upload multiple clips of the actor for better voice cloning quality.",
        )
    with col_dialogue:
        dialogue_file = st.file_uploader(
            "Your Dialogue Recording", type=MEDIA_TYPES, key="va_dialogue",
        )

    if actor_files:
        st.caption(f"{len(actor_files)} file(s) selected for voice cloning.")

    st.info(
        "**How it works:** Demucs separates the actor's vocals cleanly, "
        "then ElevenLabs clones that voice and applies it to your dialogue via Speech-to-Speech."
    )

    va_clicked = st.button("Convert Voice", type="primary", use_container_width=True, key="va_btn")

    if va_clicked:
        if not actor_files:
            st.warning("Please upload the actor's video/audio.")
            st.stop()
        if dialogue_file is None:
            st.warning("Please upload your dialogue recording.")
            st.stop()

        progress_bar = st.progress(0, text="Submitting voice artist job...")
        status_container = st.status("Cloning actor's voice and converting...", expanded=True)

        files = [("actor_files", (af.name, af.getvalue())) for af in actor_files]
        files.append(("dialogue", (dialogue_file.name, dialogue_file.getvalue())))

        try:
            r = requests.post(f"{API_BASE}/voice-artist", files=files, timeout=30)
            r.raise_for_status()
            job_id = r.json()["job_id"]
        except Exception as e:
            st.error(f"Failed to submit job: {e}")
            st.stop()

        final = _poll_job(job_id, progress_bar, status_container)

        if final["status"] == "error":
            status_container.update(label=f"Pipeline error: {final['error']}", state="error")
            st.error(f"Pipeline failed: {final['error']}")
            st.stop()

        status_container.update(label="Voice conversion complete!", state="complete")
        progress_bar.progress(1.0, text="Done!")

        st.success(
            f"Done in {final.get('elapsed', 0):.0f}s  |  "
            f"{final.get('duration', 0):.1f}s output duration"
        )

        col_orig, col_converted = st.columns(2)
        with col_orig:
            st.subheader("Your Dialogue")
            st.audio(dialogue_file.getvalue(), format=f"audio/{dialogue_file.name.rsplit('.', 1)[-1]}")
        with col_converted:
            st.subheader("Converted (Actor's Voice)")
            audio_resp = requests.get(f"{API_BASE}/download/{job_id}", timeout=60)
            if audio_resp.status_code == 200:
                st.audio(audio_resp.content, format="audio/wav")
                st.download_button(
                    "Download Converted Audio", data=audio_resp.content,
                    file_name=f"voice_artist_{job_id}.wav", mime="audio/wav",
                    use_container_width=True,
                )


# ═══════════════════════════════════════════════════════════════════════════════
# MODE 3: Multi-Character Dubbing
# ═══════════════════════════════════════════════════════════════════════════════

elif mode == "Multi-Character Dubbing":
    st.markdown(
        "Upload a **source video** with multiple characters. The system will detect each speaker, "
        "then you can upload your **Tamil/Hindi/Telugu dialogue** for each character separately."
    )

    source_file = st.file_uploader("Source Video / Audio", type=MEDIA_TYPES, key="mc_source")
    skip_sep = st.checkbox("Skip source separation (fast mode)", value=True, key="mc_skip_sep")
    script_file_mc = st.file_uploader(
        "Script / Screenplay (optional)", type=["txt"], key="mc_script",
        help="Upload a script for better emotion detection and character labelling.",
    )

    # ── Phase A: Analyse ─────────────────────────────────────────────────────
    if st.button("Analyse Characters", type="primary", key="mc_analyse"):
        if source_file is None:
            st.warning("Please upload a source file first.")
            st.stop()

        progress_bar = st.progress(0, text="Submitting analysis...")
        status_container = st.status("Detecting characters...", expanded=True)

        files = {"file": (source_file.name, source_file.getvalue())}
        data = {"skip_separation": str(skip_sep).lower()}
        if script_file_mc is not None:
            data["script_text"] = script_file_mc.getvalue().decode("utf-8", errors="replace")

        try:
            r = requests.post(f"{API_BASE}/analyze-characters", files=files, data=data, timeout=30)
            r.raise_for_status()
            job_id = r.json()["job_id"]
        except Exception as e:
            st.error(f"Failed to submit analysis: {e}")
            st.stop()

        final = _poll_job(job_id, progress_bar, status_container, done_statuses=("analyzed",))

        if final["status"] == "error":
            status_container.update(label=f"Analysis error: {final['error']}", state="error")
            st.error(f"Analysis failed: {final['error']}")
            st.stop()

        status_container.update(label="Character analysis complete!", state="complete")
        progress_bar.progress(1.0, text="Done!")

        # Fetch characters
        try:
            cr = requests.get(f"{API_BASE}/characters/{job_id}", timeout=10)
            characters = cr.json().get("characters", [])
        except Exception:
            characters = []

        st.session_state["mc_characters"] = characters
        st.session_state["mc_job_id"] = job_id

    # ── Show detected characters ─────────────────────────────────────────────
    if "mc_characters" in st.session_state:
        characters = st.session_state["mc_characters"]
        job_id = st.session_state["mc_job_id"]

        st.subheader(f"Detected {len(characters)} Character(s)")

        dialogue_files = {}
        for char in characters:
            sid = char["speaker_id"]
            col_info, col_preview, col_upload = st.columns([1, 1, 2])
            with col_info:
                st.markdown(f"**{sid}**")
                st.caption(f"{char['segment_count']} segments, {char['total_duration']:.1f}s")
                dominant = char.get("dominant_emotion")
                if dominant:
                    st.caption(f"Emotion: {dominant}")
            with col_preview:
                try:
                    preview_resp = requests.get(
                        f"{API_BASE}/character-preview/{job_id}/{sid}", timeout=10
                    )
                    if preview_resp.status_code == 200:
                        st.audio(preview_resp.content, format="audio/wav")
                except Exception:
                    st.caption("Preview unavailable")
            with col_upload:
                dlg = st.file_uploader(
                    f"Your dialogue for {sid}",
                    type=["wav", "mp3", "flac", "ogg", "m4a"],
                    key=f"mc_dlg_{sid}",
                )
                if dlg is not None:
                    dialogue_files[sid] = dlg

        # ── Phase B: Synthesise ──────────────────────────────────────────────
        if st.button("Convert All Characters", type="primary", key="mc_synth"):
            if not dialogue_files:
                st.warning("Please upload dialogue for at least one character.")
                st.stop()

            progress_bar = st.progress(0, text="Submitting synthesis...")
            status_container = st.status("Processing characters...", expanded=True)

            files = [
                ("dialogues", (f"{sid}{__import__('pathlib').Path(dlg.name).suffix}", dlg.getvalue()))
                for sid, dlg in dialogue_files.items()
            ]

            try:
                r = requests.post(
                    f"{API_BASE}/synthesize-characters/{job_id}",
                    files=files, timeout=30,
                )
                r.raise_for_status()
            except Exception as e:
                st.error(f"Failed to submit synthesis: {e}")
                st.stop()

            final = _poll_job(job_id, progress_bar, status_container)

            if final["status"] == "error":
                status_container.update(label=f"Synthesis error: {final['error']}", state="error")
                st.error(f"Synthesis failed: {final['error']}")
                st.stop()

            status_container.update(label="Voice conversion complete!", state="complete")
            progress_bar.progress(1.0, text="Done!")

            st.subheader("Results")
            for sid in dialogue_files:
                try:
                    audio_resp = requests.get(
                        f"{API_BASE}/download-character/{job_id}/{sid}", timeout=60
                    )
                    if audio_resp.status_code == 200:
                        st.markdown(f"**{sid}** -- Converted Audio")
                        st.audio(audio_resp.content, format="audio/wav")
                        st.download_button(
                            f"Download {sid}", data=audio_resp.content,
                            file_name=f"char_{sid}_{job_id}.wav", mime="audio/wav",
                            key=f"dl_{sid}",
                        )
                except Exception:
                    st.warning(f"Could not download output for {sid}")

            st.success(f"Done in {final.get('elapsed', 0):.0f}s")


# ═══════════════════════════════════════════════════════════════════════════════
# Footer
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.caption(
    "**TrillBar Prototype v0.3** -- "
    "Backend: `python run_api.py` (port 8005) -- "
    "Frontend: `streamlit run frontend/app.py` (port 8501)  \n"
    "_Supported inputs: MP4, MKV, AVI, MP3, WAV, FLAC_"
)
