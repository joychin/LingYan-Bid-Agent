"""SSE 端点：连接建立时下发的 run.state 对账事件。"""

import asyncio
import json
from datetime import datetime

from tests.util import create_conversation


def _first_frame(cid):
    """取 _event_generator 的第一帧（随后关闭，触发 finally 反订阅）。"""

    async def run():
        from app.api.sse import _event_generator

        gen = _event_generator(cid)
        try:
            return await gen.__anext__()
        finally:
            await gen.aclose()

    return asyncio.run(run())


def test_run_state_emitted_on_connect(client):
    from app import db

    cid = create_conversation(client)["id"]
    rid = db.create_run(cid)["id"]

    frame = _first_frame(cid)
    assert frame["event"] == "run.state"
    data = json.loads(frame["data"])
    assert data == {
        "run_id": rid,
        "conversation_id": cid,
        "status": "running",
        "error": None,
        # started_at = runs.created_at 换算 epoch ms（客户端重连后计时按真实起点续算）
        "started_at": int(
            datetime.fromisoformat(db.get_run(rid)["created_at"]).timestamp() * 1000
        ),
    }


def test_run_state_carries_terminal_status(client):
    from app import db

    cid = create_conversation(client)["id"]
    rid = db.create_run(cid)["id"]
    db.finish_run(rid, "error", "LLM_API_KEY 未设置")

    frame = _first_frame(cid)
    data = json.loads(frame["data"])
    assert data["status"] == "error"
    assert data["error"] == "LLM_API_KEY 未设置"


def test_run_state_carries_error_code(client):
    """错误定性 code 随 run.state 对账恢复（2026-09-08 additive）：新库读 error_code
    列；列 NULL 的旧数据回退 cancelled 字符串判定。"""
    from app import db

    cid = create_conversation(client)["id"]
    rid = db.create_run(cid)["id"]
    db.finish_run(
        rid, "error",
        "模型服务暂时不可用，已自动重试 3 次仍失败。\n服务方返回：overloaded",
        error_code="llm_unavailable",
    )
    data = json.loads(_first_frame(cid)["data"])
    assert data["code"] == "llm_unavailable"

    # 旧数据（迁移前只有文案、无 error_code）：cancelled 靠字符串比对兜底
    rid2 = db.create_run(cid)["id"]
    from app import events

    db.finish_run(rid2, "error", events.CANCELLED_MESSAGE, error_code=None)
    data2 = json.loads(_first_frame(cid)["data"])
    assert data2["run_id"] == rid2
    assert data2["code"] == "cancelled"


def test_stream_response_keeps_sane_library_ping(client):
    """库级注释 ping 间隔守卫（2026-09-08 卡顿事故回归）：sse-starlette 3.4.8 文档
    称 ping=0 可禁用，实现里 0 = 间隔 0 秒——心跳任务死循环，实测每秒发约 7,250 条
    `: ping` 注释帧（≈290KB/s），把客户端 WKWebView 网络进程吃满核。间隔必须 ≥15s；
    keepalive 语义由应用层 event: ping 承担。"""
    from app.api.sse import stream_events

    cid = create_conversation(client)["id"]

    async def run():
        # 未作为 ASGI app 启动的 EventSourceResponse 只是普通对象，无后台任务要清理
        return (await stream_events(cid)).ping_interval

    assert asyncio.run(run()) >= 15


def test_run_state_omitted_when_no_runs(client, monkeypatch):
    """从无 run 的会话：第一帧应是 ping（无对账事件可发）。"""
    from app.api import sse as sse_mod

    monkeypatch.setattr(sse_mod, "PING_INTERVAL", 0.05)
    cid = create_conversation(client)["id"]

    frame = _first_frame(cid)
    assert frame["event"] == "ping"


# ---- 流式增量微合批（2026-09-08）：连续同流合并、seq_from 标注连续性 ----


def _ev(event: str, seq: int, text: str = "x", agent_id=None) -> dict:
    data: dict = {"run_id": "r1", "conversation_id": "c1", "text": text, "seq": seq}
    if agent_id is not None:
        data["agent_id"] = agent_id
    return {"event": event, "data": data}


def test_coalesce_merges_consecutive_tokens():
    from app.api.sse import _coalesce_stream_events

    out = _coalesce_stream_events([_ev("agent.token", 1, "你"), _ev("agent.token", 2, "好"), _ev("agent.token", 3, "！")])
    assert len(out) == 1
    d = out[0]["data"]
    assert d["text"] == "你好！"
    assert d["seq"] == 3
    assert d["seq_from"] == 1


def test_coalesce_reasoning_requires_same_agent():
    from app.api.sse import _coalesce_stream_events

    out = _coalesce_stream_events(
        [
            _ev("agent.reasoning", 1, "甲", agent_id="t1"),
            _ev("agent.reasoning", 2, "乙", agent_id="t1"),
            _ev("agent.reasoning", 3, "丙", agent_id="t2"),  # 换子代理不合并
            _ev("agent.reasoning", 4, "丁"),  # 主 agent（agent_id None）也不合并
        ]
    )
    assert [f["data"]["text"] for f in out] == ["甲乙", "丙", "丁"]
    assert [f["data"]["seq_from"] for f in out] == [1, 3, 4]
    assert [f["data"]["seq"] for f in out] == [2, 3, 4]


def test_coalesce_single_frame_carries_seq_from_and_passthrough_untouched():
    from app.api.sse import _coalesce_stream_events

    tool = {"event": "tool.called", "data": {"run_id": "r1", "seq": 2}}
    out = _coalesce_stream_events([_ev("agent.token", 1, "a"), tool, _ev("agent.token", 3, "b")])
    # 单条流式帧也带 seq_from==seq；非流事件原样透传（同一 dict 引用，未被复制/改动）
    assert out[0]["data"]["seq_from"] == 1
    assert out[1] is tool
    assert out[2]["data"]["seq_from"] == 3
    # 边界隔断合并：token → tool → token 是三帧，顺序保持
    assert [f["event"] for f in out] == ["agent.token", "tool.called", "agent.token"]


def test_coalesce_groups_interleaved_streams_within_segment():
    """8 路并发下增量交错到达（a1,a2,…,a1,…）：段内按流分组而非只合并连续同类；
    非流事件切段（封段语义边界），边界后的增量属新段独立成帧。"""
    from app.api.sse import _coalesce_stream_events

    out = _coalesce_stream_events(
        [
            _ev("agent.reasoning", 1, "甲", agent_id="t1"),
            _ev("agent.token", 2, "正"),
            _ev("agent.reasoning", 3, "乙", agent_id="t1"),
            _ev("agent.reasoning", 4, "丙", agent_id="t2"),
            _ev("agent.token", 5, "文"),
            {"event": "tool.called", "data": {"run_id": "r1", "seq": 6}},
            _ev("agent.token", 7, "新"),
            _ev("agent.token", 8, "段"),
        ]
    )
    assert [f["event"] for f in out] == [
        "agent.reasoning",
        "agent.token",
        "agent.reasoning",
        "tool.called",
        "agent.token",
    ]
    # 首段三组（首现顺序）：t1 思考合一 / 正文合一 / t2 思考单帧
    assert out[0]["data"]["text"] == "甲乙"
    assert out[0]["data"]["seq"] == 3
    assert out[0]["data"]["seq_from"] == 1
    assert out[1]["data"]["text"] == "正文"
    assert out[1]["data"]["seq_from"] == 2
    assert out[1]["data"]["seq"] == 5
    assert out[2]["data"]["text"] == "丙"
    # 边界后的新段独立成组
    assert out[4]["data"]["text"] == "新段"
    assert out[4]["data"]["seq_from"] == 7
    assert out[4]["data"]["seq"] == 8


def test_generator_coalesces_burst(client, monkeypatch):
    """生成器端到端：同一窗口内的突发经 bus 进来，下发为合并帧（text 拼接、
    seq=max、seq_from=min），tool.called 收尾帧不被合并。"""
    from app import bus
    from app.api import sse as sse_mod

    monkeypatch.setattr(sse_mod, "PING_INTERVAL", 5.0)  # 不被 ping 打断窗口
    cid = create_conversation(client)["id"]

    async def run():
        gen = sse_mod._event_generator(cid)
        frames: list[dict] = []

        async def consume():
            while not any(f["event"] == "tool.called" for f in frames):
                frames.append(await asyncio.wait_for(gen.__anext__(), timeout=2))

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0.05)  # 订阅生效后再发布
        await bus.publish(cid, _ev("agent.token", 1, "a"))
        await bus.publish(cid, _ev("agent.token", 2, "b"))
        await bus.publish(cid, _ev("agent.reasoning", 3, "思", agent_id="t1"))
        await bus.publish(cid, _ev("agent.reasoning", 4, "考", agent_id="t1"))
        await bus.publish(
            cid,
            {"event": "tool.called", "data": {"run_id": "r1", "conversation_id": cid, "tool": "ls", "args": {}, "seq": 5}},
        )
        await asyncio.wait_for(task, timeout=3)
        await gen.aclose()
        return frames

    frames = asyncio.run(run())
    assert [f["event"] for f in frames] == ["agent.token", "agent.reasoning", "tool.called"]
    tok = json.loads(frames[0]["data"])
    assert tok["text"] == "ab" and tok["seq"] == 2 and tok["seq_from"] == 1
    rea = json.loads(frames[1]["data"])
    assert rea["text"] == "思考" and rea["seq"] == 4 and rea["seq_from"] == 3
