"""checkpoint 安全清理（2026-09-13）：原则 P0-P7 逐条钉死。

agent.db 侧用 SqliteSaver 在临时库上构造真 schema（与库同步，不手抄 DDL），再
直接 INSERT 合成行；app.db 侧用 db API 造会话与 run 行。合成 checkpoint_id 用
自增编号串——字典序=时间序，固化清理所依赖的排序假设（langgraph 真身是
time-ordered uuid，同性质）。
"""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app import config as cfg
from app import db
from app.checkpoint_prune import KEEP_MAIN_CHECKPOINTS, prune_agent_db


def _cp(i: int) -> str:
    """合成 checkpoint_id（编号即时间序）。"""
    return f"{i:08d}-cp"


def _seed_checkpoints(rows: list[tuple[str, str, str]]) -> None:
    """rows: (thread_id, ns, checkpoint_id)。blobs 给定长，字节数可断言。"""
    conn = sqlite3.connect(cfg.agent_db_path())
    conn.executemany(
        "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id,"
        " parent_checkpoint_id, type, checkpoint, metadata) VALUES (?,?,?,NULL,'json',?,'{}')",
        [(t, ns, c, b"x" * 100) for t, ns, c in rows],
    )
    conn.commit()
    conn.close()


def _seed_write(tid: str, cid: str) -> None:
    conn = sqlite3.connect(cfg.agent_db_path())
    conn.execute(
        "INSERT INTO writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,"
        " channel, type, value) VALUES (?,?,?,?,0,'messages','json',?)",
        (tid, "", cid, "task-1", b"y" * 50),
    )
    conn.commit()
    conn.close()


def _remaining() -> tuple[set[tuple[str, str, str]], set[tuple[str, str]]]:
    conn = sqlite3.connect(cfg.agent_db_path())
    cps = set(conn.execute("SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints"))
    wrs = set(conn.execute("SELECT thread_id, checkpoint_id FROM writes"))
    conn.close()
    return cps, wrs


def _init_agent_schema() -> None:
    """空 agent.db 上建 langgraph 真 schema（setup() 建 checkpoints/writes）。"""
    conn = sqlite3.connect(cfg.agent_db_path())
    SqliteSaver(conn).setup()
    conn.close()


def _mk_run(db, status: str, error_code: str | None = None) -> str:
    conv = db.create_conversation()["id"]
    rid = db.create_run(conv)["id"]
    db.finish_run(rid, status, error="e" if status == "error" else None, error_code=error_code)
    return conv


def test_prune_terminal_keeps_window_and_frontier(monkeypatch, tmp_path):
    """终态会话（P0/P1/P3/P4）：主图保最新 3 份；早于保留窗的中间份与旧子代理链
    删除；晚于保留窗起点的在途子代理链保留；writes 跟随删除、保留集的 writes 不动。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    _init_agent_schema()

    conv = _mk_run(db, "completed")
    tid = conv
    _seed_checkpoints([
        (tid, "", _cp(10)), (tid, "", _cp(20)), (tid, "", _cp(30)),  # 保留窗=30/40/50
        (tid, "", _cp(40)), (tid, "", _cp(50)),
        (tid, "tools:t-a", _cp(15)), (tid, "tools:t-b", _cp(25)),    # 旧链（< guard 30）
        (tid, "tools:t-c", _cp(45)),                                  # frontier（> guard）
    ])
    _seed_write(tid, _cp(10))  # 随删
    _seed_write(tid, _cp(45))  # 随留
    _seed_write(tid, _cp(50))  # 随留

    stats = prune_agent_db()
    cps, wrs = _remaining()
    expect_cps = {
        (tid, "", _cp(30)), (tid, "", _cp(40)), (tid, "", _cp(50)), (tid, "tools:t-c", _cp(45)),
    }
    assert cps == expect_cps
    assert wrs == {(tid, _cp(45)), (tid, _cp(50))}
    assert stats["rows_deleted"] == 5  # 4 checkpoints + 1 write
    assert stats["threads_pruned"] == 1 and stats["vacuumed"] is False


def test_prune_keeps_last_few_mains_when_short(monkeypatch, tmp_path):
    """主图不足保留窗（P0 退化形态）：guard=最老那份，链尾必留、旧链照删。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    _init_agent_schema()

    tid = _mk_run(db, "completed")
    _seed_checkpoints([(tid, "", _cp(10)), (tid, "tools:t", _cp(5))])
    _seed_write(tid, _cp(5))

    prune_agent_db()
    cps, wrs = _remaining()
    assert cps == {(tid, "", _cp(10))}
    assert wrs == set()


def test_prune_excludes_resumable_and_active(monkeypatch, tmp_path):
    """P2 排除三态：waiting_input / running / error+可续码 → thread 一行不动。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    _init_agent_schema()

    t_wait = _mk_run(db, "waiting_input")
    t_run = _mk_run(db, "running")
    t_resumable = _mk_run(db, "error", error_code="llm_unavailable")
    # cancelled 不在可续集合（尊重停止意图）→ 不排除，此处只验证排除态
    seeded = []
    for tid in (t_wait, t_run, t_resumable):
        seeded += [(tid, "", _cp(10)), (tid, "", _cp(20)), (tid, "tools:t", _cp(5))]
    _seed_checkpoints(seeded)

    stats = prune_agent_db()
    cps, _ = _remaining()
    assert cps == set(seeded)
    assert stats["rows_deleted"] == 0 and stats["threads_skipped"] == 3


def test_prune_cleans_orphan_thread_entirely(monkeypatch, tmp_path):
    """孤儿 thread（app.db 无会话行——删会话崩溃残留）：整链全删。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    _init_agent_schema()

    _mk_run(db, "completed")  # 至少一个正常会话，证明孤儿清理不误伤别家
    ghost = "c_ghost"
    _seed_checkpoints([(ghost, "", _cp(10)), (ghost, "tools:t", _cp(20))])
    _seed_write(ghost, _cp(10))

    prune_agent_db()
    cps, wrs = _remaining()
    assert all(t != ghost for t, _, _ in cps)
    assert all(t != ghost for t, _ in wrs)


def test_prune_idempotent(monkeypatch, tmp_path):
    """幂等：第二遍删 0 行（保留窗与 frontier 已是稳态）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    _init_agent_schema()

    tid = _mk_run(db, "completed")
    _seed_checkpoints([(tid, "", _cp(i)) for i in (10, 20, 30, 40, 50)]
                      + [(tid, "tools:t", _cp(15))])
    first = prune_agent_db()
    assert first["rows_deleted"] > 0
    second = prune_agent_db()
    assert second["rows_deleted"] == 0 and second["threads_pruned"] == 0


def test_keep_window_constant():
    """保留窗常量钉住（改它=改原则 P0，须连带改 checkpoint_prune 模块头与 docs/decision-log.md 对应条目）。"""
    assert KEEP_MAIN_CHECKPOINTS == 3
