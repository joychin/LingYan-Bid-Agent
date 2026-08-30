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
  content TEXT NOT NULL, created_at TEXT NOT NULL,
  run_id TEXT);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('running','completed','error','waiting_input')),
  error TEXT, created_at TEXT NOT NULL,
  interrupt TEXT, last_seq INTEGER NOT NULL DEFAULT 0,
  pause_msg_id TEXT,
  thinking TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS app_settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL);
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
-- run 执行过程快照（工具步骤树 + todos + 主 agent 思考流）：run 结束落一份，
-- message_id 关联 assistant 消息（error 中断的 run 无 message_id），
-- 历史会话/刷新后执行过程与「深度思考」仍可见
CREATE TABLE IF NOT EXISTS run_traces(
  run_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  message_id TEXT,
  tools TEXT NOT NULL,
  todos TEXT NOT NULL,
  duration_ms INTEGER,
  reasoning TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
-- 知识库条目（一个上传文件一条；suggested=LLM 抽取建议、business=确认后真值，
-- 两列之隔即审核边界——确认动作把 suggested 拷入 business，LLM 永不覆盖 business）
CREATE TABLE IF NOT EXISTS kb_items(
  id TEXT PRIMARY KEY,
  file_name TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  title TEXT NOT NULL,
  ext TEXT NOT NULL,
  doc_type TEXT,
  parse_status TEXT NOT NULL DEFAULT 'pending',
  extract_status TEXT NOT NULL DEFAULT 'pending',
  review_status TEXT NOT NULL DEFAULT 'pending_review',
  suggested_metadata TEXT,
  business_metadata TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
-- 知识库检索切段（FTS5）：按 outline 节点切段一段一行，body 存 jieba 预分词文本
-- （写入/查询两侧同源分词，unicode61 切英文数字 token；索引可从 kb_items+磁盘 md 重建）
CREATE VIRTUAL TABLE IF NOT EXISTS kb_segments USING fts5(
  body, item_id UNINDEXED, section_path UNINDEXED,
  line_start UNINDEXED, line_end UNINDEXED, page_start UNINDEXED);
"""

# 索引与建表分两步：旧库先建表→探测补列→再建索引（索引引用新列，顺序不能反）
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_run_traces_message ON run_traces(message_id);
CREATE INDEX IF NOT EXISTS idx_artifact_index_scope
  ON artifact_index(task_id, conversation_id, kind, schema_id, schema_version);
-- run 边界 pending_emit（WHERE last_run_id=? AND emitted=0）：每次 run 收尾一次
CREATE INDEX IF NOT EXISTS idx_artifact_index_last_run
  ON artifact_index(last_run_id, emitted);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_items_hash ON kb_items(file_hash);
CREATE INDEX IF NOT EXISTS idx_kb_items_review ON kb_items(review_status);
"""


def _conn() -> sqlite3.Connection:
    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(app_db_path()), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """建库/升级：_SCHEMA 是新库权威全量，旧库经 db_migrations 编号迁移补齐。

    user_version==0 且无表 = 全新库（_SCHEMA 直接建全，盖最新版本号）；
    user_version==0 且有任一已知表 = 无版本号的存量旧库（跑全部迁移后盖版本号）；
    user_version>0 = 已版本化，只跑增量迁移（版本号是权威，手动降表不再自动修复）。
    索引最后建（可能引用迁移补的列）。
    """
    from . import db_migrations

    _KNOWN_TABLES = (
        "tasks", "conversations", "messages", "runs", "run_traces",
        "artifact_index", "kb_items", "kb_segments",
    )

    conn = _conn()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        existing = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        legacy = version == 0 and bool(existing & set(_KNOWN_TABLES))
        conn.executescript(_SCHEMA)
        if legacy:
            db_migrations.apply(conn, 0)
        elif version > 0:
            db_migrations.apply(conn, version)
        else:
            conn.execute(f"PRAGMA user_version = {db_migrations.LATEST}")
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
    磁盘上任务目录的归档由调用方（API 层）先处理。六条 DELETE 在单事务内：
    连接是 autocommit（isolation_level=None），逐条提交时进程中止会留半级联孤儿行
    （kb_delete_item 同款 BEGIN IMMEDIATE 先例）。"""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
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
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
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
    FKs 不生效），手动清理子表；单事务防进程中止留半级联孤儿行。
    """
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM runs WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM run_traces WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM artifact_index WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def save_run_trace(
    run_id: str,
    cid: str,
    message_id: str | None,
    tools: list,
    todos: list,
    duration_ms: int | None = None,
    reasoning: str = "",
) -> None:
    """run 结束时落执行过程快照（幂等：同 run 重写）。reasoning = 主 agent 思考流整段。"""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO run_traces(run_id, conversation_id, message_id, tools, todos, duration_ms, reasoning, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id,
                cid,
                message_id,
                json.dumps(tools, ensure_ascii=False),
                json.dumps(todos, ensure_ascii=False),
                duration_ms,
                reasoning,
                _now(),
            ),
        )
    finally:
        conn.close()


def get_run_trace(run_id: str) -> dict | None:
    """按 run_id 取单条 trace（续跑段收尾时与既有行合并用，见 agent._save_merged_trace）。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT run_id, message_id, tools, todos, duration_ms, reasoning FROM run_traces WHERE run_id=?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return {
            "message_id": row["message_id"],
            "tools": json.loads(row["tools"] or "[]"),
            "todos": json.loads(row["todos"] or "[]"),
            "durationMs": row["duration_ms"],
            "reasoning": row["reasoning"] or "",
        }
    except ValueError:
        return None


def get_traces_for_messages(message_ids: list[str]) -> dict[str, dict]:
    """按 assistant message_id 批量取 trace，解析好 tools/todos/reasoning 返回 {message_id: row}。"""
    if not message_ids:
        return {}
    ph = ",".join("?" * len(message_ids))
    conn = _conn()
    try:
        rows = conn.execute(
            f"SELECT message_id, tools, todos, duration_ms, reasoning FROM run_traces WHERE message_id IN ({ph})",
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
                "reasoning": r["reasoning"] or "",
            }
        except ValueError:
            continue  # 防御：快照损坏不阻断消息列表
    return out


def create_user_message(cid: str, content: str, rid: str | None = None) -> dict:
    mid = f"m_{uuid.uuid4().hex[:12]}"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO messages(id, conversation_id, role, content, created_at, run_id)"
            " VALUES (?,?,?,?,?,?)",
            (mid, cid, "user", content, _now(), rid),
        )
    finally:
        conn.close()
    return {"id": mid, "conversation_id": cid, "role": "user", "content": content, "created_at": _now(), "run_id": rid}


def append_assistant_message(cid: str, content: str, rid: str | None = None) -> dict:
    mid = f"m_{uuid.uuid4().hex[:12]}"
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO messages(id, conversation_id, role, content, created_at, run_id)"
            " VALUES (?,?,?,?,?,?)",
            (mid, cid, "assistant", content, _now(), rid),
        )
    finally:
        conn.close()
    return {"id": mid, "conversation_id": cid, "role": "assistant", "content": content, "created_at": _now(), "run_id": rid}


def list_messages(cid: str) -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, created_at, run_id FROM messages "
            "WHERE conversation_id=? ORDER BY created_at ASC, rowid ASC",
            (cid,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_setting(key: str) -> str | None:
    """app_settings KV 读（2026-08-29 起模型配置与凭证的真值存储；value 为 JSON 文本）。
    表不存在（init_db 前的极早读取）按无值处理。"""
    conn = _conn()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO app_settings(key, value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    finally:
        conn.close()


def set_settings_many(items: dict[str, str]) -> None:
    """app_settings KV 批量写（单事务）。模型列表/默认/后台角色三键语义上是一套
    配置——逐键 autocommit 时进程中止会留半套（读侧有成员校验兜底，但写入不该
    依赖兜底）。连接是 autocommit（isolation_level=None），显式 BEGIN 包住。"""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(
                "INSERT INTO app_settings(key, value) VALUES(?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(items.items()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def create_run(cid: str, thinking: str = "low", model: str = "") -> dict:
    """创建 run 行。thinking 是本 run 的思考档位（low/medium/high）、model 是选用的
    模型 profile id（空=default），都随行存档——HITL 续跑（resume）时据此恢复，
    无需客户端重传。"""
    rid = f"r_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO runs(id, conversation_id, status, error, created_at, thinking, model) VALUES (?,?,?,?,?,?,?)",
            (rid, cid, "running", None, now, thinking, model),
        )
    finally:
        conn.close()
    return {"id": rid, "conversation_id": cid, "status": "running", "error": None, "created_at": now, "thinking": thinking, "model": model}


def finish_run(rid: str, status: str, error: str | None = None, last_seq: int | None = None) -> None:
    """run 收尾。last_seq 回写终态事件序号（此前只有 interrupt_run 写过——续跑完成后
    runs.last_seq 永远停在暂停值，对账/排查拿到的是错数）。"""
    conn = _conn()
    try:
        if last_seq is not None:
            conn.execute(
                "UPDATE runs SET status=?, error=?, last_seq=? WHERE id=?",
                (status, error, last_seq, rid),
            )
        else:
            conn.execute("UPDATE runs SET status=?, error=? WHERE id=?", (status, error, rid))
    finally:
        conn.close()


def finish_run_if_running(rid: str, status: str, error: str | None = None, last_seq: int | None = None) -> bool:
    """终态守卫版收尾：仅当 run 仍处 running 时写入，返回是否落库。

    供 agent 外层异常兜底使用——worker 分支已落的终态不被覆盖：原始 error 文案
    不被内部异常文案顶掉、completed 不被翻成 error（error 事件照发，DB 真值不动）。"""
    conn = _conn()
    try:
        if last_seq is not None:
            cur = conn.execute(
                "UPDATE runs SET status=?, error=?, last_seq=? WHERE id=? AND status='running'",
                (status, error, last_seq, rid),
            )
        else:
            cur = conn.execute(
                "UPDATE runs SET status=?, error=? WHERE id=? AND status='running'",
                (status, error, rid),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_run(rid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, conversation_id, status, error, created_at, interrupt, last_seq, pause_msg_id, thinking, model"
            " FROM runs WHERE id=?",
            (rid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def interrupt_run(rid: str, requests: list, last_seq: int, pause_msg_id: str | None = None) -> None:
    """HITL 暂停：置 waiting_input 并保存快照（前端恢复审批卡）与事件序号（续段续接）。
    pause_msg_id 记录暂停时落的半截消息——续跑段终止且无新产出时据此改写其
    「等待你的输入…」标记（retire_pause_marker），避免对话停在已失效的等待态。"""
    conn = _conn()
    try:
        conn.execute(
            "UPDATE runs SET status='waiting_input', interrupt=?, last_seq=?, pause_msg_id=? WHERE id=?",
            (json.dumps(requests, ensure_ascii=False), last_seq, pause_msg_id, rid),
        )
    finally:
        conn.close()


def retire_pause_marker(msg_id: str | None) -> bool:
    """把暂停落库消息结尾的「（等待你的输入…）」改写为「（任务中断）」。

    场景：run 暂停后续跑、又在未产出任何新消息时终止（取消/出错）——此时该消息
    是对话最后一句，却宣称在等输入，与已终止的 run 矛盾。只做末尾精确匹配，
    不动历史中段的暂停消息（那些在时序上真实等待过）。裸标记消息（无正文、
    仅标记，提问前零旁白的暂停，2026-08-30 起无条件落库）同样改写。"""
    if not msg_id:
        return False
    suffix = "\n\n（等待你的输入…）"
    conn = _conn()
    try:
        row = conn.execute("SELECT content FROM messages WHERE id=?", (msg_id,)).fetchone()
        if row is None:
            return False
        content = row["content"]
        new_content: str | None = None
        if content.endswith(suffix):
            new_content = content[: -len(suffix)] + "\n\n（任务中断）"
        elif content == "（等待你的输入…）":
            new_content = "（任务中断）"
        if new_content is None:
            return False
        conn.execute("UPDATE messages SET content=? WHERE id=?", (new_content, msg_id))
        return True
    finally:
        conn.close()


def resume_run(rid: str) -> bool:
    """用户已裁决：转回 running，快照清空（last_seq 保留，续段事件序号续接用）。

    条件 UPDATE（WHERE status='waiting_input'）+ rowcount 判定：幂等抢占点，
    并发重复 resume 只有一个能成功（当前单进程事件循环下 handler 原子不可达，
    属一行加固——handler 里未来插入任何 await 前先把守卫做实）。"""
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE runs SET status='running', interrupt=NULL WHERE id=? AND status='waiting_input'",
            (rid,),
        )
        return cur.rowcount > 0
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


def list_active_runs() -> list[dict]:
    """全部占用中的 run（running/waiting_input）：GET /runs/active 的数据源，
    侧栏跨会话「输出中」指示与任务级「等待确认」聚合用。会话级 409 守卫保证
    每会话至多一条占用。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, conversation_id, status FROM runs"
            " WHERE status IN ('running','waiting_input') ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


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


# ---------- 知识库（kb_items + kb_segments FTS5） ----------

_KB_ITEM_COLS = (
    "id, file_name, file_hash, title, ext, doc_type, "
    "parse_status, extract_status, review_status, "
    "suggested_metadata, business_metadata, error, created_at, updated_at"
)


def kb_insert_item(file_name: str, file_hash: str, title: str, ext: str) -> dict:
    kid = f"kb_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO kb_items(id, file_name, file_hash, title, ext, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (kid, file_name, file_hash, title, ext, now, now),
        )
    finally:
        conn.close()
    return kb_get_item(kid) or {}


def kb_get_item(kid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            f"SELECT {_KB_ITEM_COLS} FROM kb_items WHERE id=?", (kid,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def kb_get_item_by_hash(file_hash: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            f"SELECT {_KB_ITEM_COLS} FROM kb_items WHERE file_hash=?", (file_hash,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def kb_list_items(
    review_status: str | None = None,
    doc_type: str | None = None,
    q: str | None = None,
) -> list[dict]:
    """知识库条目列表：待确认置顶、其余按创建时间倒序；q 对 file_name/title ILIKE。"""
    sql = f"SELECT {_KB_ITEM_COLS} FROM kb_items"
    where, args = [], []
    if review_status:
        where.append("review_status=?")
        args.append(review_status)
    if doc_type:
        where.append("doc_type=?")
        args.append(doc_type)
    if q:
        where.append("(file_name LIKE ? OR title LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE review_status WHEN 'pending_review' THEN 0 ELSE 1 END, created_at DESC"
    conn = _conn()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def kb_update_item(kid: str, **fields) -> None:
    """更新 kb_items 指定列（仅白名单列）+ updated_at。"""
    allowed = {
        "title", "doc_type", "parse_status", "extract_status", "review_status",
        "suggested_metadata", "business_metadata", "error",
    }
    keys = [
        k for k in fields
        if k in allowed and (fields[k] is not None or k == "error")  # error 允许置空清除
    ]
    if not keys:
        return
    sets = ", ".join(f"{k}=?" for k in keys)
    args = [fields[k] for k in keys] + [_now(), kid]
    conn = _conn()
    try:
        conn.execute(f"UPDATE kb_items SET {sets}, updated_at=? WHERE id=?", args)
    finally:
        conn.close()


def kb_delete_item(kid: str) -> None:
    conn = _conn()
    try:
        # 单事务：两条 DELETE 之间不留「条目没了段还在」的可见窗口
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM kb_items WHERE id=?", (kid,))
            conn.execute("DELETE FROM kb_segments WHERE item_id=?", (kid,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def kb_count_pending() -> int:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM kb_items WHERE review_status='pending_review'"
        ).fetchone()
    finally:
        conn.close()
    return int(row["n"]) if row else 0


def kb_replace_segments(item_id: str, segments: list[dict]) -> None:
    """重建某条目的全部检索段（先 DELETE 后 INSERT，幂等）。

    DELETE+INSERT 必须在同一事务：连接是 autocommit（isolation_level=None），
    两条语句各自提交会留出「段已清空、新版未入」的可见窗口——确认表单后
    立即检索的调用方恰好落进窗口就空手而归（test_confirm_metadata_flow
    偶发失败的根因；与入库管线/确认路径的线程并发无关也要保证）。
    """
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM kb_segments WHERE item_id=?", (item_id,))
            conn.executemany(
                "INSERT INTO kb_segments(body, item_id, section_path, line_start, line_end, page_start)"
                " VALUES(?,?,?,?,?,?)",
                [
                    (
                        s["body"], item_id, s.get("section_path"),
                        s.get("line_start"), s.get("line_end"), s.get("page_start"),
                    )
                    for s in segments
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def kb_search_segments(match_expr: str, limit: int = 8) -> list[dict]:
    """FTS5 检索（bm25 排序），返回原始文本（body 是分词后文本，调用方展示用原文摘要）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT item_id, section_path, line_start, line_end, page_start, body,"
            " bm25(kb_segments) AS rank"
            " FROM kb_segments WHERE kb_segments MATCH ?"
            " ORDER BY rank LIMIT ?",
            (match_expr, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def recover_stale_kb() -> int:
    """启动对账：sidecar 被杀时残留的 parsing/running 条目置 failed（可手动重触发）。"""
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE kb_items SET parse_status='failed',"
            " error=COALESCE(error, 'sidecar 中断，请重新触发'), updated_at=?"
            " WHERE parse_status IN ('pending','parsing')",
            (_now(),),
        )
        n1 = cur.rowcount
        cur = conn.execute(
            "UPDATE kb_items SET extract_status='failed', updated_at=?"
            " WHERE extract_status='running'",
            (_now(),),
        )
        n2 = cur.rowcount
    finally:
        conn.close()
    return n1 + n2
