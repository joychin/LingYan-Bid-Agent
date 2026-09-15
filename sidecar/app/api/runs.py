"""Run 端点：HITL 裁决续跑 + 用户主动停止 + 终态断点续跑。

run.interrupt 暂停（status=waiting_input）后，用户在前端做出 decision
（approve / reject+理由 / respond=回答 / edit），经本端点以
Command(resume={"decisions": [...]}) 从 checkpoint 的 interrupt 处续跑同一 run。
stop 端点对 running 的 run 置位协作式取消事件，worker 线程在下一个流事件边界退出
（半截回复落库 + run 标 error「任务已停止」，语义同既有中断路径）；对
waiting_input 的 run 走逃生口分支——无活 worker，直接落 cancelled 终态
（暂停消息标记改「任务中断」+ 发 agent.error code=cancelled），与 resume
经条件 UPDATE 互斥抢占。
continue 端点（2026-09-12）对 error 终态且定性可续（interrupted/llm_unavailable/
llm_auth）的 run 从 checkpoint 断点续跑：不重发消息、已完成的工作不重跑——
误杀进程/服务不稳耗尽后长任务不再只能整轮重开（重新执行重发消息=新 run 兜底仍在）。
"""

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import agent, bg, db, events, model_ping
from .. import config as cfg
from ..agent import _frozen_ctx_cleanup, get_run_snapshot, request_cancel, run_stream
from ..bus import publish as bus_publish

logger = logging.getLogger(__name__)

router = APIRouter()

# 错误 detail 里 runs 状态枚举的人话（未知值回退原样，防未来新增状态漏译）
_STATUS_LABELS = {
    "running": "执行中",
    "waiting_input": "等待输入",
    "completed": "已完成",
    "error": "出错",
}


class DecisionBody(BaseModel):
    # langchain HITL 四种决策（与 HumanInTheLoopMiddleware 的 Decision 一致）
    type: Literal["approve", "reject", "respond", "edit"]
    # reject：给模型的拒绝理由；respond：用户的回答文本
    message: str | None = None
    # edit：改写后的工具调用（API 保留能力，前端 UI 暂不提供）
    edited_action: dict | None = None


class ResumeBody(BaseModel):
    decisions: list[DecisionBody] = Field(min_length=1)


def _resume_map(requests: list, decisions: list) -> dict | None:
    """多中断恢复映射 {interrupt_id: {"decisions": [子集]}}（langgraph 硬要求）。

    同一轮多个 ask_human 各产生一个 pending Interrupt，恢复值必须是 {中断id: 值}
    映射（langgraph _loop：非映射且 pending>1 直接 RuntimeError）。快照里全部条目
    都带 interrupt_id（2026-09-06 起归一化附上）才组装映射；旧快照无 id 返回 None，
    走单中断兼容的 {"decisions": [...]} 旧格式。
    """
    if not requests or not all(isinstance(r, dict) and r.get("interrupt_id") for r in requests):
        return None
    grouped: dict[str, dict] = {}
    for r, d in zip(requests, decisions):
        iid = r["interrupt_id"]
        grouped.setdefault(iid, {"decisions": []})["decisions"].append(d)
    return grouped


@router.get("/runs/active")
async def active_runs():
    """占用中的 run 清单（running/waiting_input）：侧栏跨会话状态指示的轻量轮询端点。"""
    return {"runs": db.list_active_runs()}


@router.get("/runs/{rid}/snapshot")
async def snapshot(rid: str):
    """运行中过程快照：供 SSE 断线/页面重挂恢复 task 卡，不产生消息或执行。"""
    run = db.get_run(rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    # 快照读取含整树 deepcopy（get_live_trace 自带锁、线程安全）：挪出事件循环，
    # 避免大 run 期间对账拉取阻塞 SSE 心跳与其余请求（FastAPI 官方 async 纪律）
    data = await asyncio.get_running_loop().run_in_executor(
        None, get_run_snapshot, rid
    ) or {
        "run_id": rid,
        "tools": [],
        "todos": [],
        "reasoning": "",
    }
    return {
        **data,
        "conversation_id": run["conversation_id"],
        "status": run["status"],
        "last_seq": run.get("last_seq"),
    }


@router.post("/runs/{rid}/cancel", status_code=202)
async def cancel(rid: str):
    run = db.get_run(rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    if run["status"] == "waiting_input":
        # 等待中的逃生口（2026-09-08）：无活 worker（暂停存活于 checkpoint），
        # 直接落 cancelled 终态。条件 UPDATE 与 resume 互斥抢占——用户恰在此刻
        # 提交回答则本分支输，回 409（与 resume 撞 cancel 对偶）。终态事件由本
        # 端点发（agent.error + code=cancelled，前端中性灰「重新执行」已就绪）
        seq = int(run.get("last_seq") or 0) + 1
        if not db.cancel_waiting_run(rid, events.CANCELLED_MESSAGE, seq):
            raise HTTPException(status_code=409, detail="该任务不在等待用户输入状态")
        db.retire_pause_marker(run.get("pause_msg_id"))
        # 终态清冻结块（与 worker 的 finish_run 清理同口径）
        _frozen_ctx_cleanup(rid)
        await bus_publish(
            run["conversation_id"],
            {
                "event": "agent.error",
                "data": events.error_payload(
                    rid, run["conversation_id"], events.CANCELLED_MESSAGE, "cancelled", seq
                ),
            },
        )
        logger.info("run %s 用户放弃等待（waiting_input → cancelled）", rid)
        return {"ok": True, "run_id": rid}
    if run["status"] != "running":
        status_label = _STATUS_LABELS.get(run["status"], run["status"])
        raise HTTPException(status_code=409, detail=f"该任务不在执行中（当前状态：{status_label}）")
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
            detail=f"需要 {len(requests)} 项决定（对应 {len(requests)} 个待确认操作），收到 {len(body.decisions)} 项",
        )

    decisions = [d.model_dump(exclude_none=True) for d in body.decisions]
    # 先条件抢占置 running（resume_run 内 WHERE status='waiting_input'，返回 False
    # 即已被裁决/状态漂移 → 409），再落 respond 用户消息、spawn 续跑 worker。
    # 抢占成功后的任何失败必须收尸（2026-09-10 review）：无 worker 的 running run
    # 会把会话 409 钉死到重启
    if not db.resume_run(rid):
        raise HTTPException(status_code=409, detail="该任务不在等待用户输入状态")
    try:
        # respond = 用户回答：同步落一条 user message，保持「messages 表是记忆恢复源」
        # 的完整（checkpoint 里是合成 ToolMessage，重建记忆时才不丢用户的回答）
        for d in decisions:
            if d.get("type") == "respond" and (d.get("message") or "").strip():
                # run_id 关联：回答与暂停消息同属一个回合（前端按 run 聚合）
                db.create_user_message(run["conversation_id"], d["message"].strip(), rid=rid)
    except Exception:
        logger.exception("续跑回答落库失败（rid=%s）", rid)
        try:
            db.finish_run_if_running(rid, "error", "回答落库失败，请重试")
        except Exception:
            logger.exception("幽灵 run 收尸失败（rid=%s）", rid)
        raise

    bg.spawn_background(
        run_stream(
            run["conversation_id"],
            rid,
            resume_decisions=decisions,
            start_seq=run["last_seq"],
            # 续跑沿用首段档位/模型（旧库空串兜底 low / default），客户端无需重传
            thinking=run.get("thinking") or "low",
            model=run.get("model") or None,
            resume_payload=_resume_map(requests, decisions),
        )
    )
    logger.info("run %s 已按用户裁决续跑（%s）", rid, ",".join(d["type"] for d in decisions))
    return {"ok": True, "run_id": rid}


async def _preflight_ping(model_id: str | None) -> str | None:
    """续跑预检：模型不可用返回人话文案（409 detail 用）；可用/无法判定返回 None。

    fail-open：profile 已删、Key 走 env、探活自身异常都放行——预检只挡「确定
    还会再死一次」的情形（欠费/Key 失效/连不上），不做第二道门禁。
    """
    try:
        profile = cfg.get_profile(model_id or cfg.default_model_id())
        if profile is None:
            return None  # 模型配置已删：留给 run_stream 按原路径报错，不在此拦截
        key = cfg.model_key(profile.id)
        if not key:
            return "模型 Key 未配置——请先在设置里填写"
        ok, message, _latency = await asyncio.to_thread(
            model_ping.ping, profile.base_url, profile.model, key
        )
        return None if ok else message
    except Exception:
        logger.debug("续跑预检失败，跳过（fail-open）", exc_info=True)
        return None


@router.post("/runs/{rid}/continue", status_code=202)
async def continue_run(rid: str):
    """终态断点续跑（2026-09-12）：error 终态且定性可续（db.RESUMABLE_ERROR_CODES）
    的 run 直接从 checkpoint 续跑——无新输入、已完成的工作不重跑，worker 以
    input=None 恢复 pending 任务（与断流重试同机制；悬空 tool_calls 由
    PatchToolCalls 在开头自愈）。

    前置：① 必须仍是会话最新 run（其后有新消息/新 run 说明会话已前进，续旧 run
    会让模型记忆分叉）；② 会话无占用中 run；③ checkpoint 存在（agent.db 损坏/
    重建后 thread 缺失时提前挡掉，给「请重新执行」的明确出路）。
    条件 UPDATE 抢占（continue_run 内 WHERE error+code），并发双击一对一输 409。
    """
    run = db.get_run(rid)
    if run is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    if run["status"] != "error":
        status_label = _STATUS_LABELS.get(run["status"], run["status"])
        raise HTTPException(status_code=409, detail=f"该任务不在可续跑状态（当前状态：{status_label}）")
    if run.get("error_code") not in db.RESUMABLE_ERROR_CODES:
        raise HTTPException(status_code=409, detail="该任务不支持从断点继续，可重新执行")
    latest = db.get_latest_run(run["conversation_id"])
    if not latest or latest["id"] != rid:
        raise HTTPException(status_code=409, detail="该任务之后已有新的对话内容，请重新执行")
    if db.active_run_exists(run["conversation_id"]):
        raise HTTPException(status_code=409, detail="该会话已有进行中的任务")
    if not agent.checkpoint_exists(run["conversation_id"]):
        raise HTTPException(status_code=409, detail="断点数据缺失，请重新执行")
    # 模型探活预检（2026-09-15 路径可靠性批）：在抢占前先确认模型服务可用——
    # r_eedd621716b5 两次续跑撞 402 各 1 秒即死、报错看不出是欠费，用户空点两轮。
    # 置于 db.continue_run 之前：失败不动 run 行（无需收尸）。fail-open：profile
    # 已删/ping 自身炸 → 跳过检查照常续跑（增强逻辑绝不打断主流程）。
    preflight = await _preflight_ping(run.get("model"))
    if preflight is not None:
        raise HTTPException(status_code=409, detail=f"模型暂不可用，未启动续跑：{preflight}")
    if not db.continue_run(rid):
        raise HTTPException(status_code=409, detail="该任务已在别处续跑，请稍候")
    try:
        bg.spawn_background(
            run_stream(
                run["conversation_id"],
                rid,
                continue_from_checkpoint=True,
                start_seq=run["last_seq"],
                # 续跑沿用首段档位/模型（旧库空串兜底 low / default）
                thinking=run.get("thinking") or "low",
                model=run.get("model") or None,
            )
        )
    except Exception:
        # 抢占成功后的任何失败必须收尸（同 resume 端点纪律）：无 worker 的 running
        # run 会把会话 409 钉死到重启
        logger.exception("续跑 worker 启动失败（rid=%s）", rid)
        try:
            db.finish_run_if_running(rid, "error", "续跑启动失败，请重试")
        except Exception:
            logger.exception("幽灵 run 收尸失败（rid=%s）", rid)
        raise HTTPException(status_code=500, detail="续跑启动失败，请重试")
    logger.info("run %s 从断点继续（此前定性 %s）", rid, run.get("error_code"))
    return {"ok": True, "run_id": rid}
