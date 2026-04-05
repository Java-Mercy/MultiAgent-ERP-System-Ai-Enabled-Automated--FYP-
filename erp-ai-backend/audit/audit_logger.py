"""
SQLite audit trail for API calls (SRS 3.2.13).

Uses only the Python standard library — no extra installs.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_DB_PATH = Path(__file__).resolve().parent / "audit.db"
_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_id TEXT,
            action_type TEXT NOT NULL,
            agent_used TEXT,
            record_id TEXT,
            status TEXT NOT NULL,
            error_message TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)")
    conn.commit()


class AuditLogger:
    """Append-only audit log with simple read helpers."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or _DB_PATH
        with _LOCK:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            _init_schema(conn)
            conn.close()

    def log_api_call(
        self,
        *,
        session_id: Optional[str],
        action_type: str,
        agent_used: Optional[str] = None,
        record_id: Optional[str] = None,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        sid = session_id if session_id is not None else ""
        with _LOCK:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            try:
                _init_schema(conn)
                conn.execute(
                    """
                    INSERT INTO audit_log
                    (timestamp, session_id, action_type, agent_used, record_id, status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        sid,
                        action_type,
                        agent_used,
                        record_id,
                        status,
                        error_message,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with _LOCK:
            conn = _connect()
            try:
                _init_schema(conn)
                cur = conn.execute(
                    """
                    SELECT id, timestamp, session_id, action_type, agent_used, record_id, status, error_message
                    FROM audit_log
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def daily_summary(self) -> dict[str, Any]:
        """Counts for the current UTC calendar day."""
        day_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with _LOCK:
            conn = _connect()
            try:
                _init_schema(conn)
                cur = conn.execute(
                    """
                    SELECT action_type, status, COUNT(*) AS c
                    FROM audit_log
                    WHERE timestamp LIKE ?
                    GROUP BY action_type, status
                    """,
                    (f"{day_prefix}%",),
                )
                rows = cur.fetchall()
            finally:
                conn.close()

        by_type: dict[str, int] = {}
        failed_count = 0
        total_actions = 0
        for r in rows:
            at = r["action_type"]
            st = (r["status"] or "").lower()
            c = int(r["c"])
            total_actions += c
            by_type[at] = by_type.get(at, 0) + c
            if st in ("error", "failed"):
                failed_count += c

        return {
            "total_actions": total_actions,
            "by_type": by_type,
            "failed_count": failed_count,
            "date_utc": day_prefix,
        }


_logger_instance: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = AuditLogger()
    return _logger_instance
