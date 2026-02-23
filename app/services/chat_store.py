import json
import logging
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder


DB_PATH = Path("data/chat/chat.db")
logger = logging.getLogger("truthcast.chat_store")
_active_db_path: Path | None = None


def _default_db_path() -> Path:
    custom_path = os.getenv("TRUTHCAST_CHAT_DB_PATH", "").strip()
    if custom_path:
        return Path(custom_path)
    return DB_PATH


def _fallback_db_path() -> Path:
    return Path(tempfile.gettempdir()) / "truthcast" / "chat.db"


def _get_active_db_path() -> Path:
    global _active_db_path
    if _active_db_path is not None:
        return _active_db_path
    _active_db_path = _default_db_path()
    return _active_db_path


def _set_fallback_db_path() -> Path:
    global _active_db_path
    _active_db_path = _fallback_db_path()
    return _active_db_path


def _is_disk_io_error(exc: sqlite3.OperationalError) -> bool:
    return "disk i/o error" in str(exc).lower()


def _create_tables(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                meta_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                actions_json TEXT,
                references_json TEXT,
                created_at TEXT NOT NULL,
                meta_json TEXT,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created ON chat_messages(session_id, created_at)")
        conn.commit()


def init_db() -> None:
    db_path = _get_active_db_path()
    try:
        _create_tables(db_path)
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("会话库路径不可写，已回退到临时目录: %s", fallback)
        _create_tables(fallback)


def create_session(title: str | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """创建会话并返回会话对象。"""

    init_db()
    session_id = f"chat_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta_json = json.dumps(jsonable_encoder(meta), ensure_ascii=False) if meta else None

    insert_sql = """
        INSERT INTO chat_sessions (session_id, title, created_at, updated_at, meta_json)
        VALUES (?, ?, ?, ?, ?)
        """
    params = (session_id, title, now, now, meta_json)

    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(insert_sql, params)
            conn.commit()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("会话库写入失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.execute(insert_sql, params)
            conn.commit()

    return {
        "session_id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "meta": meta or {},
    }


def touch_session(session_id: str) -> None:
    """更新会话 updated_at，用于排序。"""

    init_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sql = "UPDATE chat_sessions SET updated_at=? WHERE session_id=?"

    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(sql, (now, session_id))
            conn.commit()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.execute(sql, (now, session_id))
            conn.commit()


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    sql = """
        SELECT session_id, title, created_at, updated_at, meta_json
        FROM chat_sessions
        ORDER BY updated_at DESC
        LIMIT ?
        """

    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (limit,)).fetchall()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("会话库读取失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (limit,)).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "meta": json.loads(row["meta_json"]) if row["meta_json"] else {},
            }
        )
    return results


def get_session(session_id: str) -> dict[str, Any] | None:
    init_db()
    sql = """
        SELECT session_id, title, created_at, updated_at, meta_json
        FROM chat_sessions
        WHERE session_id = ?
        """

    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, (session_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, (session_id,)).fetchone()

    if row is None:
        return None
    return {
        "session_id": row["session_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "meta": json.loads(row["meta_json"]) if row["meta_json"] else {},
    }


def append_message(
    session_id: str,
    role: str,
    content: str,
    *,
    actions: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """追加一条消息并返回消息对象。"""

    init_db()
    message_id = f"msg_{uuid.uuid4().hex}"
    now = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    actions_json = json.dumps(jsonable_encoder(actions), ensure_ascii=False) if actions else "[]"
    references_json = json.dumps(jsonable_encoder(references), ensure_ascii=False) if references else "[]"
    meta_json = json.dumps(jsonable_encoder(meta), ensure_ascii=False) if meta else None

    insert_sql = """
        INSERT INTO chat_messages (
            message_id, session_id, role, content, actions_json, references_json, created_at, meta_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
    params = (
        message_id,
        session_id,
        role,
        content,
        actions_json,
        references_json,
        now,
        meta_json,
    )

    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(insert_sql, params)
            conn.commit()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("会话库写入失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.execute(insert_sql, params)
            conn.commit()

    # 更新会话更新时间
    try:
        touch_session(session_id)
    except Exception:
        logger.exception("touch_session failed: %s", session_id)

    return {
        "id": message_id,
        "role": role,
        "content": content,
        "created_at": now,
        "actions": actions or [],
        "references": references or [],
        "meta": meta or {},
    }


def list_messages(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    sql = """
        SELECT message_id, role, content, actions_json, references_json, created_at, meta_json
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        LIMIT ?
        """

    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (session_id, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, (session_id, limit)).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row["message_id"],
                "role": row["role"],
                "content": row["content"],
                "actions": json.loads(row["actions_json"]) if row["actions_json"] else [],
                "references": json.loads(row["references_json"]) if row["references_json"] else [],
                "created_at": row["created_at"],
                "meta": json.loads(row["meta_json"]) if row["meta_json"] else {},
            }
        )
    return results

