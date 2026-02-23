from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.services.history_store import _get_active_db_path, init_db


logger = logging.getLogger("truthcast.pipeline_state_store")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _create_tables(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_tasks (
                task_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                input_text TEXT NOT NULL,
                phases_json TEXT NOT NULL,
                meta_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_phase_snapshots (
                task_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                duration_ms INTEGER,
                error_message TEXT,
                payload_json TEXT,
                PRIMARY KEY (task_id, phase)
            )
            """
        )
        conn.commit()


def init_pipeline_state_db() -> None:
    # 复用 history_store 的 db path 与 disk I/O 回退策略
    init_db()
    db_path = _get_active_db_path()
    _create_tables(db_path)


def upsert_phase_snapshot(
    *,
    task_id: str,
    input_text: str,
    phases: dict[str, Any],
    phase: str,
    status: str,
    duration_ms: int | None = None,
    error_message: str | None = None,
    payload: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    """幂等写入：同一 task_id + phase 以最后一次为准（SQLite UPSERT）。"""

    init_pipeline_state_db()
    db_path = _get_active_db_path()
    now = _now_utc()

    phases_json = json.dumps(jsonable_encoder(phases), ensure_ascii=False)
    meta_json = json.dumps(jsonable_encoder(meta), ensure_ascii=False) if meta else None
    payload_json = json.dumps(jsonable_encoder(payload), ensure_ascii=False) if payload else None

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pipeline_tasks (task_id, created_at, updated_at, input_text, phases_json, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
              updated_at=excluded.updated_at,
              input_text=excluded.input_text,
              phases_json=excluded.phases_json,
              meta_json=COALESCE(excluded.meta_json, pipeline_tasks.meta_json)
            """,
            (task_id, now, now, input_text, phases_json, meta_json),
        )

        conn.execute(
            """
            INSERT INTO pipeline_phase_snapshots (
              task_id, phase, status, updated_at, duration_ms, error_message, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, phase) DO UPDATE SET
              status=excluded.status,
              updated_at=excluded.updated_at,
              duration_ms=excluded.duration_ms,
              error_message=excluded.error_message,
              payload_json=excluded.payload_json
            """,
            (task_id, phase, status, now, duration_ms, error_message, payload_json),
        )
        conn.commit()

    return now


def load_latest_task() -> dict[str, Any] | None:
    init_pipeline_state_db()
    db_path = _get_active_db_path()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id FROM pipeline_tasks ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        task_id = str(row["task_id"])
        return load_task(task_id)


def load_task(task_id: str) -> dict[str, Any] | None:
    """按 task_id 加载任务与各 phase 快照。"""

    init_pipeline_state_db()
    db_path = _get_active_db_path()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, input_text, phases_json, meta_json, updated_at FROM pipeline_tasks WHERE task_id = ? LIMIT 1",
            (task_id,),
        ).fetchone()
        if row is None:
            return None

        snapshots = conn.execute(
            "SELECT phase, status, updated_at, duration_ms, error_message, payload_json FROM pipeline_phase_snapshots WHERE task_id = ?",
            (task_id,),
        ).fetchall()

    def _loads(s: str | None) -> Any:
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            logger.warning("Failed to json.loads payload/meta/phases for task_id=%s", task_id)
            return None

    return {
        "task_id": str(row["task_id"]),
        "input_text": str(row["input_text"]),
        "phases": _loads(row["phases_json"]) or {},
        "meta": _loads(row["meta_json"]) or {},
        "updated_at": str(row["updated_at"]),
        "snapshots": [
            {
                "phase": str(s["phase"]),
                "status": str(s["status"]),
                "updated_at": str(s["updated_at"]),
                "duration_ms": s["duration_ms"],
                "error_message": s["error_message"],
                "payload": _loads(s["payload_json"]) or None,
            }
            for s in snapshots
        ],
    }

