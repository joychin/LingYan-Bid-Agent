"""每会话的内存事件订阅（asyncio.Queue 列表）。

SSE 端点订阅某个 conversation_id，run_stream 任务发布事件到该会话的所有订阅者。
MVP 不做断线补发：客户端重连时重新 GET /messages 拉全量。
"""

import asyncio
from collections import defaultdict
from typing import Any

_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(conversation_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers[conversation_id].append(q)
    return q


def unsubscribe(conversation_id: str, q: asyncio.Queue) -> None:
    try:
        _subscribers[conversation_id].remove(q)
    except ValueError:
        pass
    if not _subscribers[conversation_id]:
        _subscribers.pop(conversation_id, None)


async def publish(conversation_id: str, event: dict[str, Any]) -> None:
    for q in list(_subscribers.get(conversation_id, [])):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:  # 防御：队列积压则丢弃，客户端可重拉
            pass
