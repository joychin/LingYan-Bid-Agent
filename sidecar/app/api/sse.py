"""SSE 事件流端点（PRD §5.5）。

客户端用 @microsoft/fetch-event-source 订阅。断线重连策略：重新 GET /messages 拉全量 +
重新订阅，不做 Last-Event-ID 补发。每 15 秒发一次 `event: ping` 心跳。
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .. import bus, db, events

router = APIRouter()

PING_INTERVAL = 15.0


def _frame(event: str, data: dict) -> dict:
    """sse-starlette 对 dict 的 data 会用 str()（Python repr，单引号）——不是合法 JSON。
    这里预先 json.dumps 成字符串，保证 §5.5 契约 data: <json>。"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def _event_generator(cid: str):
    q = bus.subscribe(cid)
    try:
        # 连接建立即对账：重连的客户端错过了 agent.started/completed（MVP 无补发），
        # 先下发最新 run 的真实状态。订阅在查询之前，期间发布的事件进队列、
        # 排在 run.state 之后，终态事件总能覆盖这里的中间态。
        run = db.get_latest_run(cid)
        if run:
            data = {
                "run_id": run["id"],
                "conversation_id": cid,
                "status": run["status"],
                "error": run["error"],
            }
            # 与 agent.error 同款 additive code：cancelled=用户主动停止（刷新/重连后
            # 经对账事件恢复时同样中性呈现）
            if run["status"] == "error" and run["error"] == events.CANCELLED_MESSAGE:
                data["code"] = "cancelled"
            # HITL 对账：waiting_input 附审批/问答快照，客户端据此恢复 InterruptCard
            if run["status"] == "waiting_input":
                try:
                    data["requests"] = json.loads(run["interrupt"] or "[]")
                except ValueError:
                    data["requests"] = []
            yield _frame(events.EVENT_RUN_STATE, data)
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
    # ping=0 禁用 sse-starlette 库级注释 ping（默认 15s）：_event_generator 的
    # wait_for 超时分支已发同周期的应用层 event: ping，双份 keepalive 纯冗余
    return EventSourceResponse(_event_generator(cid), ping=0)
