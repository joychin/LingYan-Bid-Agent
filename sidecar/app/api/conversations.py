"""会话与消息端点（PRD §5.4 契约）。"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from ..agent import run_stream

router = APIRouter()


class NewConversationBody(BaseModel):
    title: str | None = None


class NewMessageBody(BaseModel):
    content: str


@router.get("/conversations")
async def list_conversations():
    return {"conversations": db.list_conversations()}


@router.post("/conversations", status_code=201)
async def create_conversation(body: NewConversationBody):
    return db.create_conversation(body.title)


@router.get("/conversations/{cid}/messages")
async def get_messages(cid: str):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"messages": db.list_messages(cid)}


@router.post("/conversations/{cid}/messages", status_code=202)
async def create_message(cid: str, body: NewMessageBody):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    if db.active_run_exists(cid):
        raise HTTPException(status_code=409, detail="该会话已有进行中的任务")

    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="消息内容不能为空")

    msg = db.create_user_message(cid, content)
    run = db.create_run(cid)

    async def _task():
        await run_stream(cid, run["id"], content)

    asyncio.create_task(_task())
    return {"message_id": msg["id"], "run_id": run["id"]}
