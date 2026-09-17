"""agent.db checkpoint 安全清理（2026-09-13 磁盘治理批）。

动因：langgraph SqliteSaver 每个 superstep 写一份「全量消息历史」checkpoint，
单链总量随步数平方增长；子代理（task 工具）每条派发再开独立 checkpoint 链
（ns=tools:<tid>），整本 run 数十条链——实测 agent.db 涨到 1.86GB，其中 98%
是终态 run 抛在身后的历史子代理链（308 条链 1.6GB，主图全部会话仅 39MB）。

安全性建立在「运行时只读链尾」上：全 sidecar 对 checkpoint 的读取仅两处——
checkpoint_exists 的 get_tuple 与 recover_agent_memory 的 get_state，都取最新
一份；历史中间份在任何运行路径里不被读取（历史回看走 app.db 的
messages/run_traces，与 agent.db 无关）。清理原则（P0-P7，测试逐条钉死）：

P0 链尾不可删：主图（ns=''）最新 3 份恒保留——链尾是会话记忆的锚点（下一条
   消息从它续写），另两份防 parent_checkpoint_id 引用悬空的廉价保险。
P1 只删永远不被读的行：早于保留窗的主图中间份 + 早于保留窗的子代理链
   （属已完成波次；新波次 task id 全新，旧链永不复用）。
P2 可续态排除：会话有 running/waiting_input run，或最新 run 为 error 且
   error_code ∈ db.RESUMABLE_ERROR_CODES → 整个 thread 一行不动（断点续跑/
   暂停续跑链原封不动）。
P3 frontier 保留：checkpoint_id ≥ 保留窗起点的行一律不删——取消态会话链尾
   superstep 里在途子代理链在此，删了会退化为整节重写。checkpoint_id 是
   langgraph 的 time-ordered uuid，字典序=时间序（SqliteSaver get_tuple 同序）。
P4 writes 跟随：只删 checkpoint_id ∈ 删除集合的 writes 行；保留集的 writes
   一行不动（断点重放可能读链尾 pending writes）。
P5 会话粒度小事务：先 SELECT 算集合再 DELETE（thread_id+checkpoint_id 双限定、
   分批 IN），单会话失败只记日志不外抛。
P6 删而不缩=白做：删后 PRAGMA wal_checkpoint(TRUNCATE) 折叠 WAL；主文件+WAL
   仍超体积门槛且无占用中 run 时跑一次 VACUUM 收缩（SQLite 删行只留空页）。
P7 可观测：每会话记删行数/字节，VACUUM 记前后体积与耗时。

孤儿 thread（app.db 无对应会话行——删会话时的崩溃残留）：整链全删。
触发点=sidecar 启动（recover_stale_runs 之后、recover_agent_memory 之前：后者
首建 saver 长连接，清理先行获得独占写窗口；崩溃残留 run 已标 interrupted=可续，
自动落 P2 排除）。任何失败不阻断启动（退化=现状不清理，下次启动重试）。
"""

import logging
import sqlite3
import time

from . import config as cfg
from . import db

logger = logging.getLogger(__name__)

# 主图保留窗：最新 3 份（链尾记忆锚点 + 两份父链保险，均摊几 MB）
KEEP_MAIN_CHECKPOINTS = 3
# VACUUM 体积门槛（字节）：删行折叠 WAL 后主文件+WAL 仍超过才值得全库重写
VACUUM_THRESHOLD = 300 * 1024 * 1024
# 删除集合分批大小（IN 参数上限防御；单线程实测最多两千余行，900 远够）
_DELETE_BATCH = 900


def prune_agent_db(allow_vacuum: bool = True) -> dict:
    """清理 agent.db 的历史 checkpoint（幂等，启动时调用）。返回统计 dict。

    allow_vacuum=False（2026-09-17）：只删行 + 折叠 WAL、跳过 VACUUM——大库
    VACUUM 全库重写可达分钟级，而 lifespan 完成前 uvicorn 不 listen，Rust 探活
    窗口超时即杀（库越大越起不来、VACUUM 被打断下次还重做）。VACUUM 由 main.py
    的后台延迟任务（启动 2 分钟后且无活跃 run）重跑本函数（默认参数）时执行。
    """
    stats: dict = {"threads_pruned": 0, "rows_deleted": 0, "bytes_freed": 0,
                   "threads_skipped": 0, "vacuumed": False}
    path = cfg.agent_db_path()
    if not path.is_file():
        return stats
    conn = sqlite3.connect(str(path), timeout=5.0)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(checkpoints)")}
        wcols = {r[1] for r in conn.execute("PRAGMA table_info(writes)")}
        if not {"thread_id", "checkpoint_ns", "checkpoint_id"} <= cols or "checkpoint_id" not in wcols:
            logger.warning("agent.db 表结构与预期不符（langgraph 升级？），跳过 checkpoint 清理")
            return stats
        threads = [r[0] for r in conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id").fetchall()]
        for tid in threads:
            try:
                _prune_thread(conn, tid, stats)
            except sqlite3.DatabaseError:
                conn.rollback()
                logger.exception("checkpoint 清理失败（thread=%s），跳过该会话", tid)
        # P6：折叠 WAL（把 -wal 并回主文件，删行收益先兑现一半）
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        size = path.stat().st_size + _wal_size(path)
        if allow_vacuum and size > VACUUM_THRESHOLD and not db.list_active_runs():
            t0 = time.monotonic()
            conn.execute("VACUUM")
            # WAL 模式下 VACUUM 先落 -wal，折叠回主文件后体积才真实收缩
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("agent.db VACUUM：%.2f GB → %.2f MB，用时 %.1fs",
                        size / 1073741824, path.stat().st_size / 1048576,
                        time.monotonic() - t0)
            stats["vacuumed"] = True
    finally:
        conn.close()
    if stats["rows_deleted"]:
        logger.info("checkpoint 清理完成：%d 个会话删 %d 行（约 %.0f MB）",
                    stats["threads_pruned"], stats["rows_deleted"],
                    stats["bytes_freed"] / 1048576)
    return stats


def vacuum_needed() -> bool:
    """主文件+WAL 是否超过 VACUUM 门槛（后台延迟任务的预检：小库直接免 120s 空等）。"""
    path = cfg.agent_db_path()
    if not path.is_file():
        return False
    return path.stat().st_size + _wal_size(path) > VACUUM_THRESHOLD


def _wal_size(path) -> int:
    wal = path.with_name(path.name + "-wal")
    try:
        return wal.stat().st_size
    except OSError:
        return 0


def _prune_thread(conn: sqlite3.Connection, tid: str, stats: dict) -> None:
    """单 thread 清理（P2 排除 → 孤儿整删 → 保留窗计算 → 分批删除）。"""
    # P2 排除：占用中或最新 run 可续 → 一行不动
    if db.active_run_exists(tid):
        stats["threads_skipped"] += 1
        return
    latest = db.get_latest_run(tid)
    if latest and latest.get("status") == "error" and latest.get("error_code") in db.RESUMABLE_ERROR_CODES:
        stats["threads_skipped"] += 1
        return

    rows = conn.execute(
        "SELECT checkpoint_ns, checkpoint_id FROM checkpoints WHERE thread_id=?", (tid,)
    ).fetchall()

    # 孤儿 thread：app.db 无会话行（删会话的崩溃残留）→ 整链全删
    if db.get_conversation(tid) is None:
        del_ids = [cid for _ns, cid in rows]
        n, b = _delete_ids(conn, tid, del_ids)
        if n:
            logger.info("checkpoint 清理（孤儿 thread=%s）：删 %d 行（%.1f MB）",
                        tid, n, b / 1048576)
            stats["threads_pruned"] += 1
            stats["rows_deleted"] += n
            stats["bytes_freed"] += b
        return

    mains = [cid for ns, cid in rows if ns == ""]
    if not mains:
        # 无主图行的异常形态（正常 thread 主图必然先落）：保守不动
        stats["threads_skipped"] += 1
        return
    mains.sort(reverse=True)  # checkpoint_id 字典序=时间序（P3 同款假设）
    keep = set(mains[:KEEP_MAIN_CHECKPOINTS])
    guard = mains[min(KEEP_MAIN_CHECKPOINTS, len(mains)) - 1]
    # P1/P3：主图不在保留窗 ∪ 子代理链早于保留窗起点；guard 之后的行（含在途
    # 子代理链）一律保留
    del_ids = [cid for ns, cid in rows
               if cid < guard or (ns == "" and cid not in keep)]
    n, b = _delete_ids(conn, tid, del_ids)
    if n:
        logger.info("checkpoint 清理（thread=%s）：删 %d 行（writes 含在内）/ 保留 %d 行 checkpoint（%.1f MB）",
                    tid, n, len(rows) - len(del_ids), b / 1048576)
        stats["threads_pruned"] += 1
        stats["rows_deleted"] += n
        stats["bytes_freed"] += b


def _delete_ids(conn: sqlite3.Connection, tid: str, del_ids: list[str]) -> tuple[int, int]:
    """按删除集合删 checkpoints + writes（P4/P5：双限定、分批、先量后删）。

    返回 (删行数, 释放字节)。空集合直接返回；分批提交——每批是独立小事务，
    中断只会少删不会误删（保留集不在删除集合里，结构性安全）。
    """
    total_rows = 0
    total_bytes = 0
    for i in range(0, len(del_ids), _DELETE_BATCH):
        batch = del_ids[i:i + _DELETE_BATCH]
        ph = ",".join("?" * len(batch))
        cp_bytes = conn.execute(
            f"SELECT COALESCE(SUM(LENGTH(checkpoint)),0) FROM checkpoints"
            f" WHERE thread_id=? AND checkpoint_id IN ({ph})",
            (tid, *batch),
        ).fetchone()[0]
        w_bytes = conn.execute(
            f"SELECT COALESCE(SUM(LENGTH(COALESCE(value,''))),0) FROM writes"
            f" WHERE thread_id=? AND checkpoint_id IN ({ph})",
            (tid, *batch),
        ).fetchone()[0]
        c1 = conn.execute(
            f"DELETE FROM checkpoints WHERE thread_id=? AND checkpoint_id IN ({ph})",
            (tid, *batch),
        ).rowcount
        c2 = conn.execute(
            f"DELETE FROM writes WHERE thread_id=? AND checkpoint_id IN ({ph})",
            (tid, *batch),
        ).rowcount
        conn.commit()
        total_rows += c1 + c2
        total_bytes += cp_bytes + w_bytes
    return total_rows, total_bytes
