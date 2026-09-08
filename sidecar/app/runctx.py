"""run 上下文（contextvars）：把 (conversation_id, run_id, task_id, thinking) 传给工具层与模型层。

工具在 worker 线程内随 agent 流同步执行，与 _run_agent_stream 共享同一份
context 拷贝；发布管线据此记录产物来源与作用域，任务进度工具据此归属任务。
thinking 是本 run 的思考档位（low/medium/high），模型壳在每次 API 请求构建
payload 时现读注入 reasoning_effort。未处于 run 中时 current_run() 返回 None
（如测试直接调工具），current_thinking() 兜底 low。
"""

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class RunCtx:
    conversation_id: str
    run_id: str
    task_id: str | None = None
    thinking: str = "low"


_ctx: contextvars.ContextVar[RunCtx | None] = contextvars.ContextVar("run_ctx", default=None)

# 模型调用语境（main/sub）：与 RunCtx 的 run 级冻结不同，这是逐调用级——子代理
# scope 中间件在 wrap_model_call 内置 sub、finally 复位，token_usage 据此给
# per-turn 用量明细按主线程/子代理归因。默认 main（含 SummarizationMiddleware 等
# 主线程语境的内部调用）。
_scope: contextvars.ContextVar[str] = contextvars.ContextVar("agent_scope", default="main")


def set_run(cid: str, rid: str, task_id: str | None = None, thinking: str = "low") -> None:
    _ctx.set(RunCtx(cid, rid, task_id, thinking))


def clear_run() -> None:
    _ctx.set(None)


def current_run() -> RunCtx | None:
    return _ctx.get()


def current_thinking() -> str:
    ctx = _ctx.get()
    return ctx.thinking if ctx is not None else "low"


def set_agent_scope(scope: str) -> contextvars.Token:
    """置当前模型调用语境；返回 token 供 reset_agent_scope 复位。"""
    return _scope.set(scope)


def reset_agent_scope(token: contextvars.Token) -> None:
    _scope.reset(token)


def current_scope() -> str:
    return _scope.get()
