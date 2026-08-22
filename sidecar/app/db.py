"""SQLite 持久化（标准库 sqlite3，WAL 模式）。

三个表：conversations / messages / runs。与 DeepAgents 的 checkpointer（data/agent.db）分离，
避免锁竞争。所有写操作在各自连接上执行，连接默认 autocommit（isolation_level=None）。
"""

import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from .config import app_db_path

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','error')),
  error TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conversation_id);
"""


def _conn() -> sqlite3.Connection:
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(app_db_path()), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    conn = _conn()
    try:
        conn.executescript(_SCHEMA)
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_conversation(title: str | None = None) -> dict:
    cid = f"c_{uuid.uuid4().hex[:12]}"
    title = (title or "").strip() or "新对话"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO conversations(id, title, created_at) VALUES (?,?,?)",
            (cid, title, _now()),
        )
    finally:
        conn.close()
    return {"id": cid, "title": title, "created_at": _now()}


def list_conversations() -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_conversation(cid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, title, created_at FROM conversations WHERE id=?", (cid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def create_user_message(cid: str, content: str) -> dict:
    mid = f"m_{uuid.uuid4().hex[:12]}"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?,?,?,?,?)",
            (mid, cid, "user", content, _now()),
        )
    finally:
        conn.close()
    return {"id": mid, "conversation_id": cid, "role": "user", "content": content, "created_at": _now()}


def append_assistant_message(cid: str, content: str) -> dict:
    mid = f"m_{uuid.uuid4().hex[:12]}"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?,?,?,?,?)",
            (mid, cid, "assistant", content, _now()),
        )
    finally:
        conn.close()
    return {"id": mid, "conversation_id": cid, "role": "assistant", "content": content, "created_at": _now()}


def list_messages(cid: str) -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, created_at FROM messages "
            "WHERE conversation_id=? ORDER BY created_at ASC, id ASC",
            (cid,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def create_run(cid: str) -> dict:
    rid = f"r_{uuid.uuid4().hex[:12]}"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO runs(id, conversation_id, status, error, created_at) VALUES (?,?,?,?,?)",
            (rid, cid, "running", None, _now()),
        )
    finally:
        conn.close()
    return {"id": rid, "conversation_id": cid, "status": "running", "error": None, "created_at": _now()}


def finish_run(rid: str, status: str, error: str | None = None) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE runs SET status=?, error=? WHERE id=?", (status, error, rid)
        )
    finally:
        conn.close()


def recover_stale_runs() -> int:
    """sidecar 崩溃/被杀重启后，把残留的 running run 标记为 error。

    否则该会话会一直命中 409「已有进行中的任务」，永久无法再发消息。
    """
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE runs SET status='error', error=? WHERE status='running'",
            ("sidecar 重启，任务中断",),
        )
        return cur.rowcount
    finally:
        conn.close()


def active_run_exists(cid: str) -> bool:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id FROM runs WHERE conversation_id=? AND status='running'", (cid,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def load_recent_history(cid: str, limit: int = 20) -> list[dict]:
    """给 agent 做线程记忆预热的最近消息（role/content 对，不含 id）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (cid, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]
