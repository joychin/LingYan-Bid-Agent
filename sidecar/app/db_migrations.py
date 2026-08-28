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

LATEST = 9


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(ddl)


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
]


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
