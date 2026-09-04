"""SQLite 迁移（PRAGMA user_version 编号迁移，flyway/yoyo 同构的极简自制版）。

约定：
- 每个迁移 = (版本号, 函数)。函数只做 DDL 且幂等（升级事务中途崩溃重启后重跑无害）；
  事务由 runner 统一包裹，user_version 随同一事务写入——DDL 与版本号原子生效。
- db._SCHEMA 仍是**新库的权威全量**（CREATE IF NOT EXISTS）；迁移只负责把旧库补齐。
  此后 schema 变更 = _SCHEMA 同步改 + 这里追加一个迁移 + LATEST 递增，不再散探测。
- 版本 1–9 由原 db.init_db 的散点逻辑（8 列探测补齐 + runs 整表重建）原样转正，
  语义不变；user_version==0 且有表 = 无版本号的存量旧库，跑全部迁移后盖版本号。
"""

import sqlite3

LATEST = 21


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(ddl)


def _drop_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    """幂等删列（迁移 19 首用；SQLite DROP COLUMN 需 3.35+，uv 管的 Python 3.12
    自带 sqlite 满足）。旧库有该列才执行，新库（_SCHEMA 已无此列）跳过。"""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in cols:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def _rebuild_runs_waiting_input(conn: sqlite3.Connection) -> None:
    """runs 表 CHECK 增加 'waiting_input'（HITL）——SQLite 不能 ALTER CHECK，
    探测旧建表 SQL 后整表重建（CREATE new + copy + rename）。数据量小，秒级完成。
    事务由 runner 包裹；开头清掉上次迁移中途崩溃可能残留的 runs_migrate。"""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
    if row is None or "waiting_input" in row["sql"]:
        return
    conn.execute("DROP TABLE IF EXISTS runs_migrate")
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


# 迁移清单（编号即顺序；新增只追加，不改动历史条目）
MIGRATIONS: list[tuple[int, object]] = [
    (1, _rebuild_runs_waiting_input),
    (2, lambda c: _add_column(c, "runs", "interrupt", "ALTER TABLE runs ADD COLUMN interrupt TEXT")),
    (3, lambda c: _add_column(c, "runs", "last_seq", "ALTER TABLE runs ADD COLUMN last_seq INTEGER NOT NULL DEFAULT 0")),
    (4, lambda c: _add_column(c, "runs", "pause_msg_id", "ALTER TABLE runs ADD COLUMN pause_msg_id TEXT")),
    (5, lambda c: _add_column(c, "run_traces", "duration_ms", "ALTER TABLE run_traces ADD COLUMN duration_ms INTEGER")),
    (6, lambda c: _add_column(c, "run_traces", "reasoning", "ALTER TABLE run_traces ADD COLUMN reasoning TEXT NOT NULL DEFAULT ''")),
    (7, lambda c: _add_column(c, "conversations", "task_id", "ALTER TABLE conversations ADD COLUMN task_id TEXT")),
    (8, lambda c: _add_column(c, "artifact_index", "conversation_id", "ALTER TABLE artifact_index ADD COLUMN conversation_id TEXT")),
    (
        9,
        lambda c: _add_column(
            c, "artifact_index", "promotion_proposed",
            "ALTER TABLE artifact_index ADD COLUMN promotion_proposed INTEGER NOT NULL DEFAULT 0",
        ),
    ),
    (
        10,
        lambda c: _add_column(
            c, "runs", "thinking",
            "ALTER TABLE runs ADD COLUMN thinking TEXT NOT NULL DEFAULT ''",
        ),
    ),
    (
        11,
        lambda c: _add_column(
            c, "runs", "model",
            "ALTER TABLE runs ADD COLUMN model TEXT NOT NULL DEFAULT ''",
        ),
    ),
    (
        12,
        lambda c: c.execute(
            "CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        ),
    ),
    (
        13,
        lambda c: _add_column(c, "messages", "run_id", "ALTER TABLE messages ADD COLUMN run_id TEXT"),
    ),
    (
        14,
        lambda c: _migrate_artifact_state(c),
    ),
    (
        15,
        lambda c: _add_column(
            c, "run_traces", "files",
            "ALTER TABLE run_traces ADD COLUMN files TEXT NOT NULL DEFAULT '[]'",
        ),
    ),
    (
        16,
        lambda c: _add_column(
            c, "kb_items", "bucket",
            "ALTER TABLE kb_items ADD COLUMN bucket TEXT NOT NULL DEFAULT 'company'",
        ),
    ),
    (
        17,
        lambda c: _migrate_kb_materials(c),
    ),
    (
        18,
        lambda c: _migrate_kb_v3_rebuild(c),
    ),
    (
        19,
        lambda c: _migrate_artifact_single_version(c),
    ),
    (
        20,
        lambda c: _migrate_kb_chapter_blocks(c),
    ),
    (
        21,
        lambda c: _migrate_materials_v2(c),
    ),
]


def _migrate_materials_v2(conn: sqlite3.Connection) -> None:
    """写作素材库 v2（2026-09-04）：与知识库彻底分离、用户手工构建。

    知识库章节块退役（kb_materials DROP——LLM 裁定链路整体删除，用户改在素材库
    目录树手动勾选建块）；新表 mt_files/mt_blocks（真值在 materials/parse/<stem>/
    blocks.json，本表可重建）。
    """
    conn.execute("DROP TABLE IF EXISTS kb_materials")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mt_files(
          id TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_hash TEXT NOT NULL,
          parse_status TEXT NOT NULL DEFAULT 'pending', error TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mt_blocks(
          id TEXT PRIMARY KEY, file_id TEXT NOT NULL, title TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '', ranges TEXT NOT NULL,
          chars INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"""
    )


def _migrate_kb_chapter_blocks(conn: sqlite3.Connection) -> None:
    """章节块重构（2026-09-04）：素材=章节块（删 kind/usage/topics/image_path/page，
    加 level/chars/excluded），kb_materials DROP 重建。

    用户明令旧数据可清（开发期）：旧素材行整体作废，重传/重新识别后按新模型重建；
    磁盘 materials.json 旧结构由读侧容错忽略（read_materials 过滤无 id 块）。
    """
    conn.execute("DROP TABLE IF EXISTS kb_materials")
    conn.execute(
        """CREATE TABLE kb_materials(
          id TEXT PRIMARY KEY, item_id TEXT NOT NULL,
          title TEXT NOT NULL, section_path TEXT, level INTEGER,
          line_start INTEGER, line_end INTEGER, chars INTEGER,
          excluded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"""
    )


def _migrate_artifact_single_version(conn: sqlite3.Connection) -> None:
    """产物两态移除（2026-09-04）：单一当前版本，无草稿/已确认之分。

    删 artifact_index.state 列（迁移 14 加的）与 promotion_proposed 死列
    （迁移 9 加的，语义已被 14 整体替换）。历史迁移 14 保留在清单里——v13 旧库
    先加列再由本迁移删掉，冗余但幂等正确；包内 meta.json 残留的 state/confirmed_at
    键读侧显式字段映射，天然忽略。
    """
    _drop_column(conn, "artifact_index", "state")
    _drop_column(conn, "artifact_index", "promotion_proposed")


def _migrate_kb_v3_rebuild(conn: sqlite3.Connection) -> None:
    """知识库 v3 内容角色模型（2026-09-03）：不兼容旧两桶结构，整组 DROP 重建。

    用户明令旧数据可清（开发期）：kb_items 去 bucket 加 progress、kb_materials 加
    kind/image_path/page。重建后各表为空——磁盘 knowledge/ 下的旧解析产物成为孤儿
    （无条目引用，删除条目路径不再触达；重传同名文件会建新 stem 目录自然分流）。
    """
    conn.execute("DROP TABLE IF EXISTS kb_items")
    conn.execute("DROP TABLE IF EXISTS kb_segments")
    conn.execute("DROP TABLE IF EXISTS kb_materials")
    conn.execute(
        """CREATE TABLE kb_items(
          id TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_hash TEXT NOT NULL,
          title TEXT NOT NULL, ext TEXT NOT NULL, doc_type TEXT,
          parse_status TEXT NOT NULL DEFAULT 'pending',
          extract_status TEXT NOT NULL DEFAULT 'pending',
          review_status TEXT NOT NULL DEFAULT 'pending_review',
          suggested_metadata TEXT, business_metadata TEXT, progress TEXT, error TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
    )
    conn.execute(
        "CREATE VIRTUAL TABLE kb_segments USING fts5("
        "body, item_id UNINDEXED, section_path UNINDEXED, material_id UNINDEXED, "
        "line_start UNINDEXED, line_end UNINDEXED, page_start UNINDEXED)"
    )
    conn.execute(
        """CREATE TABLE kb_materials(
          id TEXT PRIMARY KEY, item_id TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'text', title TEXT NOT NULL, topics TEXT NOT NULL,
          usage TEXT, section_path TEXT, line_start INTEGER, line_end INTEGER,
          image_path TEXT, page INTEGER, created_at TEXT NOT NULL)"""
    )


def _migrate_artifact_state(conn: sqlite3.Connection) -> None:
    """产物模型重构（2026-08-31）：promotion_proposed 语义替换为 state（draft/confirmed）。

    - 加 state 列（默认 draft）；promotion_proposed 列保留为死列（SQLite DROP COLUMN 需
      3.35+，且历史迁移只 ADD 的约定下不主动删）。
    - 推断旧行状态：conversation_id IS NULL = 原「任务正式稿」→ confirmed；非空 = 原
      「会话过程稿」→ draft。开发期无真实数据则等价于清空重建，语义无损。
    """
    _add_column(conn, "artifact_index", "state", "ALTER TABLE artifact_index ADD COLUMN state TEXT NOT NULL DEFAULT 'draft'")
    conn.execute("UPDATE artifact_index SET state='confirmed' WHERE conversation_id IS NULL")


def _migrate_kb_materials(conn: sqlite3.Connection) -> None:
    """知识库素材层（2026-09-03 两桶模型）：kb_materials 新表 + kb_segments 加 material_id。

    FTS5 虚表不能 ALTER——探测旧建表 SQL 无 material_id 时 DROP 后按新结构重建。
    段是派生索引（可从 kb_items + 磁盘 md/materials.json 全量重建，启动
    rebuild_kb_index 自愈），重建零数据损失；迁移 16 的 bucket 默认值即存量回填
    （全部留在 company 桶，reference 桶从空开始）。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kb_materials(
          id TEXT PRIMARY KEY, item_id TEXT NOT NULL,
          title TEXT NOT NULL, topics TEXT NOT NULL, usage TEXT NOT NULL,
          section_path TEXT, line_start INTEGER, line_end INTEGER,
          created_at TEXT NOT NULL)"""
    )
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='kb_segments'"
    ).fetchone()
    if row is not None and "material_id" not in row["sql"]:
        conn.execute("DROP TABLE kb_segments")
        conn.execute(
            "CREATE VIRTUAL TABLE kb_segments USING fts5("
            "body, item_id UNINDEXED, section_path UNINDEXED, material_id UNINDEXED, "
            "line_start UNINDEXED, line_end UNINDEXED, page_start UNINDEXED)"
        )


def apply(conn: sqlite3.Connection, current: int) -> None:
    """从 current 版本起应用全部待执行迁移（每迁移一个事务，随事务写版本号）。"""
    for version, fn in MIGRATIONS:
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            fn(conn)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
