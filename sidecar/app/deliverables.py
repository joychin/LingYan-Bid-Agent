"""交付物呈现信号的收集队列（deliverable.created 事件的产出侧）。

行业共识（Claude artifacts / Cowork / Canvas）：什么东西值得展示由**产出通道
自己声明**，UI 不带任何文件名/业务类型规则。本模块是声明侧的机械收集层：

- 工具线程（ToolNode 的 ContextThreadPoolExecutor 子线程，contextvars 只能
  父→子传播、写不回 worker 上下文）在产出交付物的成功点调 note()——按
  runctx 里的 run_id 归桶，无 run（脚本直调/测试）静默跳过；
- 呈现时机=**run 正常完成时**（2026-09-13 二批改定，首版「产出即开」被用户
  调整）：agent.py 在 completed 分支 drain 取**最后一个**声明、在终态事件前
  发出 deliverable.created（error/含取消与 interrupt 等待段不呈现，随段
  丢弃）；run 收尾 finally 清桶防泄漏。

当前声明点：publish.py 的两条发布路径（publish_artifact JSON 产物 /
publish_file_artifact 文件型产物 tender.volume=整本）的成功分支——内容
未变短路分支不声明（没新东西不打扰）。kind=file 通道保留给未来不走产物
系统的文件型交付物（path 相对 <task>/work/）。

并发语义：deque 的 append/popleft 是原子操作（CPython），无需加锁——note
可能来自并行工具线程、drain 只在 run 收尾的事件循环单点发生；不丢不重。

事件本身是**瞬时呈现信号**（additive，2026-09-13）：不落库、不重放、错过
不补——转录里的产物卡/「本轮文件」chips 是持久兜底；artifact.created 仍是
run/段边界的登记对账事件（落库、emitted 去重），两者分工不重叠。
"""

import logging
from collections import deque

from . import runctx

logger = logging.getLogger(__name__)

# 按 run_id 分桶（同 CANCEL_EVENTS 键控姿势）：并发 run 互不串台，一个 run
# 结束只清自己的桶
_QUEUE: dict[str, deque[dict]] = {}


def note(kind: str, **payload) -> None:
    """在当前 run 里声明一个交付物（呈现信号）。

    kind: "artifact"（artifact_id/display_name）| "file"（path/display_name，
    path 相对 <task>/work/，与「本轮文件」chips 同格式）。
    不在 run 中（脚本直调工具/测试）静默跳过——没有 seq 宿主就没有事件。
    """
    ctx = runctx.current_run()
    if ctx is None:
        return
    _QUEUE.setdefault(ctx.run_id, deque()).append({"kind": kind, **payload})


def drain(rid: str) -> list[dict]:
    """取走该 run 收集到的全部声明（破坏性读，队列为空返回空列表）。"""
    q = _QUEUE.get(rid)
    if not q:
        return []
    out: list[dict] = []
    while q:
        out.append(q.popleft())
    return out


def clear(rid: str) -> None:
    """run 收尾清桶（防御性：drain 已空时是 no-op，防异常路径残留累积）。"""
    _QUEUE.pop(rid, None)
