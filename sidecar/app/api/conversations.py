"""会话与消息端点（PRD §5.4 契约）。

P4：会话必须归属任务（POST 必填 task_id）；删会话级联删该会话的
「过程稿」目录（<task_id>/threads/<cid>/，文件夹语义——正式稿属任务，不受会话删除影响）。
"""

import asyncio
import json
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, artifact_store, db, titler
from ..agent import delete_thread_memory, run_stream

router = APIRouter()


class NewConversationBody(BaseModel):
    task_id: str
    title: str | None = None


class RenameConversationBody(BaseModel):
    title: str


class NewMessageBody(BaseModel):
    content: str


@router.get("/conversations")
async def list_conversations():
    return {"conversations": db.list_conversations()}


@router.post("/conversations", status_code=201)
async def create_conversation(body: NewConversationBody):
    if not db.get_task(body.task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return db.create_conversation(body.task_id, body.title)


@router.patch("/conversations/{cid}")
async def rename_conversation(cid: str, body: RenameConversationBody):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        return db.rename_conversation(cid, body.title)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str):
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if db.active_run_exists(cid):
        raise HTTPException(status_code=409, detail="该会话有进行中的任务，无法删除")
    # 会话「过程稿」目录随会话删除（文件夹语义）；任务「正式稿」不受影响；
    # 索引行随 db.delete_conversation 连带清理
    if conv.get("task_id"):
        shutil.rmtree(artifact_store.thread_dir(conv["task_id"], cid), ignore_errors=True)
    db.delete_conversation(cid)
    delete_thread_memory(cid)  # 「删会话 = 删上下文」：连带清 agent.db 里该 thread 的 checkpoint
    return {"ok": True}


@router.get("/conversations/{cid}/messages")
async def get_messages(cid: str):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.list_messages(cid)
    # assistant 消息挂执行过程快照（run_traces），历史会话/刷新后执行过程与深度思考仍可见
    traces = db.get_traces_for_messages([m["id"] for m in messages if m["role"] == "assistant"])
    for m in messages:
        t = traces.get(m["id"])
        if t is not None:
            m["tools"] = t["tools"]
            m["todos"] = t["todos"]
            m["durationMs"] = t.get("durationMs")
            m["reasoning"] = t.get("reasoning", "")
    return {"messages": messages}


@router.get("/conversations/{cid}/runs/latest")
async def get_latest_run(cid: str):
    """最新 run 状态（任意状态）：SSE 断线期间 run 结束时，前端据此收敛 running 态。
    waiting_input 时附 requests 快照（恢复审批/问答卡）。"""
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    run = db.get_latest_run(cid)
    if run and run["status"] == "waiting_input":
        try:
            run["requests"] = json.loads(run.pop("interrupt") or "[]")
        except ValueError:
            run["requests"] = []
    elif run:
        run.pop("interrupt", None)
    return {"run": run}


@router.post("/conversations/{cid}/messages", status_code=202)
async def create_message(cid: str, body: NewMessageBody):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    latest = db.get_latest_run(cid)
    if latest and latest["status"] == "waiting_input":
        raise HTTPException(status_code=409, detail="该任务正在等待你的回答/确认，请先处理后再发新消息")
    if latest and latest["status"] == "running":
        if agent.is_cancel_pending(latest["id"]):
            # 用户刚点了停止、run 在协作式取消的事件边界等待收尾（通常 1~2s）：
            # 短暂探测等待其终止后放行，让「停止→立刻发下一条」不必撞 409
            for _ in range(20):
                await asyncio.sleep(0.15)
                latest = db.get_latest_run(cid)
                if not latest or latest["status"] != "running":
                    break
        if latest and latest["status"] == "running":
            raise HTTPException(status_code=409, detail="该会话已有进行中的任务")

    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="消息内容不能为空")

    msg = db.create_user_message(cid, content)
    run = db.create_run(cid)

    # 自动命名（fire-and-forget）：默认标题时后台生成，条件收敛在 titler 内部
    asyncio.create_task(titler.maybe_generate_title(cid, content))

    async def _task():
        await run_stream(cid, run["id"], content)

    asyncio.create_task(_task())
    return {"message_id": msg["id"], "run_id": run["id"]}
