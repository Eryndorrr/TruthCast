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


DB_PATH = Path("data/history/history.db")
logger = logging.getLogger("truthcast.history_store")
_active_db_path: Path | None = None


def _default_db_path() -> Path:
    custom_path = os.getenv("TRUTHCAST_HISTORY_DB_PATH", "").strip()
    if custom_path:
        return Path(custom_path)
    return DB_PATH


def _fallback_db_path() -> Path:
    return Path(tempfile.gettempdir()) / "truthcast" / "history.db"


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
            CREATE TABLE IF NOT EXISTS analysis_history (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                input_text TEXT NOT NULL,
                risk_label TEXT NOT NULL,
                risk_score INTEGER NOT NULL,
                detected_scenario TEXT NOT NULL,
                evidence_domains TEXT NOT NULL,
                report_json TEXT NOT NULL,
                detect_json TEXT,
                simulation_json TEXT,
                content_json TEXT,
                feedback_status TEXT,
                feedback_note TEXT
            )
            """
        )
        try:
            conn.execute("ALTER TABLE analysis_history ADD COLUMN detect_json TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE analysis_history ADD COLUMN simulation_json TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE analysis_history ADD COLUMN content_json TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def init_db() -> None:
    db_path = _get_active_db_path()
    try:
        _create_tables(db_path)
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("历史库路径不可写，已回退到临时目录: %s", fallback)
        _create_tables(fallback)


def save_report(
    input_text: str,
    report: dict[str, Any],
    detect_data: dict[str, Any] | None = None,
    simulation: dict[str, Any] | None = None,
) -> str:
    init_db()
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    normalized_report = jsonable_encoder(report)
    evidence_domains = json.dumps(
        normalized_report.get("evidence_domains", []), ensure_ascii=False
    )
    report_json = json.dumps(normalized_report, ensure_ascii=False)
    detect_json = json.dumps(jsonable_encoder(detect_data), ensure_ascii=False) if detect_data else None
    simulation_json = json.dumps(jsonable_encoder(simulation), ensure_ascii=False) if simulation else None

    insert_sql = """
        INSERT INTO analysis_history (
            id, created_at, input_text, risk_label, risk_score,
            detected_scenario, evidence_domains, report_json, detect_json, simulation_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    params = (
        record_id,
        now,
        input_text,
        normalized_report.get("risk_label", "unknown"),
        int(normalized_report.get("risk_score", 0)),
        normalized_report.get("detected_scenario", "general"),
        evidence_domains,
        report_json,
        detect_json,
        simulation_json,
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
        logger.warning("历史库写入失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.execute(insert_sql, params)
            conn.commit()

    return record_id


def list_history(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    db_path = _get_active_db_path()
    select_sql = """
        SELECT id, created_at, input_text, risk_label, risk_score,
               detected_scenario, evidence_domains, feedback_status
        FROM analysis_history
        ORDER BY created_at DESC
        LIMIT ?
        """

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(select_sql, (limit,)).fetchall()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("历史库读取失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(select_sql, (limit,)).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "input_preview": row["input_text"][:120],
                "risk_label": row["risk_label"],
                "risk_score": row["risk_score"],
                "detected_scenario": row["detected_scenario"],
                "evidence_domains": json.loads(row["evidence_domains"]),
                "feedback_status": row["feedback_status"],
            }
        )
    return results


def get_history(record_id: str) -> dict[str, Any] | None:
    init_db()
    db_path = _get_active_db_path()
    select_sql = """
        SELECT id, created_at, input_text, risk_label, risk_score,
               detected_scenario, evidence_domains, report_json,
               detect_json, simulation_json, content_json,
               feedback_status, feedback_note
        FROM analysis_history
        WHERE id = ?
        """

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(select_sql, (record_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("历史库读取失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(select_sql, (record_id,)).fetchone()

    if row is None:
        return None
    
    detect_data = None
    if row["detect_json"]:
        try:
            detect_data = json.loads(row["detect_json"])
        except json.JSONDecodeError:
            pass
    
    simulation = None
    if row["simulation_json"]:
        try:
            simulation = json.loads(row["simulation_json"])
        except json.JSONDecodeError:
            pass

    content = None
    if row["content_json"]:
        try:
            content = json.loads(row["content_json"])
        except json.JSONDecodeError:
            pass
    
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "input_text": row["input_text"],
        "risk_label": row["risk_label"],
        "risk_score": row["risk_score"],
        "detected_scenario": row["detected_scenario"],
        "evidence_domains": json.loads(row["evidence_domains"]),
        "report": json.loads(row["report_json"]),
        "detect_data": detect_data,
        "simulation": simulation,
        "content": content,
        "feedback_status": row["feedback_status"],
        "feedback_note": row["feedback_note"],
    }


def update_content(record_id: str, content: dict[str, Any]) -> bool:
    """更新历史记录的 content 数据（应对内容生成结果，可为部分字段）"""
    init_db()
    db_path = _get_active_db_path()
    content_json = json.dumps(jsonable_encoder(content), ensure_ascii=False)
    update_sql = """
        UPDATE analysis_history
        SET content_json = ?
        WHERE id = ?
        """
    params = (content_json, record_id)

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(update_sql, params)
            conn.commit()
            return cur.rowcount > 0
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("历史库写入失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            cur = conn.execute(update_sql, params)
            conn.commit()
            return cur.rowcount > 0


def save_feedback(record_id: str, status: str, note: str | None) -> bool:
    init_db()
    db_path = _get_active_db_path()
    update_sql = """
        UPDATE analysis_history
        SET feedback_status = ?, feedback_note = ?
        WHERE id = ?
        """
    params = (status, note or "", record_id)

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(update_sql, params)
            conn.commit()
            return cur.rowcount > 0
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("历史库写入失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            cur = conn.execute(update_sql, params)
            conn.commit()
            return cur.rowcount > 0


def update_simulation(record_id: str, simulation: dict[str, Any]) -> bool:
    """更新历史记录的 simulation 数据"""
    init_db()
    db_path = _get_active_db_path()
    simulation_json = json.dumps(jsonable_encoder(simulation), ensure_ascii=False)
    update_sql = """
        UPDATE analysis_history
        SET simulation_json = ?
        WHERE id = ?
        """
    params = (simulation_json, record_id)

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(update_sql, params)
            conn.commit()
            return cur.rowcount > 0
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        logger.warning("历史库写入失败，已回退到临时目录: %s", fallback)
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            cur = conn.execute(update_sql, params)
            conn.commit()
            return cur.rowcount > 0
