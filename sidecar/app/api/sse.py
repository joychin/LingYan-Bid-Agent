"""SSE 事件流端点（PRD §5.5）。

客户端用 @microsoft/fetch-event-source 订阅。断线重连策略：重新 GET /messages 拉全量 +
重新订阅，不做 Last-Event-ID 补发。每 15 秒发一次 `event: ping` 心跳。
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .. import bus, db

router = APIRouter()

PING_INTERVAL = 15.0


def _frame(event: str, data: dict) -> dict:
    """sse-starlette 对 dict 的 data 会用 str()（Python repr，单引号）——不是合法 JSON。
    这里预先 json.dumps 成字符串，保证 §5.5 契约 data: <json>。"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def _event_generator(cid: str):
    q = bus.subscribe(cid)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=PING_INTERVAL)
            except asyncio.TimeoutError:
                yield _frame("ping", {})
                continue
            yield _frame(event["event"], event["data"])
    finally:
        bus.unsubscribe(cid, q)


@router.get("/conversations/{cid}/events")
async def stream_events(cid: str):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    return EventSourceResponse(_event_generator(cid))
