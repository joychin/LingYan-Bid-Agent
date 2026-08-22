"""LangGraph 流 → §5.5 SSE 事件的唯一映射层。

DeepAgents 处于 beta，库内部格式变化只改这个文件，事件契约（agent.started / agent.token /
tool.called / tool.result / agent.completed / agent.error / ping）不可变。
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

    yield: ("token", text) | ("tool_called", {...}) | ("tool_result", {...})
    """
    for item in stream:
        mode = item[0] if isinstance(item, tuple) else item
        chunk = item[1] if isinstance(item, tuple) else None
        if mode == "messages":
            msg, _meta = chunk if isinstance(chunk, tuple) else (chunk, None)
            if isinstance(msg, AIMessageChunk):
                text = _chunk_text(msg)
                if text:
                    yield ("token", text)
        elif mode == "updates":
            if not isinstance(chunk, dict):
                continue
            for _node, update in chunk.items():
                messages = update.get("messages", []) if isinstance(update, dict) else []
                for m in messages:
                    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            yield (
                                "tool_called",
                                {"tool": tc.get("name", "unknown"), "args": _tool_args(tc.get("args"))},
                            )
                    elif isinstance(m, ToolMessage):
                        yield (
                            "tool_result",
                            {
                                "tool": getattr(m, "name", None) or "unknown",
                                "summary": _summary(getattr(m, "content", "")),
                            },
                        )
