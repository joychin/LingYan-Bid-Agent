"""SQLite 持久化（标准库 sqlite3，WAL 模式）。

tasks / conversations / messages / runs / artifact_index。与 DeepAgents 的
checkpointer（data/agent.db）分离，避免锁竞争。所有写操作在各自连接上执行，
连接默认 autocommit（isolation_level=None）。

任务层（2026-08-31 归属重构；2026-09-04 两态移除）：会话归属任务
（conversations.task_id）；产物归任务单一真源、单一当前版本，conversation_id
仅 provenance（记录产出会话），不再有正式稿/过程稿双层。

artifact_index 是类型化 Artifact 的可重建索引 + 运行态（content_seq/emitted）；
权威身份在每个 Artifact 包的 meta.json（见 artifact_store.py），本表丢失后
可由 meta 重建（rebuild_artifact_index）。
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from .config import app_db_path

logger = logging.getLogger(__name__)

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
  model TEXT NOT NULL DEFAULT '',
  token_usage TEXT,
  error_code TEXT);
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
  emitted INTEGER NOT NULL DEFAULT 0);
-- run 执行过程快照（工具步骤树 + todos + 主 agent 思考流）：run 结束落一份，
-- message_id 关联 assistant 消息（终态消息：最终回复/暂停/中断半截，GET /messages
-- 据此挂载），历史会话/刷新后执行过程与「深度思考」仍可见
CREATE TABLE IF NOT EXISTS run_traces(
  run_id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  message_id TEXT,
  tools TEXT NOT NULL,
  todos TEXT NOT NULL,
  duration_ms INTEGER,
  reasoning TEXT NOT NULL DEFAULT '',
  files TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL);
-- 每次模型调用的用量明细（2026-09-08）：run 级聚合在 runs.token_usage，本表
-- per-turn 落行、scope 区分主线程/子代理，供「token 都花在哪」的归因查询
CREATE TABLE IF NOT EXISTS run_turn_usage(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'main',
  input INTEGER NOT NULL DEFAULT 0,
  cached INTEGER NOT NULL DEFAULT 0,
  output INTEGER NOT NULL DEFAULT 0,
  reasoning INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL);
-- 知识库条目（v3 内容角色模型，2026-09-03 全量重建：一个上传文件一条；
-- suggested=AI 建议（doc_type/内容说明 statement/时间字段）、business=确认后真值，
-- 两列之隔即审核边界——确认把 suggested 拷入 business，LLM 永不覆盖 business；
-- progress=进行中工序的进度文本（"素材拆分中 3/5 批"/"图片识别中 12/60 页"），NULL=无）
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
  check_result TEXT,
  progress TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
-- 知识库检索切段（FTS5）：按 outline 节点切段一段一行，body 存 jieba 预分词文本
-- （写入/查询两侧同源分词，unicode61 切英文数字 token；索引可从 kb_items+磁盘 md 重建）；
-- material_id 非空 = 参考文档桶的素材段（素材块复用同一张表、检索一条路径）
CREATE VIRTUAL TABLE IF NOT EXISTS kb_segments USING fts5(
  body, item_id UNINDEXED, section_path UNINDEXED, material_id UNINDEXED,
  line_start UNINDEXED, line_end UNINDEXED, page_start UNINDEXED);
-- 写作素材库（2026-09-04 v2 手工构建，与知识库彻底分离）：素材文件 + 用户勾选建的块
-- （块=多行号区间集合+用户备注；真值在 materials/parse/<stem>/blocks.json，本表可重建；
-- 块检索段复用 kb_segments，item_id=素材文件 id mt_ 前缀与知识库天然隔离）
CREATE TABLE IF NOT EXISTS mt_files(
  id TEXT PRIMARY KEY,
  file_name TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  parse_status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mt_blocks(
  id TEXT PRIMARY KEY,
  file_id TEXT NOT NULL,
  title TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  ranges TEXT NOT NULL,
  chars INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  use_count INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT);
"""

# 索引与建表分两步：旧库先建表→探测补列→再建索引（索引引用新列，顺序不能反）
_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_run_traces_message ON run_traces(message_id);
CREATE INDEX IF NOT EXISTS idx_run_turn_usage_run ON run_turn_usage(run_id);
CREATE INDEX IF NOT EXISTS idx_artifact_index_scope
  ON artifact_index(task_id, conversation_id, kind, schema_id, schema_version);
-- run 边界 pending_emit（WHERE last_run_id=? AND emitted=0）：每次 run 收尾一次
CREATE INDEX IF NOT EXISTS idx_artifact_index_last_run
  ON artifact_index(last_run_id, emitted);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_items_hash ON kb_items(file_hash);
CREATE INDEX IF NOT EXISTS idx_kb_items_review ON kb_items(review_status);
CREATE INDEX IF NOT EXISTS idx_mt_blocks_file ON mt_blocks(file_id);
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
    """删任务行及其全部会话数据与产物索引行（产物行带所属 task_id，随任务一并清理）。
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
    """删除会话及其消息/run 记录。文件归任务（2026-08-31）：产物索引行保留
    （conversation_id 仅是 provenance），磁盘产物也不随会话删除。
    表之间无外键约束（PRAGMA foreign_keys=ON 对未声明 FKs 不生效），手动清理子表；
    单事务防进程中止留半级联孤儿行。
    """
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM runs WHERE conversation_id=?", (cid,))
            conn.execute("DELETE FROM run_traces WHERE conversation_id=?", (cid,))
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
    files: list | None = None,
) -> None:
    """run 结束时落执行过程快照（幂等：同 run 重写）。reasoning = 主 agent 思考流整段。
    files = 本轮 work/ 变更清单（[{path, op}]，run_files 起止 diff，None 存空）。"""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO run_traces(run_id, conversation_id, message_id, tools, todos, duration_ms, reasoning, files, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                cid,
                message_id,
                json.dumps(tools, ensure_ascii=False),
                json.dumps(todos, ensure_ascii=False),
                duration_ms,
                reasoning,
                json.dumps(files or [], ensure_ascii=False),
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
            "SELECT run_id, message_id, tools, todos, duration_ms, reasoning, files FROM run_traces WHERE run_id=?",
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
            "files": json.loads(row["files"] or "[]"),
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
            f"SELECT message_id, tools, todos, duration_ms, reasoning, files FROM run_traces WHERE message_id IN ({ph})",
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
                "files": json.loads(r["files"] or "[]"),
            }
        except ValueError:
            continue  # 防御：快照损坏不阻断消息列表
    return out


def get_message(message_id: str) -> dict | None:
    """单条消息行（cid 归属校验用）。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, conversation_id, role FROM messages WHERE id=?", (message_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_trace_by_message(message_id: str) -> dict | None:
    """单条消息的完整执行过程快照（按需端点数据源，2026-09-08 messages 瘦身）。"""
    conn = _conn()
    try:
        r = conn.execute(
            "SELECT tools, todos, duration_ms, reasoning, files FROM run_traces WHERE message_id=?",
            (message_id,),
        ).fetchone()
    finally:
        conn.close()
    if r is None:
        return None
    try:
        return {
            "tools": json.loads(r["tools"]),
            "todos": json.loads(r["todos"]),
            "durationMs": r["duration_ms"],
            "reasoning": r["reasoning"] or "",
            "files": json.loads(r["files"] or "[]"),
        }
    except ValueError:
        return None  # 快照损坏：按无过程处理（端点 404）


def get_message_trace_summaries(message_ids: list[str]) -> dict[str, dict]:
    """消息过程摘要（步数/是否含暂停步 + durationMs/files）：折叠头所需的轻量字段。

    步数与 paused 用 SQLite JSON 函数在库内走树（C 层），不把 MB 级 tools JSON
    拉回 Python 解析——messages 瘦身（2026-09-08）后这是列表端点唯一要碰
    run_traces 的地方，标书会话实测 11.4MB 全量解析不可接受。
    """
    if not message_ids:
        return {}
    ph = ",".join("?" * len(message_ids))
    conn = _conn()
    try:
        rows = conn.execute(
            f"""
            SELECT message_id, duration_ms, files,
                   json_array_length(tools) AS steps,
                   EXISTS(SELECT 1 FROM json_tree(tools) WHERE key='status' AND value='paused') AS paused
            FROM run_traces WHERE message_id IN ({ph})
            """,
            message_ids,
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict] = {}
    for r in rows:
        try:
            steps = int(r["steps"] or 0)
        except (TypeError, ValueError):
            steps = 0
        try:
            files = json.loads(r["files"] or "[]")
        except ValueError:
            files = []
        out[r["message_id"]] = {
            "steps": steps,
            "paused": bool(r["paused"]),
            "durationMs": r["duration_ms"],
            "files": files,
        }
    return out


def insert_run_turn_usage(rid: str, scope: str, usage: dict[str, int]) -> None:
    """单次模型调用的用量明细一行（token_usage.record_usage 调；异常由调用方吞）。"""
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO run_turn_usage(run_id, scope, input, cached, output, reasoning, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                rid,
                scope,
                usage.get("input", 0),
                usage.get("cached", 0),
                usage.get("output", 0),
                usage.get("reasoning", 0),
                _now(),
            ),
        )
    finally:
        conn.close()


def list_run_turn_usage(rid: str) -> list[dict]:
    """按 run 取全部 per-turn 用量明细（id 升序=调用顺序；归因/测试用）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, scope, input, cached, output, reasoning, created_at"
            " FROM run_turn_usage WHERE run_id=? ORDER BY id",
            (rid,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


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


def finish_run(
    rid: str, status: str, error: str | None = None, last_seq: int | None = None,
    token_usage_json: str | None = None, error_code: str | None = None,
) -> None:
    """run 收尾。last_seq 回写终态事件序号（此前只有 interrupt_run 写过——续跑完成后
    runs.last_seq 永远停在暂停值，对账/排查拿到的是错数）。token_usage_json 是本 run
    的模型用量快照（input/output/cached/reasoning，agent 层 take 出来的 JSON 文本，
    None=保留旧值——HITL 分段落库时首段已写，续段无新增时不覆盖）。error_code 是
    错误定性（cancelled/llm_unavailable/llm_auth/internal，2026-09-08 契约 additive；
    completed 时随 error 一并写 NULL）。"""
    sets = ["status=?", "error=?", "error_code=?"]
    args: list = [status, error, error_code]
    if last_seq is not None:
        sets.append("last_seq=?")
        args.append(last_seq)
    if token_usage_json is not None:
        sets.append("token_usage=?")
        args.append(token_usage_json)
    args.append(rid)
    conn = _conn()
    try:
        conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", args)
    finally:
        conn.close()


def finish_run_if_running(
    rid: str, status: str, error: str | None = None, last_seq: int | None = None,
    token_usage_json: str | None = None, error_code: str | None = None,
) -> bool:
    """终态守卫版收尾：仅当 run 仍处 running 时写入，返回是否落库。

    供 agent 外层异常兜底使用——worker 分支已落的终态不被覆盖：原始 error 文案
    不被内部异常文案顶掉、completed 不被翻成 error（error 事件照发，DB 真值不动）。"""
    sets = ["status=?", "error=?", "error_code=?"]
    args: list = [status, error, error_code]
    if last_seq is not None:
        sets.append("last_seq=?")
        args.append(last_seq)
    if token_usage_json is not None:
        sets.append("token_usage=?")
        args.append(token_usage_json)
    args.append(rid)
    conn = _conn()
    try:
        cur = conn.execute(
            f"UPDATE runs SET {', '.join(sets)} WHERE id=? AND status='running'", args
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_run(rid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, conversation_id, status, error, created_at, interrupt, last_seq, pause_msg_id, thinking, model, token_usage, error_code"
            " FROM runs WHERE id=?",
            (rid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def interrupt_run(
    rid: str, requests: list, last_seq: int, pause_msg_id: str | None = None,
    token_usage_json: str | None = None,
) -> None:
    """HITL 暂停：置 waiting_input 并保存快照（前端恢复审批卡）与事件序号（续段续接）。
    pause_msg_id 记录暂停时落的半截消息——续跑段终止且无新产出时据此改写其
    「等待你的输入…」标记（retire_pause_marker），避免对话停在已失效的等待态。
    token_usage_json 落半程用量（续段累计时 agent 层把首段值加回再落）。"""
    conn = _conn()
    try:
        if token_usage_json is not None:
            conn.execute(
                "UPDATE runs SET status='waiting_input', interrupt=?, last_seq=?, pause_msg_id=?, token_usage=? WHERE id=?",
                (json.dumps(requests, ensure_ascii=False), last_seq, pause_msg_id, token_usage_json, rid),
            )
        else:
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


def cancel_waiting_run(rid: str, error: str, seq: int | None = None) -> bool:
    """用户放弃等待中的 run（waiting_input 逃生口，2026-09-08）：落 cancelled 终态。

    与 resume_run 同款条件 UPDATE 抢占——并发 resume/cancel 只有一个能赢，
    输家回 409。此时无活 worker（暂停存活于 checkpoint），不置取消事件、
    不清 checkpoint（与 running 取消同口径，下一 run 由 langgraph 自愈悬空
    tool_calls）；interrupt 快照清空防残留，last_seq 可随终态事件回写。"""
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE runs SET status='error', error=?, error_code='cancelled', interrupt=NULL, "
            "last_seq=COALESCE(?, last_seq) WHERE id=? AND status='waiting_input'",
            (error, seq, rid),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def recover_stale_runs() -> int:
    """sidecar 崩溃/被杀重启后，把残留的 running run 标记为 error。

    否则该会话会一直命中 409「已有进行中的任务」，永久无法再发消息。
    waiting_input 不翻：interrupt 存活于 agent.db checkpoint，重启后用户仍可裁决续跑。
    error_code='interrupted'（2026-09-08 契约 additive）：前端中性呈现，不与真实错误
    共用红色（同 cancelled 视觉语义——环境重启不是模型的错也不是用户的错）。
    """
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE runs SET status='error', error=?, error_code='interrupted' WHERE status='running'",
            ("应用服务重启，任务被中断",),
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


# 终态断点续跑（2026-09-12）可续的错误定性：服务重启中断 / 模型服务不稳重试耗尽 /
# Key 失效或欠费（用户修好配置回来续）。cancelled 不提供——尊重用户停止意图；
# internal 不提供——程序自身错误，续跑大概率原地再错（重新执行走新 run 有 PatchToolCalls 自愈）。
RESUMABLE_ERROR_CODES = ("interrupted", "llm_unavailable", "llm_auth")


def continue_run(rid: str) -> bool:
    """终态断点续跑的抢占翻转（error → running）：仅 error 终态且 error_code 在
    RESUMABLE_ERROR_CODES 内生效。条件 UPDATE 与并发双击互斥（一对一输，输家 409，
    与 resume_run 同款语义）；last_seq 保留（续段事件序号接续，前端按 run_id 去重）；
    error/error_code 清空（下次终态再写）。"""
    codes = ",".join("?" for _ in RESUMABLE_ERROR_CODES)
    conn = _conn()
    try:
        cur = conn.execute(
            f"UPDATE runs SET status='running', error=NULL, error_code=NULL "
            f"WHERE id=? AND status='error' AND error_code IN ({codes})",
            (rid, *RESUMABLE_ERROR_CODES),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


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
            "SELECT id, conversation_id, status, error, created_at, interrupt, last_seq, token_usage, error_code"
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
    "emitted"
)

_NUM_INDEX_COLS = len(_INDEX_COLS.split(","))


def upsert_artifact_index(rec: dict) -> None:
    """写入/覆盖一行索引（发布与修订共用）。新发布的行 emitted=0，待 run 边界发事件。"""
    conn = _conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO artifact_index({_INDEX_COLS}) "
            f"VALUES ({','.join('?' * _NUM_INDEX_COLS)})",
            (
                rec["artifact_id"], rec.get("task_id"), rec.get("conversation_id"), rec["kind"],
                rec["schema_id"], rec["schema_version"], rec["cardinality"], rec["display_name"],
                rec["content_path"], rec.get("content_seq", 1), rec["updated_at"],
                rec.get("last_run_id"), rec.get("last_thread_id"),
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
    """按归属找同契约现有产物（task-single upsert 用）。

    文件归任务：同契约在任务内唯一（task-single），conversation_id 仅作来源筛选
    （可选），不再作为作用域判别——process 稿与正式稿已合并为单一产物。
    """
    if task_id is None:
        return None
    where, args = "task_id=?", [task_id]
    if conversation_id is not None:
        where += " AND conversation_id=?"
        args.append(conversation_id)
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
    """产物索引列表。任务过滤返回任务全部产物（不再按 conversation_id IS NULL 区分）；
    会话过滤（可选）按 provenance 筛出该会话产出的产物；无参 = 全部。
    """
    where, args = "", []
    if task_id is not None:
        where, args = "WHERE task_id=?", [task_id]
    if conversation_id is not None:
        where += (" AND " if where else "WHERE ") + "conversation_id=?"
        args.append(conversation_id)
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
    """用磁盘 meta.json 与库内现存行做同步（meta 是身份权威，索引可重建）。

    启动时调用。2026-09-12 起不再「清空重插 + 运行态复位」：幸存行（磁盘包还在）
    保留五列运行态 content_seq/updated_at/last_run_id/last_thread_id/emitted——
    此前 content_seq 恒复位 1（目录编辑器拿 content_seq 当版本号做外部更新探测，
    重启即误报「外部已修改」），last_run_id 回卷到 meta.source 的创建 run（meta
    从不在重发布时回写 source，重启后聊天产物卡跳回首次发布回合直到下次发布）。
    身份字段（display_name/content_path/cardinality 等）仍以 meta 为准，手改
    meta.json 会被拾起；磁盘新增的包按现状默认插入；库有而磁盘无的行删除。
    全量 DB 丢失时无幸存行可保留，回落复位语义（seq=1、emitted=1、last_run
    取 meta.source）。旧包 meta.json 残留的 state/confirmed_at 键（两态时代
    化石）被显式字段映射天然忽略。content_path_of: meta -> content_path 的
    求值函数（注入避免依赖 store）。返回同步后的行数。
    """
    cols = _INDEX_COLS.split(", ")
    conn = _conn()
    try:
        existing = {
            r["artifact_id"]: dict(r)
            for r in conn.execute(f"SELECT {_INDEX_COLS} FROM artifact_index")
        }
        conn.execute("DELETE FROM artifact_index")
        rows = []
        for m in manifests:
            schema = m.get("schema", {})
            source = m.get("source") or {}
            rec = {
                "artifact_id": m["artifact_id"], "task_id": m.get("task_id"),
                "conversation_id": m.get("conversation_id"), "kind": m["kind"],
                "schema_id": schema.get("id", ""), "schema_version": schema.get("version", 1),
                "cardinality": m.get("cardinality", "task-single"),
                "display_name": m.get("display_name", ""),
                "content_path": content_path_of(m),
                "content_seq": 1, "updated_at": m.get("created_at", _now()),
                "last_run_id": source.get("run_id"), "last_thread_id": source.get("thread_id"),
                "emitted": 1,
            }
            prev = existing.pop(rec["artifact_id"], None)
            if prev is not None:
                for col in ("content_seq", "updated_at", "last_run_id", "last_thread_id", "emitted"):
                    rec[col] = prev[col]
            rows.append(tuple(rec[c] for c in cols))
        conn.executemany(
            f"INSERT INTO artifact_index({_INDEX_COLS}) "
            f"VALUES ({','.join('?' * _NUM_INDEX_COLS)})",
            rows,
        )
    finally:
        conn.close()
    return len(rows)


# ---------- 知识库（kb_items + kb_segments FTS5） ----------

_KB_ITEM_COLS = (
    "id, file_name, file_hash, title, ext, doc_type, "
    "parse_status, extract_status, review_status, "
    "suggested_metadata, business_metadata, check_result, progress, error, created_at, updated_at"
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
        "suggested_metadata", "business_metadata", "check_result", "progress", "error",
    }
    keys = [
        k for k in fields
        # business/check_result 可显式置空（自动核对降级清 business 副本）
        if k in allowed and (fields[k] is not None or k in ("error", "progress", "business_metadata", "check_result"))
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
        # 单事务：条目/段之间不留「条目没了子行还在」的可见窗口
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

    段 dict 可带 material_id（素材段；普通段缺省 None）。
    """
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM kb_segments WHERE item_id=?", (item_id,))
            conn.executemany(
                "INSERT INTO kb_segments(body, item_id, section_path, material_id, line_start, line_end, page_start)"
                " VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        s["body"], item_id, s.get("section_path"), s.get("material_id"),
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


# ---------- 写作素材库（mt_files + mt_blocks；块检索段复用 kb_segments） ----------

_MT_FILE_COLS = "id, file_name, file_hash, parse_status, error, created_at, updated_at"


def mt_insert_file(file_name: str, file_hash: str) -> dict:
    fid = f"mt_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO mt_files(id, file_name, file_hash, created_at, updated_at)"
            " VALUES(?,?,?,?,?)",
            (fid, file_name, file_hash, now, now),
        )
    finally:
        conn.close()
    return mt_get_file(fid) or {}


def mt_get_file(fid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(f"SELECT {_MT_FILE_COLS} FROM mt_files WHERE id=?", (fid,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def mt_get_file_by_hash(file_hash: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(f"SELECT {_MT_FILE_COLS} FROM mt_files WHERE file_hash=?", (file_hash,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def mt_list_files() -> list[dict]:
    """素材文件列表（按创建时间倒序）。"""
    conn = _conn()
    try:
        rows = conn.execute(f"SELECT {_MT_FILE_COLS} FROM mt_files ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def mt_update_file(fid: str, **fields) -> None:
    """更新 mt_files 指定列（仅白名单列）+ updated_at。"""
    allowed = {"parse_status", "error", "file_name"}
    keys = [
        k for k in fields
        if k in allowed and (fields[k] is not None or k == "error")
    ]
    if not keys:
        return
    sets = ", ".join(f"{k}=?" for k in keys)
    args = [fields[k] for k in keys] + [_now(), fid]
    conn = _conn()
    try:
        conn.execute(f"UPDATE mt_files SET {sets}, updated_at=? WHERE id=?", args)
    finally:
        conn.close()


def mt_delete_file(fid: str) -> None:
    """删素材文件连带块与检索段（单事务不留孤儿）。"""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM mt_files WHERE id=?", (fid,))
            conn.execute("DELETE FROM mt_blocks WHERE file_id=?", (fid,))
            conn.execute("DELETE FROM kb_segments WHERE item_id=?", (fid,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def mt_replace_blocks(file_id: str, rows: list[dict]) -> None:
    """重建某素材文件的块行（先 DELETE 后 INSERT，幂等；与知识库段重建同款事务纪律）。

    rows dict：{id, title, note, ranges(JSON 字符串 [[s,e],…]), chars}。
    块 id 在 blocks.json 生命周期内稳定——重建时按 id 回填 created_at/use_count/
    last_used_at（引用打点不随同步丢失，created_at 也不再被刷成 now）。
    """
    now = _now()
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            keep: dict[str, tuple[str, int, str | None]] = {
                r["id"]: (r["created_at"], r["use_count"], r["last_used_at"])
                for r in conn.execute(
                    "SELECT id, created_at, use_count, last_used_at FROM mt_blocks WHERE file_id=?",
                    (file_id,),
                ).fetchall()
            }
            conn.execute("DELETE FROM mt_blocks WHERE file_id=?", (file_id,))
            conn.executemany(
                "INSERT INTO mt_blocks(id, file_id, title, note, ranges, chars, created_at,"
                " use_count, last_used_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (
                        r["id"], file_id, r["title"], r.get("note") or "",
                        r["ranges"], r.get("chars") or 0,
                        keep.get(r["id"], (now, 0, None))[0],
                        keep.get(r["id"], (now, 0, None))[1],
                        keep.get(r["id"], (now, 0, None))[2],
                    )
                    for r in rows
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def mt_touch_blocks(bids: list[str]) -> None:
    """素材块 AI 引用打点（use_count+1 / last_used_at=now；容错不抛）。"""
    ids = [b for b in bids if b]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn = _conn()
    try:
        conn.execute(
            f"UPDATE mt_blocks SET use_count=use_count+1, last_used_at=? WHERE id IN ({placeholders})",
            [_now(), *ids],
        )
    except Exception:
        logger.exception("素材块引用打点失败：%s", ids)
    finally:
        conn.close()


def mt_list_blocks(file_id: str | None = None) -> list[dict]:
    """块列表（可按文件过滤；ranges 反序列化为 [[s,e],…]；按创建时间倒序）。"""
    sql = (
        "SELECT id, file_id, title, note, ranges, chars, created_at, use_count, last_used_at"
        " FROM mt_blocks"
    )
    args: tuple = ()
    if file_id:
        sql += " WHERE file_id=?"
        args = (file_id,)
    sql += " ORDER BY created_at DESC"
    conn = _conn()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["ranges"] = json.loads(d["ranges"]) if d["ranges"] else []
        except ValueError:
            d["ranges"] = []
        out.append(d)
    return out


def mt_get_block(bid: str) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, file_id, title, note, ranges, chars, created_at, use_count, last_used_at"
            " FROM mt_blocks WHERE id=?",
            (bid,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["ranges"] = json.loads(d["ranges"]) if d["ranges"] else []
    except ValueError:
        d["ranges"] = []
    return d


def mt_count_blocks() -> int:
    conn = _conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM mt_blocks").fetchone()
    finally:
        conn.close()
    return int(row["n"]) if row else 0


def mt_block_counts() -> dict[str, int]:
    """file_id → 块数（文件列表徽标，一次聚合查询）。"""
    conn = _conn()
    try:
        rows = conn.execute("SELECT file_id, COUNT(*) AS n FROM mt_blocks GROUP BY file_id").fetchall()
    finally:
        conn.close()
    return {r["file_id"]: int(r["n"]) for r in rows}


def kb_search_segments(match_expr: str, limit: int = 8) -> list[dict]:
    """FTS5 检索（bm25 排序），返回原始文本（body 是分词后文本，调用方展示用原文摘要）。"""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT item_id, section_path, material_id, line_start, line_end, page_start, body,"
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
            "UPDATE kb_items SET parse_status='failed', progress=NULL,"
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


def recover_stale_mt() -> int:
    """启动对账：素材文件残留 pending/parsing 置 failed（失败行有重试入口）。"""
    conn = _conn()
    try:
        cur = conn.execute(
            "UPDATE mt_files SET parse_status='failed',"
            " error=COALESCE(error, '解析中断，请重试'), updated_at=?"
            " WHERE parse_status IN ('pending','parsing')",
            (_now(),),
        )
        n = cur.rowcount
    finally:
        conn.close()
    return n
