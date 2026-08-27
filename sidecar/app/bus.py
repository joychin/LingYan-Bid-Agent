"""每会话的内存事件订阅（asyncio.Queue 列表）。

SSE 端点订阅某个 conversation_id，run_stream 任务发布事件到该会话的所有订阅者。
MVP 不做断线补发：客户端重连时重新 GET /messages 拉全量。
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any

from . import events

logger = logging.getLogger(__name__)

_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

# 必达事件（不可见 plumbing）：终态事件丢了客户端在连接存活时没有收敛信号
# （run.state 只在重连建立时发一次），run 会卡「执行中」；artifact.created 丢了
# 产物面板无刷新触发。积压时宁可挤出最旧的可丢事件（token 增量等）也要送达。
_MUST_DELIVER = {
    events.EVENT_COMPLETED,
    events.EVENT_ERROR,
    events.EVENT_RUN_INTERRUPT,
    events.EVENT_ARTIFACT_CREATED,
}


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
        except asyncio.QueueFull:
            if event.get("event") not in _MUST_DELIVER:
                # 可丢事件（token/todo/tool 等增量）：客户端靠终态事件+重连对账兜底
                logger.debug("SSE 队列积压，丢弃事件 %s（cid=%s）", event.get("event"), conversation_id)
                continue
            # 必达事件：挤出最旧一条腾位（多为可丢的 token 增量）再入队。
            # 单事件循环内 get/put 之间无并发，取一条即有空位。
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # 理论不可达（防御）
                logger.error("必达事件入队失败 %s（cid=%s）", event.get("event"), conversation_id)
