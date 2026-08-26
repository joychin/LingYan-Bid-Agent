"""Run 端点：HITL 裁决续跑 + 用户主动停止。

run.interrupt 暂停（status=waiting_input）后，用户在前端做出 decision
（approve / reject+理由 / respond=回答 / edit），经本端点以
Command(resume={"decisions": [...]}) 从 checkpoint 的 interrupt 处续跑同一 run。
stop 端点对 running 的 run 置位协作式取消事件，worker 线程在下一个流事件边界退出
（半截回复落库 + run 标 error「任务已停止」，语义同既有中断路径）。
"""

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..agent import request_cancel, run_stream

logger = logging.getLogger(__name__)

router = APIRouter()


class DecisionBody(BaseModel):
    # langchain HITL 四种决策（与 HumanInTheLoopMiddleware 的 Decision 一致）
    type: Literal["approve", "reject", "respond", "edit"]
    # reject：给模型的拒绝理由；respond：用户的回答文本
    message: str | None = None
    # edit：改写后的工具调用（API 保留能力，前端 UI 暂不提供）
    edited_action: dict | None = None


class ResumeBody(BaseModel):
    decisions: list[DecisionBody] = Field(min_length=1)


@router.post("/runs/{rid}/cancel", status_code=202)
async def cancel(rid: str):
    run = db.get_run(rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    if run["status"] != "running":
        raise HTTPException(status_code=409, detail=f"该任务不在执行中（当前状态：{run['status']}）")
    if not request_cancel(rid):
        # 状态仍为 running 但本进程无执行体（极端窗口：恰好在此刻收尾）——按已结束处理
        raise HTTPException(status_code=409, detail="该任务已结束或正在收尾")
    logger.info("run %s 收到用户停止请求", rid)
    return {"ok": True, "run_id": rid}


@router.post("/runs/{rid}/resume", status_code=202)
async def resume(rid: str, body: ResumeBody):
    run = db.get_run(rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    if run["status"] != "waiting_input":
        raise HTTPException(status_code=409, detail="该任务不在等待用户输入状态")

    # 中间件要求 decision 与被拦截的 tool call 一一对应（顺序一致）
    try:
        requests = json.loads(run["interrupt"] or "[]")
    except ValueError:
        requests = []
    if len(body.decisions) != len(requests):
        raise HTTPException(
            status_code=422,
            detail=f"需要 {len(requests)} 个决策（对应 {len(requests)} 个待确认动作），收到 {len(body.decisions)} 个",
        )

    decisions = [d.model_dump(exclude_none=True) for d in body.decisions]
    # respond = 用户回答：同步落一条 user message，保持「messages 表是记忆恢复源」
    # 的完整（checkpoint 里是合成 ToolMessage，重建记忆时才不丢用户的回答）
    for d in decisions:
        if d.get("type") == "respond" and (d.get("message") or "").strip():
            db.create_user_message(run["conversation_id"], d["message"].strip())

    db.resume_run(rid)
    asyncio.create_task(
        run_stream(
            run["conversation_id"],
            rid,
            resume_decisions=decisions,
            start_seq=run["last_seq"],
        )
    )
    logger.info("run %s 已按用户裁决续跑（%s）", rid, ",".join(d["type"] for d in decisions))
    return {"ok": True, "run_id": rid}
