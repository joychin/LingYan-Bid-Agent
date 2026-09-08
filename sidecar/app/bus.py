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
    # 2000：8 路子代理并发的 reasoning/token 洪峰会冲垮 500 的水位（2026-09-08
    # 实测 tool.result 被静默挤掉→前端死步），扩容降低丢弃概率；丢了有前端过程对账兜底
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
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
                # 可丢事件（token/todo/tool 等增量）：客户端靠终态事件+重连对账兜底。
                # info 级（2026-09-08 从 debug 升）：洪峰丢事件是已发生过的真事故，静默不可诊断
                logger.info("SSE 队列积压，丢弃事件 %s（cid=%s）", event.get("event"), conversation_id)
                continue
            # 必达事件：挤出最旧的**非必达**事件腾位。单事件循环内以下操作无并发，
            # 整队列重建一遍找得到可丢事件；若积压全是必达事件（消费者彻底停滞的
            # 极端态），保序丢弃最旧一条并告警——此时丢哪个都丢失收敛信号。
            held: list[dict] = []
            evicted: dict | None = None
            while True:
                try:
                    oldest = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if evicted is None and oldest.get("event") not in _MUST_DELIVER:
                    evicted = oldest
                    continue
                held.append(oldest)
            if evicted is None and held:
                evicted = held.pop(0)  # 全是必达事件：held 头部即最旧一条
            for e in held:
                q.put_nowait(e)
            if evicted is not None:
                logger.warning(
                    "SSE 队列积压，丢弃最旧事件 %s（cid=%s）", evicted.get("event"), conversation_id
                )
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # 理论不可达（防御：空队列才走到这）
                logger.error("必达事件入队失败 %s（cid=%s）", event.get("event"), conversation_id)
