"""HITL（human-in-the-loop）全链路单测。

覆盖：events 捕获 __interrupt__ → run_stream 转 waiting_input（半截消息/trace/
快照/last_seq 落库 + run.interrupt 事件）→ resume 端点（状态校验/决策数校验/
respond 落 user message/续段 seq 续接）→ 旧库 runs 表 CHECK 迁移 →
重启恢复不翻 waiting_input。
"""

import asyncio
import json
import sqlite3
import time

from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.types import Command, Interrupt

from app import agent as agent_mod
from app import db, events
from app.api import runs as runs_api
from app.config import app_db_path


def _make_interrupt(question: str = "用哪个方案？") -> Interrupt:
    """构造 HumanInTheLoopMiddleware 会发出的 HITLRequest 中断。"""
    return Interrupt(
        value={
            "action_requests": [
                {"name": "ask_human", "args": {"question": question}, "description": "确认方案"}
            ],
            "review_configs": [
                {"action_name": "ask_human", "allowed_decisions": ["respond"]}
            ],
        }
    )


# ---------- events.iter_stream：__interrupt__ 捕获 ----------


def test_iter_stream_parses_interrupt():
    stream = iter([("updates", {"__interrupt__": (_make_interrupt(),)})])
    out = list(events.iter_stream(stream))
    assert out == [
        (
            "interrupt",
            {
                "requests": [
                    {
                        "tool": "ask_human",
                        "args": {"question": "用哪个方案？"},
                        "description": "确认方案",
                        "allowed": ["respond"],
                    }
                ]
            },
        )
    ]


def test_iter_stream_interrupt_not_dropped_as_update():
    """__interrupt__ 的值是元组：不专门处理会掉进 update 解析被静默丢弃（回归防线）。"""
    stream = iter([("updates", {"__interrupt__": (_make_interrupt(),)})])
    kinds = [k for k, _ in events.iter_stream(stream)]
    assert "interrupt" in kinds and "tool_called" not in kinds


def _template_interrupt(name: str, args: dict) -> Interrupt:
    """langchain HITL 中间件的默认 description（英文模板 + 完整 args repr）。"""
    return Interrupt(
        value={
            "action_requests": [
                {
                    "name": name,
                    "args": args,
                    "description": f"Tool execution requires approval\nTool: {name}\nArgs: {args!r}",
                }
            ],
            "review_configs": [],
        }
    )


def test_hitl_template_description_rewritten_for_task():
    """task 派发审批卡的默认模板 description 重写为人话摘要（args 原样保留）。"""
    out = events._hitl_requests(
        (
            _template_interrupt(
                "task",
                {
                    "description": "为「商务标书」生成目录（R2 初稿 + 三道清理）。\n你是执行单元，请先阅读规则文件。",
                    "subagent_type": "tender-outline-writer",
                },
            ),
        )
    )
    [req] = out["requests"]
    assert req["description"] == "派出子代理（tender-outline-writer）：为「商务标书」生成目录（R2 初稿 + 三道清理）。"
    assert req["args"]["subagent_type"] == "tender-outline-writer"


def test_hitl_template_description_rewritten_for_generic_tool():
    out = events._hitl_requests((_template_interrupt("fetch_url", {"url": "https://x"}),))
    [req] = out["requests"]
    assert req["description"] == "执行工具 fetch_url，需要你的批准"


def test_hitl_custom_description_passthrough():
    """skill 自拟的中文 description（非模板前缀）原样透传，不受重写影响。"""
    out = events._hitl_requests((_make_interrupt(),))
    [req] = out["requests"]
    assert req["description"] == "确认方案"


# ---------- run_stream：中断边界 ----------


class _StubAgent:
    def __init__(self, items):
        self._items = items
        self.inputs: list = []

    def stream(self, inp, config=None, stream_mode=None, subgraphs=None):
        self.inputs.append(inp)
        return iter(self._items)


def _drive_run_stream(monkeypatch, stub, cid, rid, **kwargs):
    """订阅 bus 队列跑一遍 run_stream，返回产出的事件 [(event, data)]。"""

    async def fake_get_agent(profile_id=None):
        return stub

    monkeypatch.setattr(agent_mod, "get_agent", fake_get_agent)

    from app import bus

    async def scenario():
        q = bus.subscribe(cid)
        await agent_mod.run_stream(cid, rid, **kwargs)
        out = []
        while not q.empty():
            e = q.get_nowait()
            out.append((e["event"], e["data"]))
        bus.unsubscribe(cid, q)
        return out

    return asyncio.run(scenario())


def _setup_conv(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("测试任务")
    conv = db.create_conversation(task["id"], "会话")
    run = db.create_run(conv["id"])
    return conv["id"], run["id"]


def test_run_stream_interrupt_transitions_to_waiting(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    gated = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {"description": "调研 OpenAI"}, "id": "t1"}],
    )
    items = [
        ("messages", (AIMessageChunk(content="我先确认一下"), {})),
        # task 被门禁拦下前 tool.called 已流出（模型节点先于 HITL 节点提交）→ running 步骤入树
        ("updates", {"model": {"messages": [gated]}}),
        ("updates", {"__interrupt__": (_make_interrupt(),)}),
    ]
    stub = _StubAgent(items)
    out = _drive_run_stream(monkeypatch, stub, cid, rid, user_text="hi")

    names = [e for e, _ in out]
    assert names[0] == "agent.started"
    assert "agent.token" in names
    assert "tool.called" in names
    assert names[-1] == "run.interrupt"
    data = out[-1][1]
    assert data["requests"][0]["tool"] == "ask_human"
    assert data["requests"][0]["allowed"] == ["respond"]
    assert isinstance(data["seq"], int) and data["seq"] >= 3

    # runs 行：waiting_input + 快照 + last_seq（= run.interrupt 事件的 seq）
    row = db.get_run(rid)
    assert row["status"] == "waiting_input"
    assert json.loads(row["interrupt"])[0]["tool"] == "ask_human"
    assert row["last_seq"] == data["seq"]

    # 半截回复落库（带等待标记）+ trace 落库；被拦下的 running 步骤改标 paused（不永远转圈）
    msgs = db.list_messages(cid)
    partial = [m for m in msgs if m["role"] == "assistant" and "等待你的输入" in m["content"]]
    assert partial
    trace = db.get_traces_for_messages([partial[0]["id"]])[partial[0]["id"]]
    assert trace["tools"][0]["tool"] == "task"
    assert trace["tools"][0]["status"] == "paused"
    assert trace["tools"][0]["endedAt"] is not None


def test_run_stream_resume_segment_continues_seq(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    db.interrupt_run(rid, [{"tool": "ask_human", "args": {}, "allowed": ["respond"]}], last_seq=3)

    items = [("messages", (AIMessageChunk(content="好的，继续"), {}))]
    stub = _StubAgent(items)
    out = _drive_run_stream(monkeypatch, stub, cid, rid, resume_decisions=[{"type": "respond", "message": "方案A"}], start_seq=3)

    # 续段事件序号从 last_seq+1 接上（前端按 run_id 去重，重置会吞掉续段事件）
    assert out[0][0] == "agent.started" and out[0][1]["seq"] == 4
    assert out[-1][0] == "agent.completed"
    # 输入是 Command(resume=...)，不是新 user 消息
    assert isinstance(stub.inputs[0], Command)
    assert stub.inputs[0].resume == {"decisions": [{"type": "respond", "message": "方案A"}]}
    # 续段正常完成：run 转 completed
    assert db.get_run(rid)["status"] == "completed"


# ---------- db：迁移与恢复 ----------


def test_runs_table_migration_from_old_check(tmp_path, monkeypatch):
    """旧库（CHECK 无 waiting_input、无新列）→ init_db 整表迁移，数据保留。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    p = app_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE runs(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,"
        " status TEXT NOT NULL CHECK(status IN ('running','completed','error')),"
        " error TEXT, created_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO runs VALUES('r_old','c_1','completed',NULL,'2026-01-01T00:00:00')")
    conn.commit()
    conn.close()

    db.init_db()
    row = db.get_run("r_old")
    assert row is not None and row["status"] == "completed"  # 数据原样带过
    db.interrupt_run("r_old", [{"tool": "ask_human", "args": {}}], 5)  # 新 CHECK 可写
    assert db.get_run("r_old")["status"] == "waiting_input"
    assert db.get_run("r_old")["last_seq"] == 5


def test_recover_stale_runs_keeps_waiting_input(tmp_path, monkeypatch):
    """重启恢复只翻 running；waiting_input 的 interrupt 活在 checkpoint，仍可续跑。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    r_waiting = db.create_run(conv["id"])
    db.interrupt_run(r_waiting["id"], [], 0)
    r_running = db.create_run(conv["id"])

    assert db.recover_stale_runs() == 1
    assert db.get_run(r_running["id"])["status"] == "error"
    assert db.get_run(r_waiting["id"])["status"] == "waiting_input"


def test_active_run_exists_covers_waiting_input(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    run = db.create_run(conv["id"])
    db.interrupt_run(run["id"], [], 0)
    assert db.active_run_exists(conv["id"]) is True
    db.resume_run(run["id"])
    assert db.active_run_exists(conv["id"]) is True
    db.finish_run(run["id"], "completed")
    assert db.active_run_exists(conv["id"]) is False


# ---------- resume 端点 ----------


def _waiting_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    run = db.create_run(conv["id"])
    db.interrupt_run(run["id"], [{"tool": "ask_human", "args": {"question": "Q"}, "allowed": ["respond"]}], 3)
    return conv["id"], run["id"]


def _wait_captured(captured, key):
    for _ in range(200):
        if key in captured:
            return
        time.sleep(0.01)


def test_resume_endpoint_flow(client, tmp_path, monkeypatch):
    cid, rid = _waiting_setup(tmp_path, monkeypatch)
    captured: dict = {}

    async def fake_run_stream(cid_, rid_, user_text=None, resume_decisions=None, start_seq=0, thinking="low", model=None):
        captured.update(cid=cid_, rid=rid_, resume_decisions=resume_decisions, start_seq=start_seq)

    monkeypatch.setattr(runs_api, "run_stream", fake_run_stream)

    # 404：不存在的 run
    assert client.post("/api/runs/r_none/resume", json={"decisions": [{"type": "approve"}]}).status_code == 404
    # 422：决策数与待确认动作数不一致（快照 1 个，传 2 个）
    resp = client.post(
        f"/api/runs/{rid}/resume",
        json={"decisions": [{"type": "respond", "message": "a"}, {"type": "approve"}]},
    )
    assert resp.status_code == 422
    # 202：respond 决策 → 落 user message、run 转 running、快照清空、续段参数透传
    resp = client.post(
        f"/api/runs/{rid}/resume", json={"decisions": [{"type": "respond", "message": "方案A"}]}
    )
    assert resp.status_code == 202
    _wait_captured(captured, "resume_decisions")
    assert captured["rid"] == rid
    assert captured["resume_decisions"] == [{"type": "respond", "message": "方案A"}]
    assert captured["start_seq"] == 3  # 接 waiting 时的 last_seq
    assert db.get_run(rid)["status"] == "running"
    assert db.get_run(rid)["interrupt"] is None
    assert any(m["role"] == "user" and m["content"] == "方案A" for m in db.list_messages(cid))
    # 409：已转 running，再 resume 拒绝
    assert client.post(f"/api/runs/{rid}/resume", json={"decisions": [{"type": "approve"}]}).status_code == 409


def test_message_post_409_while_waiting(client, tmp_path, monkeypatch):
    cid, rid = _waiting_setup(tmp_path, monkeypatch)
    resp = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    assert resp.status_code == 409
    assert "等待" in resp.json()["detail"]


def test_latest_run_returns_requests_snapshot(client, tmp_path, monkeypatch):
    cid, rid = _waiting_setup(tmp_path, monkeypatch)
    resp = client.get(f"/api/conversations/{cid}/runs/latest").json()["run"]
    assert resp["status"] == "waiting_input"
    assert resp["requests"][0]["tool"] == "ask_human"
