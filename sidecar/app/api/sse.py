"""SSE 事件流端点（PRD §5.5）。

客户端用 @microsoft/fetch-event-source 订阅。断线重连策略：重新 GET /messages 拉全量 +
重新订阅，不做 Last-Event-ID 补发。每 15 秒发一次 `event: ping` 心跳。
"""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .. import bus, db, events

router = APIRouter()

PING_INTERVAL = 15.0

# 流式增量微合批（2026-09-08）：agent.token/agent.reasoning 是 token 级高频事件
# （8 路子代理并发实测 ~320 帧/s），每帧都要过 sse-starlette 编码 + TCP 写 +
# WKWebView 网络进程逐帧跨进程转发 + 页面逐条 JSON.parse——四层成本与帧数成正比。
# 发送层把窗口内**连续**的同流增量合并成一帧（text 拼接、seq 取最大），线上帧数
# ~30 倍↓（行业标配做法，AI SDK experimental_throttle 同思路）。合并帧带 additive
# `seq_from`（本帧首个 seq），前端据此区分「合并跳号」与「真丢事件」（后者才对账）。
_COALESCE_WINDOW = 0.1
_COALESCE_MAX = 200


def _coalesce_stream_events(items: list[dict]) -> list[dict]:
    """把批次内的流式增量按**段**分组合并：以非流式事件（tool/todo/边界帧）为界
    切段，段内 agent.token 归一组、agent.reasoning 按 (run, agent_id) 各归一组——
    text 拼接、seq 取组内最大值、seq_from=组内首个 seq。8 路并发的增量是交错到达
    的，只合并「连续同类」几乎合不动；段内跨流重排无害（token 与各子代理思考
    写互不依赖的缓冲），封段语义由段边界保证（段内增量全属于上一个边界之前）。
    非流事件原样透传（同一 dict 引用，不改不复制）。"""
    out: list[dict] = []
    seg: list[dict] = []

    def _flush_seg() -> None:
        if not seg:
            return
        groups: dict[tuple, dict] = {}
        order: list[tuple] = []
        for item in seg:
            data = item["data"]
            if item["event"] == events.EVENT_TOKEN:
                key = (events.EVENT_TOKEN, data.get("run_id"))
            else:
                key = (events.EVENT_REASONING, data.get("run_id"), data.get("agent_id"))
            group = groups.get(key)
            if group is None:
                # 复制再入组：绝不改动 bus 侧原 dict；seq_from 定格在创建时——
                # 此刻 seq 尚未被组内后续最大值覆盖（组内首条即最小 seq）
                d = dict(data)
                d["seq_from"] = data.get("seq_from", data.get("seq"))
                groups[key] = group = {"event": item["event"], "data": d}
                order.append(key)
            else:
                g = group["data"]
                g["text"] += data.get("text") or ""
                if isinstance(data.get("seq"), int):
                    g["seq"] = data["seq"]
        for key in order:
            out.append({"event": groups[key]["event"], "data": groups[key]["data"]})
        seg.clear()

    for item in items:
        if item["event"] in (events.EVENT_TOKEN, events.EVENT_REASONING):
            seg.append(item)
        else:
            _flush_seg()
            out.append(item)
    _flush_seg()
    return out


def _frame(event: str, data: dict) -> dict:
    """sse-starlette 对 dict 的 data 会用 str()（Python repr，单引号）——不是合法 JSON。
    这里预先 json.dumps 成字符串，保证 §5.5 契约 data: <json>。"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def _started_at_ms(run: dict) -> int | None:
    """runs.created_at（db._now 的 UTC ISO）→ epoch ms。run.state 的 started_at 数据源。"""
    try:
        return int(datetime.fromisoformat(run["created_at"]).timestamp() * 1000)
    except (KeyError, ValueError):
        return None


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
                # 真实起点（epoch ms）：重连恢复 running 态的活卡计时续算而非重算
                "started_at": _started_at_ms(run),
            }
            # 与 agent.error 同款 additive code（取值域 2026-09-08 扩展）：优先读
            # runs.error_code 列（新库），NULL 回退旧字符串判定（迁移前的 cancelled
            # 数据只存了文案）——刷新/重连后经对账事件恢复时同样正确呈现
            code = run.get("error_code")
            if (
                not code
                and run["status"] == "error"
                and run["error"] == events.CANCELLED_MESSAGE
            ):
                code = "cancelled"
            if code:
                data["code"] = code
            # HITL 对账：waiting_input 附审批/问答快照，客户端据此恢复 InterruptCard
            if run["status"] == "waiting_input":
                try:
                    data["requests"] = json.loads(run["interrupt"] or "[]")
                except ValueError:
                    data["requests"] = []
            yield _frame(events.EVENT_RUN_STATE, data)
        while True:
            try:
                first = await asyncio.wait_for(q.get(), timeout=PING_INTERVAL)
            except asyncio.TimeoutError:
                yield _frame("ping", {})
                continue
            # 微合批窗口：首条到达即起表，100ms 内继续积攒（封顶 _COALESCE_MAX 条，
            # 洪峰下即满即发），期末把批次过合并函数逐帧下发。首帧延迟上界 +100ms
            # （低于前端 200ms 渲染节流，不可感）；ping 语义不变（窗口仅在首条后打开）。
            batch = [first]
            loop = asyncio.get_running_loop()
            deadline = loop.time() + _COALESCE_WINDOW
            while len(batch) < _COALESCE_MAX:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(q.get(), timeout=remaining))
                except asyncio.TimeoutError:
                    break
            for item in _coalesce_stream_events(batch):
                yield _frame(item["event"], item["data"])
    finally:
        bus.unsubscribe(cid, q)


@router.get("/conversations/{cid}/events")
async def stream_events(cid: str):
    if not db.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    # 库级注释 ping 保持默认 15s，勿传 ping=0：sse-starlette 3.4.8 文档称「0 禁用」，
    # 实现里 0 = 间隔 0 秒——心跳任务 anyio.sleep(0) 死循环，实测每秒发约 7,250 条
    # `: ping` 注释帧（≈290KB/s/条连接），WKWebView 网络进程被吃满核、整机卡顿
    # （2026-09-08 事故）。keepalive 由 _event_generator 的 wait_for 超时分支发
    # 应用层 event: ping；库注释 ping 与之并存（合计 2 帧/15s）无感。
    return EventSourceResponse(_event_generator(cid))
