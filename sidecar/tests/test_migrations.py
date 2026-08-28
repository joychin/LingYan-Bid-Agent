"""db_migrations 迁移测试：全新库直接盖版本、存量旧库升级保数据、init_db 幂等。"""

import sqlite3

from app import db
from app.config import app_db_path
from app.db_migrations import LATEST

# 无版本号的存量旧库形状（HITL 之前、kb 表引入之前）：runs 三态 CHECK、
# conversations 无 task_id、artifact_index 无 conversation_id/promotion_proposed、
# run_traces 无 duration_ms/reasoning
_LEGACY_SCHEMA = """
CREATE TABLE tasks(
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  progress_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE conversations(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE runs(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','error')),
  error TEXT, created_at TEXT NOT NULL);
CREATE TABLE artifact_index(
  artifact_id TEXT PRIMARY KEY, task_id TEXT,
  kind TEXT NOT NULL, schema_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
  cardinality TEXT NOT NULL, display_name TEXT NOT NULL, content_path TEXT NOT NULL,
  content_seq INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
  last_run_id TEXT, last_thread_id TEXT, emitted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE run_traces(
  run_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, message_id TEXT,
  tools TEXT NOT NULL, todos TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def _conn():
    c = sqlite3.connect(str(app_db_path()))
    c.row_factory = sqlite3.Row
    return c


def _make_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    c = _conn()
    c.executescript(_LEGACY_SCHEMA)
    c.executescript(
        """
        INSERT INTO tasks(id, title, progress_note, created_at) VALUES('t1', '老任务', '', '2026-01-01');
        INSERT INTO conversations(id, title, created_at) VALUES('c1', '老会话', '2026-01-01');
        INSERT INTO messages(id, conversation_id, role, content, created_at)
          VALUES('m1', 'c1', 'user', '你好', '2026-01-01');
        INSERT INTO runs(id, conversation_id, status, error, created_at)
          VALUES('r1', 'c1', 'completed', NULL, '2026-01-01');
        INSERT INTO artifact_index(artifact_id, task_id, kind, schema_id, schema_version,
          cardinality, display_name, content_path, content_seq, updated_at, emitted)
          VALUES('a1', 't1', 'doc.note', 'note-md', 1, 'task-multi', '老产物', 'x', 1, '2026-01-01', 1);
        """
    )
    c.commit()
    c.close()


def test_fresh_db_stamps_latest(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    c = _conn()
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST
        # 新库由 _SCHEMA 直接建全：waiting_input 可写（CHECK 已含四态）
        c.execute(
            "INSERT INTO runs(id, conversation_id, status, created_at) VALUES('r', 'c', 'waiting_input', '2026-01-01')"
        )
        c.rollback()
    finally:
        c.close()


def test_legacy_db_migrates_and_preserves_rows(monkeypatch, tmp_path):
    _make_legacy(monkeypatch, tmp_path)
    db.init_db()
    c = _conn()
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST

        # 旧数据原样保留
        assert c.execute("SELECT title FROM tasks WHERE id='t1'").fetchone()["title"] == "老任务"
        assert c.execute("SELECT content FROM messages WHERE id='m1'").fetchone()["content"] == "你好"
        assert c.execute("SELECT status FROM runs WHERE id='r1'").fetchone()["status"] == "completed"
        assert c.execute("SELECT display_name FROM artifact_index WHERE artifact_id='a1'").fetchone()[
            "display_name"
        ] == "老产物"

        # 全部补列就位
        for table, column in (
            ("runs", "interrupt"),
            ("runs", "last_seq"),
            ("runs", "pause_msg_id"),
            ("run_traces", "duration_ms"),
            ("run_traces", "reasoning"),
            ("conversations", "task_id"),
            ("artifact_index", "conversation_id"),
            ("artifact_index", "promotion_proposed"),
        ):
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            assert column in cols, f"{table}.{column} 未迁移"

        # runs 重建后 waiting_input 可写、旧行完好（同一断言集）
        c.execute(
            "INSERT INTO runs(id, conversation_id, status, created_at) VALUES('r2', 'c1', 'waiting_input', '2026-01-02')"
        )
        c.rollback()
    finally:
        c.close()


def test_init_db_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    db.init_db()  # 二次启动：已版本化库只查增量，无迁移可跑也不报错
    c = _conn()
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST
    finally:
        c.close()
