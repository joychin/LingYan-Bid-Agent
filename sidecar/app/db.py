"""SQLite 持久化（标准库 sqlite3，WAL 模式）。

tasks / conversations / messages / runs / artifact_index。与 DeepAgents 的
checkpointer（data/agent.db）分离，避免锁竞争。所有写操作在各自连接上执行，
连接默认 autocommit（isolation_level=None）。

任务层（P4）：会话归属任务（conversations.task_id）；Artifact 分两层——
任务「正式稿」（artifact_index.task_id 非空）与会话「过程稿」
（artifact_index.conversation_id 非空）。

artifact_index 是类型化 Artifact 的可重建索引 + 运行态（content_seq/emitted）；
权威身份在每个 Artifact 包的 manifest.json（见 artifact_store.py），本表丢失后
可由 manifest 重建（rebuild_artifact_index）。
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from .config import app_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  progress_note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, task_id TEXT, title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant')),
  content TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','error','waiting_input')),
  error TEXT, created_at TEXT NOT NULL,
  interrupt TEXT, last_seq INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS artifact_index(
  artifact_id TEXT PRIMARY KEY,
  task_id TEXT,
  conversation_id TEXT,
  kind TEXT NOT NULL, schema_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
  cardinality TEXT NOT NULL, display_name TEXT NOT NULL,
  content_path TEXT NOT NULL,
  content_seq INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  last_run_id TEXT, last_thread_id TEXT,
  promotion_proposed INTEGER NOT NULL DEFAULT 0,
  emitted INTEGER NOT NULL DEFAULT 0);
-- run 执行过程快照（工具步骤树 + todos）：run 结束落一份，message_id 关联 assistant
-- 消息（error 中断的 run 无 message_id），历史会话/刷新后执行过程仍可见
CREATE TABLE IF NOT EXISTS run_traces(
  run_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  message_id TEXT,
  tools TEXT NOT NULL,
  todos TEXT NOT NULL,
  duration_ms INTEGER,
  created_at TEXT NOT NULL);
"""

# 索引与建表分两步：旧库先建表→探测补列→再建索引（索引引用新列，顺序不能反）
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_run_traces_message ON run_traces(message_id);
CREATE INDEX IF NOT EXISTS idx_artifact_index_scope
  ON artifact_index(task_id, conversation_id, kind, schema_id, schema_version);
"""


def _conn() -> sqlite3.Connection:
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(app_db_path()), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _rebuild_runs_for_waiting_input(conn: sqlite3.Connection) -> None:
    """runs 表 CHECK 增加 'waiting_input'（HITL 等待用户裁决）——SQLite 不能
    ALTER CHECK，探测旧建表 SQL 后整表重建（CREATE new + copy + rename）。
    旧行 status 原样带过，interrupt/last_seq 取列默认值。数据量小，秒级完成。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'"
    ).fetchone()
    if row is None or "waiting_input" in row["sql"]:
        return
    conn.execute(
        """CREATE TABLE runs_migrate(
          id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('running','completed','error','waiting_input')),
          error TEXT, created_at TEXT NOT NULL,
          interrupt TEXT, last_seq INTEGER NOT NULL DEFAULT 0)"""
    )
    conn.execute(
        "INSERT INTO runs_migrate(id, conversation_id, status, error, created_at, interrupt, last_seq)"
        " SELECT id, conversation_id, status, error, created_at, NULL, 0 FROM runs"
    )
    conn.execute("DROP TABLE runs")  # 索引随表删除，_SCHEMA_INDEXES 在迁移后重建
    conn.execute("ALTER TABLE runs_migrate RENAME TO runs")


def init_db() -> None:
    conn = _conn()
    try:
        conn.executescript(_SCHEMA)
        # runs 表整表迁移（CHECK 约束变化）必须先于列探测：新表自带全部新列
        _rebuild_runs_for_waiting_input(conn)
        # 仓内无迁移机制（IF NOT EXISTS 不改已有表）：后加的列用启动时探测补齐
        # （新库由 _SCHEMA 直接建全，旧库走 ALTER）
        for table, column, ddl in (
            ("runs", "interrupt", "ALTER TABLE runs ADD COLUMN interrupt TEXT"),
            ("runs", "last_seq", "ALTER TABLE runs ADD COLUMN last_seq INTEGER NOT NULL DEFAULT 0"),
            ("run_traces", "duration_ms", "ALTER TABLE run_traces ADD COLUMN duration_ms INTEGER"),
            ("conversations", "task_id", "ALTER TABLE conversations ADD COLUMN task_id TEXT"),
            ("artifact_index", "conversation_id", "ALTER TABLE artifact_index ADD COLUMN conversation_id TEXT"),
            (
                "artifact_index",
                "promotion_proposed",
                "ALTER TABLE artifact_index ADD COLUMN promotion_proposed INTEGER NOT NULL DEFAULT 0",
            ),
        ):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(ddl)
        conn.executescript(_SCHEMA_INDEXES)
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- 任务（P4 任务层：会话与正式稿的容器） ----------


def create_task(title: str) -> dict:
    title = (title or "").strip() or "新任务"
    tid = f"t_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO tasks(id, title, progress_note, created_at) VALUES (?,?,?,?)",
            (tid, title, "", now),
        )
    finally:
        conn.close()
    return {"id": tid, "title": title, "progress_note": "", "created_at": now}


def list_tasks() -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, title, progress_note, created_at FROM tasks ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_task(tid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, title, progress_note, created_at FROM tasks WHERE id=?", (tid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def rename_task(tid: str, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("任务名不能为空")
    conn = _conn()
    try:
        conn.execute("UPDATE tasks SET title=? WHERE id=?", (title, tid))
    finally:
        conn.close()
    return {"id": tid, "title": title}


def update_task_progress(tid: str, note: str) -> None:
    """进度便签：任务白板，整体覆盖（last-write-wins），非版本化内容。"""
    conn = _conn()
    try:
        conn.execute("UPDATE tasks SET progress_note=? WHERE id=?", (note, tid))
    finally:
        conn.close()


def list_task_conversation_ids(tid: str) -> list[str]:
    conn = _conn()
    try:
        rows = conn.execute("SELECT id FROM conversations WHERE task_id=?", (tid,)).fetchall()
    finally:
        conn.close()
    return [r["id"] for r in rows]


def delete_task(tid: str) -> None:
    """删任务行及其全部会话数据与产物索引行（过程稿行也带所属 task_id，一并清理）。
    磁盘上任务目录的归档由调用方（API 层）先处理。"""
    conn = _conn()
    try:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE task_id=?)",
            (tid,),
        )
        conn.execute(
            "DELETE FROM runs WHERE conversation_id IN (SELECT id FROM conversations WHERE task_id=?)",
            (tid,),
        )
        conn.execute(
            "DELETE FROM run_traces WHERE conversation_id IN (SELECT id FROM conversations WHERE task_id=?)",
            (tid,),
        )
        conn.execute("DELETE FROM conversations WHERE task_id=?", (tid,))
        conn.execute("DELETE FROM artifact_index WHERE task_id=?", (tid,))
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
    finally:
        conn.close()


def create_conversation(task_id: str | None = None, title: str | None = None) -> dict:
    cid = f"c_{uuid.uuid4().hex[:12]}"
    title = (title or "").strip() or "新对话"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO conversations(id, task_id, title, created_at) VALUES (?,?,?,?)",
            (cid, task_id, title, _now()),
        )
    finally:
        conn.close()
    return {"id": cid, "task_id": task_id, "title": title, "created_at": _now()}


def list_conversations() -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, task_id, title, created_at FROM conversations ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_conversation(cid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, task_id, title, created_at FROM conversations WHERE id=?", (cid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def rename_conversation(cid: str, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("标题不能为空")
    conn = _conn()
    try:
        conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, cid))
    finally:
        conn.close()
    return {"id": cid, "title": title}


def set_title_if_default(cid: str, title: str) -> bool:
    """自动命名专用：仅当标题仍是默认「新对话」时改写（单条原子条件 UPDATE），
    返回是否写入——LLM 调用在飞时用户手动改名，自动结果被静默丢弃，无需锁。"""
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE conversations SET title=? WHERE id=? AND title='新对话'",
            (title, cid),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_conversation(cid: str) -> None:
    """删除会话及其消息/run 记录与「过程稿」索引行（磁盘上 threads/<cid>/ 目录
    由调用方 API 层先清理）。表之间无外键约束（PRAGMA foreign_keys=ON 对未声明
    FKs 不生效），手动清理子表。
    """
    conn = _conn()
    try:
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        conn.execute("DELETE FROM runs WHERE conversation_id=?", (cid,))
        conn.execute("DELETE FROM run_traces WHERE conversation_id=?", (cid,))
        conn.execute("DELETE FROM artifact_index WHERE conversation_id=?", (cid,))
        conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
    finally:
        conn.close()


def save_run_trace(
    run_id: str, cid: str, message_id: str | None, tools: list, todos: list, duration_ms: int | None = None
) -> None:
    """run 结束时落执行过程快照（幂等：同 run 重写）。"""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO run_traces(run_id, conversation_id, message_id, tools, todos, duration_ms, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (run_id, cid, message_id, json.dumps(tools, ensure_ascii=False), json.dumps(todos, ensure_ascii=False), duration_ms, _now()),
        )
    finally:
        conn.close()


def get_traces_for_messages(message_ids: list[str]) -> dict[str, dict]:
    """按 assistant message_id 批量取 trace，解析好 tools/todos 返回 {message_id: row}。"""
    if not message_ids:
        return {}
    ph = ",".join("?" * len(message_ids))
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT message_id, tools, todos, duration_ms FROM run_traces WHERE message_id IN ({ph})",
            message_ids,
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for r in rows:
        try:
            out[r["message_id"]] = {
                "tools": json.loads(r["tools"]),
                "todos": json.loads(r["todos"]),
                "durationMs": r["duration_ms"],
            }
        except ValueError:
            continue  # 防御：快照损坏不阻断消息列表
    return out


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
            "WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC",
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


def get_run(rid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, conversation_id, status, error, created_at, interrupt, last_seq"
            " FROM runs WHERE id=?",
            (rid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def interrupt_run(rid: str, requests: list, last_seq: int) -> None:
    """HITL 暂停：置 waiting_input 并保存快照（前端恢复审批卡）与事件序号（续段续接）。"""
    conn = _conn()
    try:
        conn.execute(
            "UPDATE runs SET status='waiting_input', interrupt=?, last_seq=? WHERE id=?",
            (json.dumps(requests, ensure_ascii=False), last_seq, rid),
        )
    finally:
        conn.close()


def resume_run(rid: str) -> None:
    """用户已裁决：转回 running，快照清空（last_seq 保留，续段事件序号续接用）。"""
    conn = _conn()
    try:
        conn.execute("UPDATE runs SET status='running', interrupt=NULL WHERE id=?", (rid,))
    finally:
        conn.close()


def recover_stale_runs() -> int:
    """sidecar 崩溃/被杀重启后，把残留的 running run 标记为 error。

    否则该会话会一直命中 409「已有进行中的任务」，永久无法再发消息。
    waiting_input 不翻：interrupt 存活于 agent.db checkpoint，重启后用户仍可裁决续跑。
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
    """该会话是否有占用中的 run：running（执行中）或 waiting_input（等待用户裁决——
    语义是「请先处理待确认」，而不是可以另起新任务）。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id FROM runs WHERE conversation_id=? AND status IN ('running','waiting_input')",
            (cid,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def get_latest_run(cid: str) -> dict | None:
    """该会话最近一条 run（任意状态）。SSE 连接建立时据此下发 run.state 对账事件，
    供断线重连的客户端恢复 running（无 agent.started 补发）或收敛已结束的 run。
    waiting_input 时附 interrupt 快照（API 层解析为 requests 恢复审批卡）。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, conversation_id, status, error, created_at, interrupt, last_seq"
            " FROM runs WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def load_recent_history(cid: str, limit: int = 20) -> list[dict]:
    """给 agent 做线程记忆预热的最近消息（role/content 对，不含 id）。

    记忆对账（agent.recover_agent_memory）以此为恢复源。created_at 只有秒级精度，
    同秒消息必须用 rowid（插入序）决胜，否则顺序随机（uuid id 排序无意义）。
    """
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (cid, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]


_INDEX_COLS = (
    "artifact_id, task_id, conversation_id, kind, schema_id, schema_version, cardinality, "
    "display_name, content_path, content_seq, updated_at, last_run_id, last_thread_id, "
    "promotion_proposed, emitted"
)


def upsert_artifact_index(rec: dict) -> None:
    """写入/覆盖一行索引（发布与修订共用）。新发布的行 emitted=0，待 run 边界发事件。"""
    conn = _conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO artifact_index({_INDEX_COLS}) VALUES ({','.join('?' * 15)})",
            (
                rec["artifact_id"], rec.get("task_id"), rec.get("conversation_id"), rec["kind"],
                rec["schema_id"], rec["schema_version"], rec["cardinality"], rec["display_name"],
                rec["content_path"], rec.get("content_seq", 1), rec["updated_at"],
                rec.get("last_run_id"), rec.get("last_thread_id"),
                1 if rec.get("promotion_proposed") else 0,
                rec.get("emitted", 0),
            ),
        )
    finally:
        conn.close()


def find_artifact_index(
    kind: str,
    schema_id: str,
    schema_version: int,
    task_id: str | None = None,
    conversation_id: str | None = None,
) -> dict | None:
    """按作用域找同契约现有 Artifact（task-single upsert 用）。

    作用域：conversation_id 非空 = 会话过程稿；否则 task_id 非空 = 任务正式稿
    （过程稿行也带所属 task_id，正式稿查询必须排除它们）；皆空不支持（§16 移除全局作用域）。
    """
    if conversation_id is not None:
        where, args = "conversation_id=?", [conversation_id]
    elif task_id is not None:
        where, args = "task_id=? AND conversation_id IS NULL", [task_id]
    else:
        return None
    conn = _conn()
    try:
        row = conn.execute(
            f"SELECT {_INDEX_COLS} FROM artifact_index WHERE {where} "
            "AND kind=? AND schema_id=? AND schema_version=?",
            (*args, kind, schema_id, schema_version),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_artifact_index(
    task_id: str | None = None, conversation_id: str | None = None
) -> list[dict]:
    """产物索引列表，可按任务（正式稿）或会话（过程稿）过滤；无参 = 全部。

    task 过滤只返回正式稿行（过程稿行带所属 task_id，须用 conversation_id 查）。
    """
    where, args = "", []
    if conversation_id is not None:
        where, args = "WHERE conversation_id=?", [conversation_id]
    elif task_id is not None:
        where, args = "WHERE task_id=? AND conversation_id IS NULL", [task_id]
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT {_INDEX_COLS} FROM artifact_index {where} ORDER BY updated_at DESC, artifact_id DESC",
            args,
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def delete_artifact_index(aid: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM artifact_index WHERE artifact_id=?", (aid,))
    finally:
        conn.close()


def set_promotion_proposed(aid: str, proposed: bool) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE artifact_index SET promotion_proposed=? WHERE artifact_id=?", (1 if proposed else 0, aid)
        )
    finally:
        conn.close()


def get_artifact_index(aid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            f"SELECT {_INDEX_COLS} FROM artifact_index WHERE artifact_id=?", (aid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def pending_emit(run_id: str) -> list[dict]:
    """该 run 发布、尚未发 artifact.created 的产物（run 边界逐个发出后 mark_emitted）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT {_INDEX_COLS} FROM artifact_index WHERE last_run_id=? AND emitted=0",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mark_emitted(aid: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE artifact_index SET emitted=1 WHERE artifact_id=?", (aid,))
    finally:
        conn.close()


def rebuild_artifact_index(manifests: list[dict], content_path_of) -> int:
    """用磁盘 manifest 全量重建索引（manifest 权威、索引可重建）。

    启动时调用：清空后重扫。运行态自然复位（content_seq=1、promotion_proposed=0、
    emitted=1——启动时无消费者，残留 emitted=0 只会让 run 边界空转，直接置 1）。
    content_path_of: manifest -> content_path 的求值函数（注入避免依赖 store；
    包位置按 manifest 的 scope 派生）。
    返回重建行数。
    """
    rows = []
    for m in manifests:
        schema = m.get("schema", {})
        rows.append(
            (
                m["artifact_id"], m.get("task_id"), m.get("conversation_id"), m["kind"],
                schema.get("id", ""), schema.get("version", 1),
                m.get("cardinality", "task-single"), m.get("display_name", ""),
                content_path_of(m), 1,
                m.get("created_at", _now()), None, None, 0, 1,
            )
        )
    conn = _conn()
    try:
        conn.execute("DELETE FROM artifact_index")
        conn.executemany(
            f"INSERT INTO artifact_index({_INDEX_COLS}) VALUES ({','.join('?' * 15)})",
            rows,
        )
    finally:
        conn.close()
    return len(rows)
