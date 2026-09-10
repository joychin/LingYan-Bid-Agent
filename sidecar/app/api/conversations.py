"""会话与消息端点（PRD §5.4 契约）。

P4：会话必须归属任务（POST 必填 task_id）。2026-08-31 重构：文件归任务、会话=执行
上下文——删会话只删转录 + checkpoint，不动任务文件树（产物/过程文件/来源全部保留）。
"""

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent, bg, db, events, titler
from .. import config as cfg
from ..agent import delete_thread_memory, run_stream

router = APIRouter()


class NewConversationBody(BaseModel):
    task_id: str
    title: str | None = None


class RenameConversationBody(BaseModel):
    title: str


class NewMessageBody(BaseModel):
    content: str
    # 思考档位（标准 reasoning_effort 三档；模型默认开思考，无关闭项），缺省 low
    thinking: Literal["low", "medium", "high"] | None = None
    # 本条消息选用的模型 profile id（输入框胶囊选择器），缺省/未知值走 default
    model: str | None = None


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
    # 文件归任务：删会话不动任务文件树（产物/过程文件/来源保留），只清转录 + checkpoint
    db.delete_conversation(cid)
    delete_thread_memory(cid)  # 「删会话 = 删上下文」：连带清 agent.db 里该 thread 的 checkpoint
    return {"ok": True}


@router.get("/conversations/{cid}/messages")
async def get_messages(cid: str):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.list_messages(cid)
    # 过程快照瘦身（2026-09-08）：tools/todos/reasoning 大对象不再随列表下发
    # （标书会话实测 11.4MB、随历史线性涨，而每次 run 收尾/invalidate 都全量重拉）；
    # 折叠头只需步数/是否暂停摘要，完整过程点开时按需取（下方 trace 端点）。
    summaries = db.get_message_trace_summaries(
        [m["id"] for m in messages if m["role"] == "assistant"]
    )
    for m in messages:
        s = summaries.get(m["id"])
        if s is not None:
            m["traceSteps"] = s["steps"]
            m["tracePaused"] = s["paused"]
            m["durationMs"] = s["durationMs"]
            m["files"] = s["files"]
    return {"messages": messages}


@router.get("/conversations/{cid}/messages/{mid}/trace")
async def get_message_trace(cid: str, mid: str):
    """单条消息的完整执行过程（按需，2026-09-08）：tools 步骤树 + todos + 最终段
    思考。用户点开历史消息过程区时前端才取（按消息缓存）；cid 归属校验防跨会话。"""
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    msg = db.get_message(mid)
    if msg is None or msg["conversation_id"] != cid:
        raise HTTPException(status_code=404, detail="消息不存在")
    t = db.get_trace_by_message(mid)
    if t is None:
        raise HTTPException(status_code=404, detail="该消息没有执行过程")
    return {"tools": t["tools"], "todos": t["todos"], "reasoning": t["reasoning"]}


@router.get("/conversations/{cid}/runs/latest")
async def get_latest_run(cid: str):
    """最新 run 状态（任意状态）：SSE 断线期间 run 结束时，前端据此收敛 running 态。
    waiting_input 时附 requests 快照（恢复审批/问答卡）。"""
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    run = db.get_latest_run(cid)
    if run and run["status"] == "waiting_input":
        try:
            # 过一遍 ask_human 参数自愈：修复前落库的快照可能带泄漏形态（2026-09-10）
            run["requests"] = events.normalize_hitl_requests(json.loads(run.pop("interrupt") or "[]"))
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

    thinking = body.thinking or "low"
    # 模型 profile：未知 id（配置已删）静默回落 default，不为此打断对话
    model = body.model if body.model and cfg.get_profile(body.model) else ""
    # 先建 run 再落用户消息：messages.run_id 关联所属回合（前端按 run 聚合消息段）
    run = db.create_run(cid, thinking, model)
    msg = db.create_user_message(cid, content, rid=run["id"])

    # 自动命名（fire-and-forget）：默认标题时后台生成，条件收敛在 titler 内部
    bg.spawn_background(titler.maybe_generate_title(cid, content))

    async def _task():
        await run_stream(cid, run["id"], content, thinking=thinking, model=model or None)

    bg.spawn_background(_task())
    return {"message_id": msg["id"], "run_id": run["id"]}
