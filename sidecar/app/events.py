"""LangGraph 流 → SSE 事件的唯一映射层。

DeepAgents 处于 beta，库内部格式变化只改这个文件，事件契约（agent.started / agent.token /
tool.called / tool.result / agent.completed / agent.error / ping /
todo.updated / artifact.created / run.state）不可变。
agent.reasoning 是对契约的 additive 扩展（DeepSeek 推理模型有 reasoning_content 时才下发）。
"""

import json
from typing import Iterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

EVENT_STARTED = "agent.started"
EVENT_TOKEN = "agent.token"
EVENT_TOOL_CALLED = "tool.called"
EVENT_TOOL_RESULT = "tool.result"
EVENT_COMPLETED = "agent.completed"
EVENT_ERROR = "agent.error"
EVENT_TODO_UPDATED = "todo.updated"
EVENT_ARTIFACT_CREATED = "artifact.created"
# 推理模型（DeepSeek reasoner）的 chain-of-thought 增量文本；非推理模型不产生该事件
EVENT_REASONING = "agent.reasoning"
# SSE 连接建立时由端点直接下发的对账事件（非 iter_stream 产出）：
# 携带该会话最新 run 的真实状态，客户端据此恢复 running 或收敛
EVENT_RUN_STATE = "run.state"


def _chunk_text(msg: AIMessageChunk) -> str:
    """从 AIMessageChunk 提取增量文本（content 可能是 str 或内容块列表）。"""
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c
    parts: list[str] = []
    for b in c:
        if isinstance(b, str):
            parts.append(b)
        elif isinstance(b, dict):
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", "") or "")
    return "".join(parts)


def _chunk_reasoning(msg: AIMessageChunk) -> str:
    """从 AIMessageChunk 提取增量推理文本（DeepSeek 的 reasoning_content）。

    ChatDeepSeek 把推理增量放 additional_kwargs["reasoning_content"]（str 或内容块列表）。
    """
    raw = (getattr(msg, "additional_kwargs", None) or {}).get("reasoning_content")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    if isinstance(raw, list):
        for b in raw:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") in ("text", "reasoning_text"):
                parts.append(b.get("text", "") or "")
    return "".join(parts)


def _tool_args(args) -> dict:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return {"raw": args}
    return {"raw": str(args)}


def _summary(content, limit: int = 400) -> str:
    s = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    s = (s or "").strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def iter_stream(stream: Iterator) -> Iterator[tuple[str, object]]:
    """把 agent.stream(stream_mode=["messages","updates"]) 的产出映射为归一化事件。

    yield: ("token", text) | ("reasoning", text) | ("tool_called", {...})
           | ("tool_result", {...}) | ("todo_updated", todos)
    """
    last_todos_key: str | None = None
    for item in stream:
        mode = item[0] if isinstance(item, tuple) else item
        chunk = item[1] if isinstance(item, tuple) else None
        if mode == "messages":
            msg, _meta = chunk if isinstance(chunk, tuple) else (chunk, None)
            if isinstance(msg, AIMessageChunk):
                reason = _chunk_reasoning(msg)
                if reason:
                    yield ("reasoning", reason)
                text = _chunk_text(msg)
                if text:
                    yield ("token", text)
        elif mode == "updates":
            if not isinstance(chunk, dict):
                continue
            for _node, update in chunk.items():
                # todos 由 TodoListMiddleware 的 write_todos 写入 state；
                # 每次调用整体替换列表，去重后只在内容变化时发事件
                if isinstance(update, dict):
                    todos = update.get("todos")
                    if todos is not None:
                        key = json.dumps(todos, sort_keys=True, ensure_ascii=False)
                        if key != last_todos_key:
                            last_todos_key = key
                            yield ("todo_updated", todos)
                messages = update.get("messages", []) if isinstance(update, dict) else []
                for m in messages:
                    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            yield (
                                "tool_called",
                                {"tool": tc.get("name", "unknown"), "args": _tool_args(tc.get("args"))},
                            )
                    elif isinstance(m, ToolMessage):
                        content = getattr(m, "content", "")
                        status = getattr(m, "status", None)
                        error = None
                        if status == "error":
                            # task 抛出异常时 ToolMessage.content 是错误文本；作为 tool_result 的
                            # error 字段下发，让前端渲染「✗ 失败工具卡」并可展开查看详情
                            error = _summary(content, limit=800)
                        yield (
                            "tool_result",
                            {
                                "tool": getattr(m, "name", None) or "unknown",
                                "summary": _summary(content),
                                "error": error,
                            },
                        )
