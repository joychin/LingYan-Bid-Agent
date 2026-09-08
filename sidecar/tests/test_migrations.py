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
            ("runs", "thinking"),
            ("run_traces", "duration_ms"),
            ("run_traces", "reasoning"),
            ("run_traces", "files"),
            ("conversations", "task_id"),
            ("artifact_index", "conversation_id"),
            ("messages", "run_id"),
        ):
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            assert column in cols, f"{table}.{column} 未迁移"

        # 迁移 19（两态移除）：state 与 promotion_proposed 死列被删除
        cols_art = {r["name"] for r in c.execute("PRAGMA table_info(artifact_index)").fetchall()}
        assert "state" not in cols_art
        assert "promotion_proposed" not in cols_art

        # 旧消息 run_id 为 NULL（无所属 run 语境，前端按独立消息渲染）
        assert c.execute("SELECT run_id FROM messages WHERE id='m1'").fetchone()["run_id"] is None

        # 旧 run 行 thinking 默认空串（读取方兜底 low）
        assert c.execute("SELECT thinking FROM runs WHERE id='r1'").fetchone()["thinking"] == ""

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


# 已版本化到 v9 的库形状（迁移 1-9 已应用）：runs 四态 CHECK + interrupt/last_seq/
# pause_msg_id、run_traces 带 duration_ms/reasoning、conversations 带 task_id、
# artifact_index 带 conversation_id/promotion_proposed；还没有 thinking/model/
# app_settings/messages.run_id
_V9_SCHEMA = """
CREATE TABLE tasks(
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  progress_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE conversations(
  id TEXT PRIMARY KEY, task_id TEXT, title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE runs(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','error','waiting_input')),
  error TEXT, created_at TEXT NOT NULL,
  interrupt TEXT, last_seq INTEGER NOT NULL DEFAULT 0, pause_msg_id TEXT);
CREATE TABLE artifact_index(
  artifact_id TEXT PRIMARY KEY, task_id TEXT, conversation_id TEXT,
  kind TEXT NOT NULL, schema_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
  cardinality TEXT NOT NULL, display_name TEXT NOT NULL, content_path TEXT NOT NULL,
  content_seq INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
  last_run_id TEXT, last_thread_id TEXT, emitted INTEGER NOT NULL DEFAULT 0,
  promotion_proposed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE run_traces(
  run_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, message_id TEXT,
  tools TEXT NOT NULL, todos TEXT NOT NULL, created_at TEXT NOT NULL,
  duration_ms INTEGER, reasoning TEXT NOT NULL DEFAULT '');
"""


def test_versioned_db_v9_migrates_incrementally(monkeypatch, tmp_path):
    """已版本化库增量升级（v9 → 最新）：只跑 10-15，v9 已有的列与数据原样保留
    （真实用户库都是从中间版本滚上来的，此前测试只覆盖 v0 旧库一跳到顶）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    c = _conn()
    c.executescript(_V9_SCHEMA)
    c.executescript(
        """
        INSERT INTO tasks(id, title, progress_note, created_at) VALUES('t1', '任务九', '', '2026-01-01');
        INSERT INTO conversations(id, task_id, title, created_at) VALUES('c1', 't1', '会话九', '2026-01-01');
        INSERT INTO messages(id, conversation_id, role, content, created_at)
          VALUES('m1', 'c1', 'user', '增量升级', '2026-01-01');
        INSERT INTO runs(id, conversation_id, status, created_at, last_seq)
          VALUES('r1', 'c1', 'waiting_input', '2026-01-01', 7);
        INSERT INTO artifact_index(artifact_id, task_id, kind, schema_id, schema_version,
          cardinality, display_name, content_path, content_seq, updated_at, emitted, promotion_proposed)
          VALUES('a1', 't1', 'doc.note', 'note-md', 1, 'task-multi', '产物九', 'x', 3, '2026-01-01', 1, 1);
        INSERT INTO run_traces(run_id, conversation_id, message_id, tools, todos, created_at, duration_ms, reasoning)
          VALUES('r1', 'c1', 'm1', '[]', '[]', '2026-01-01', 1234, '思考流');
        PRAGMA user_version = 9;
        """
    )
    c.commit()
    c.close()

    db.init_db()
    c = _conn()
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST

        # v9 已有数据原样保留（含运行态 last_seq / 内容版本 content_seq）
        assert c.execute("SELECT title FROM tasks WHERE id='t1'").fetchone()["title"] == "任务九"
        assert c.execute("SELECT last_seq FROM runs WHERE id='r1'").fetchone()["last_seq"] == 7
        assert c.execute("SELECT status FROM runs WHERE id='r1'").fetchone()["status"] == "waiting_input"
        assert c.execute("SELECT duration_ms FROM run_traces WHERE run_id='r1'").fetchone()["duration_ms"] == 1234
        assert c.execute("SELECT reasoning FROM run_traces WHERE run_id='r1'").fetchone()["reasoning"] == "思考流"
        # 迁移 15：files 列就位，旧 trace 行回读默认空清单
        assert c.execute("SELECT files FROM run_traces WHERE run_id='r1'").fetchone()["files"] == "[]"
        assert c.execute("SELECT content_seq FROM artifact_index WHERE artifact_id='a1'").fetchone()["content_seq"] == 3

        # 增量补列/补表就位
        cols_runs = {r["name"] for r in c.execute("PRAGMA table_info(runs)").fetchall()}
        assert {"thinking", "model"} <= cols_runs
        cols_msg = {r["name"] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
        assert "run_id" in cols_msg
        assert c.execute("SELECT run_id FROM messages WHERE id='m1'").fetchone()["run_id"] is None
        # 迁移 19（两态移除）：state/promotion_proposed 列被删除，行数据保留
        cols_art = {r["name"] for r in c.execute("PRAGMA table_info(artifact_index)").fetchall()}
        assert "state" not in cols_art
        assert "promotion_proposed" not in cols_art
        assert c.execute("SELECT display_name FROM artifact_index WHERE artifact_id='a1'").fetchone()[
            "display_name"
        ] == "产物九"
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "app_settings" in tables

        # 升级后的行可被 db 层正常读取
        row = db.get_run("r1")
        assert row is not None and row["status"] == "waiting_input"
    finally:
        c.close()


# v15 时代的知识库旧形状：kb_items 无 bucket、kb_segments 无 material_id、无 kb_materials
_KB_V15_SCHEMA = """
CREATE TABLE kb_items(
  id TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_hash TEXT NOT NULL,
  title TEXT NOT NULL, ext TEXT NOT NULL, doc_type TEXT,
  parse_status TEXT NOT NULL DEFAULT 'pending', extract_status TEXT NOT NULL DEFAULT 'pending',
  review_status TEXT NOT NULL DEFAULT 'pending_review',
  suggested_metadata TEXT, business_metadata TEXT, error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE VIRTUAL TABLE kb_segments USING fts5(
  body, item_id UNINDEXED, section_path UNINDEXED,
  line_start UNINDEXED, line_end UNINDEXED, page_start UNINDEXED);
"""


def test_migration_18_kb_v3_rebuild(monkeypatch, tmp_path):
    """kb 迁移 18（v3 内容角色模型，不兼容旧两桶）：三表整组 DROP 重建——旧 kb 行
    清空（用户明令旧数据可清）、新形状就位（progress/kind/image_path/page）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    c = _conn()
    c.executescript(_KB_V15_SCHEMA)
    c.execute(
        "INSERT INTO kb_items(id, file_name, file_hash, title, ext, created_at, updated_at)"
        " VALUES('kb_old', 'a.pdf', 'h', 't', '.pdf', '2026-01-01', '2026-01-01')"
    )
    c.execute("INSERT INTO kb_segments(body, item_id) VALUES('旧段内容', 'kb_old')")
    c.execute("PRAGMA user_version = 15")
    c.commit()
    c.close()

    db.init_db()

    c = _conn()
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST
        # 旧数据清空（v3 不兼容重建；迁移 21 再按素材分离重建）
        assert c.execute("SELECT COUNT(*) FROM kb_items").fetchone()[0] == 0
        # 新形状：kb_items 有 progress 无 bucket
        item_cols = {r["name"] for r in c.execute("PRAGMA table_info(kb_items)")}
        assert "progress" in item_cols and "bucket" not in item_cols
        seg_cols = {r["name"] for r in c.execute("PRAGMA table_info(kb_segments)")}
        assert "material_id" in seg_cols
        # 素材分离（迁移 21）：kb_materials 删除；mt_files/mt_blocks 就位
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "kb_materials" not in tables
        assert {"mt_files", "mt_blocks"} <= tables
    finally:
        c.close()


def test_migration_25_run_turn_usage_and_trace_backfill(monkeypatch, tmp_path):
    """迁移 25：run_turn_usage 明细表就位 + error 收尾 bug 期间落库的孤儿 trace
    回填挂到同 run 最后一条 assistant 消息（无产出的 run 不动、已挂载的不动）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    c = _conn()
    c.executescript(
        """
        INSERT INTO tasks(id, title, progress_note, created_at) VALUES('t1', '任务', '', '2026-01-01');
        INSERT INTO conversations(id, task_id, title, created_at) VALUES('c1', 't1', '会话', '2026-01-01');
        INSERT INTO runs(id, conversation_id, status, created_at) VALUES('r1', 'c1', 'error', '2026-01-01');
        INSERT INTO runs(id, conversation_id, status, created_at) VALUES('r2', 'c1', 'error', '2026-01-02');
        INSERT INTO runs(id, conversation_id, status, created_at) VALUES('r3', 'c1', 'completed', '2026-01-03');
        -- r1：暂停消息在早、（任务中断）半截在后 → 孤儿 trace 应回填到最后一条
        INSERT INTO messages(id, conversation_id, role, content, created_at, run_id)
          VALUES('m_pause', 'c1', 'assistant', '（等待你的输入…）', '2026-01-01 08:00:00', 'r1');
        INSERT INTO messages(id, conversation_id, role, content, created_at, run_id)
          VALUES('m_err', 'c1', 'assistant', '写到一半\n\n（任务中断）', '2026-01-01 09:00:00', 'r1');
        -- r2：秒挂无产出（无 assistant 消息）→ 保持空
        -- r3：已挂载的行不被改写
        INSERT INTO messages(id, conversation_id, role, content, created_at, run_id)
          VALUES('m_final', 'c1', 'assistant', '完成', '2026-01-03 09:00:00', 'r3');
        INSERT INTO run_traces(run_id, conversation_id, message_id, tools, todos, created_at)
          VALUES('r1', 'c1', NULL, '[]', '[]', '2026-01-01');
        INSERT INTO run_traces(run_id, conversation_id, message_id, tools, todos, created_at)
          VALUES('r2', 'c1', '', '[]', '[]', '2026-01-02');
        INSERT INTO run_traces(run_id, conversation_id, message_id, tools, todos, created_at)
          VALUES('r3', 'c1', 'm_final', '[]', '[]', '2026-01-03');
        """
    )
    # 降级回 v24：删掉新表、退版本号，模拟修复上线前的库
    c.execute("DROP TABLE run_turn_usage")
    c.execute("PRAGMA user_version = 24")
    c.commit()
    c.close()

    db.init_db()  # 触发迁移 25

    c = _conn()
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST
        assert c.execute("SELECT message_id FROM run_traces WHERE run_id='r1'").fetchone()["message_id"] == "m_err"
        assert c.execute("SELECT message_id FROM run_traces WHERE run_id='r2'").fetchone()["message_id"] in (None, "")
        assert c.execute("SELECT message_id FROM run_traces WHERE run_id='r3'").fetchone()["message_id"] == "m_final"
        # 明细表就位（_SCHEMA 同款形状）
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "run_turn_usage" in tables
        cols = {r["name"] for r in c.execute("PRAGMA table_info(run_turn_usage)").fetchall()}
        assert {"run_id", "scope", "input", "cached", "output", "reasoning"} <= cols
    finally:
        c.close()


def test_migration_26_kb_check_result(monkeypatch, tmp_path):
    """迁移 26：kb_items.check_result 列（锚点回文核对结果）就位。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    c = _conn()
    try:
        c.execute("ALTER TABLE kb_items DROP COLUMN check_result")  # 模拟 v25 旧库
        c.execute("PRAGMA user_version = 25")
        c.commit()
    finally:
        c.close()
    db.init_db()
    c = _conn()
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(kb_items)")}
        assert "check_result" in cols
        assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST
    finally:
        c.close()
