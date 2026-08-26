"""run 上下文（contextvars）：把 (conversation_id, run_id, task_id) 传给工具层。

工具在 worker 线程内随 agent 流同步执行，与 _run_agent_stream 共享同一份
context 拷贝；发布管线据此记录产物来源与作用域，任务进度工具据此归属任务。
未处于 run 中时 current_run() 返回 None（如测试直接调工具）。
"""

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class RunCtx:
    conversation_id: str
    run_id: str
    task_id: str | None = None


_ctx: contextvars.ContextVar[RunCtx | None] = contextvars.ContextVar("run_ctx", default=None)


def set_run(cid: str, rid: str, task_id: str | None = None) -> None:
    _ctx.set(RunCtx(cid, rid, task_id))


def clear_run() -> None:
    _ctx.set(None)


def current_run() -> RunCtx | None:
    return _ctx.get()
