"""SyncLabs AI lip sync integration."""

import logging
import time
import requests

logger = logging.getLogger("trillbar.lipsync")

SYNCLABS_BASE = "https://api.sync.so/v2/lipsync"


def submit_lipsync_job(video_url: str, audio_url: str, api_key: str) -> str:
    """Submit a lip sync job to SyncLabs. Returns the SyncLabs job ID."""
    resp = requests.post(
        SYNCLABS_BASE,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json={
            "model": "sync-1.6.0",
            "input": [
                {"type": "video", "url": video_url},
                {"type": "audio", "url": audio_url},
            ],
            "options": {"output_format": "mp4"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("id")
    if not job_id:
        raise ValueError(f"SyncLabs did not return a job ID: {data}")
    logger.info("SyncLabs job submitted: %s", job_id)
    return job_id


def poll_lipsync_job(synclabs_job_id: str, api_key: str) -> dict:
    """Poll SyncLabs for job status. Returns the full response dict.

    Possible statuses: PROCESSING, COMPLETED, FAILED
    When COMPLETED, result['output']['url'] contains the download URL.
    """
    resp = requests.get(
        f"{SYNCLABS_BASE}/{synclabs_job_id}",
        headers={"x-api-key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def wait_for_lipsync(synclabs_job_id: str, api_key: str, poll_interval: float = 5.0, timeout: float = 600.0) -> str:
    """Block until SyncLabs job completes. Returns the output video URL."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = poll_lipsync_job(synclabs_job_id, api_key)
        status = data.get("status", "").upper()
        if status == "COMPLETED":
            url = (data.get("output") or {}).get("url")
            if not url:
                raise ValueError(f"SyncLabs COMPLETED but no output URL: {data}")
            return url
        if status == "FAILED":
            raise RuntimeError(f"SyncLabs job failed: {data.get('error') or data}")
        time.sleep(poll_interval)
    raise TimeoutError(f"SyncLabs job {synclabs_job_id} timed out after {timeout}s")
