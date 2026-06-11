"""SQLite-backed job persistence layer.

Replaces the in-memory jobs dict in api.py so that job state survives
server restarts and is safe to read from the async SSE polling loop.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend import config

logger = logging.getLogger(__name__)

DB_PATH = config.DATA_DIR / "jobs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    job_type    TEXT NOT NULL DEFAULT 'dub',
    status      TEXT NOT NULL DEFAULT 'queued',
    stage       TEXT NOT NULL DEFAULT 'Queued',
    progress    INTEGER NOT NULL DEFAULT 0,
    params      TEXT,
    result      TEXT,
    error       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_library (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    elevenlabs_id  TEXT NOT NULL,
    ref_audio_path TEXT,
    created_at     REAL NOT NULL
);
"""

_lock = __import__("threading").Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


_init_db()


def create_job(job_id: str, job_type: str, params: dict) -> dict:
    now = time.time()
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, job_type, status, stage, progress, params, created_at, updated_at) "
            "VALUES (?, ?, 'queued', 'Queued', 0, ?, ?, ?)",
            (job_id, job_type, json.dumps(_make_json_safe(params)), now, now),
        )
    return get_job(job_id)


def update_job(job_id: str, result: dict | None = None, **fields) -> None:
    """Update scalar fields and/or merge into the result JSON blob."""
    now = time.time()
    with _lock, _conn() as conn:
        if fields:
            set_clauses = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE jobs SET {set_clauses}, updated_at = ? WHERE id = ?",
                [*fields.values(), now, job_id],
            )

        if result is not None:
            row = conn.execute("SELECT result FROM jobs WHERE id = ?", (job_id,)).fetchone()
            existing = json.loads(row["result"]) if row and row["result"] else {}
            existing.update(_make_json_safe(result))
            conn.execute(
                "UPDATE jobs SET result = ?, updated_at = ? WHERE id = ?",
                (json.dumps(existing), now, job_id),
            )


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["params"] = json.loads(job["params"]) if job["params"] else {}
    job["result"] = json.loads(job["result"]) if job["result"] else {}
    return job


# ── Voice Library ─────────────────────────────────────────────────────────────

def create_voice_entry(voice_id: str, name: str, elevenlabs_id: str, ref_audio_path: str | None = None) -> dict:
    now = time.time()
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO voice_library (id, name, elevenlabs_id, ref_audio_path, created_at) VALUES (?,?,?,?,?)",
            (voice_id, name, elevenlabs_id, ref_audio_path, now),
        )
    return get_voice(voice_id)


def list_voices() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM voice_library ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_voice(voice_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM voice_library WHERE id = ?", (voice_id,)).fetchone()
    return dict(row) if row else None


def delete_voice(voice_id: str) -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM voice_library WHERE id = ?", (voice_id,))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_json_safe(obj: Any) -> Any:
    """Recursively convert Path objects and other non-JSON types to strings."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_json_safe(item) for item in obj]
    return obj
