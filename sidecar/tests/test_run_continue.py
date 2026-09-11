"""终态断点续跑（POST /runs/{rid}/continue，2026-09-12）。

error 终态且定性可续（interrupted/llm_unavailable/llm_auth）的 run 从 checkpoint
断点续跑：不重发消息、已完成的工作不重跑。覆盖端点前置矩阵（状态/定性/最新 run/
占用/checkpoint 预检/并发双击）与 run_stream 的 continue 模式（input=None +
agent.started 照发）。
"""

import asyncio
import time

from app import agent as agent_mod
from app import bus, db
from app.api import runs as runs_api


def _wait_captured(captured, key):
    for _ in range(200):
        if key in captured:
            return
        time.sleep(0.01)


def _error_setup(tmp_path, monkeypatch, code="interrupted", error="应用服务重启，任务被中断"):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    run = db.create_run(conv["id"], thinking="high", model="p2")
    db.finish_run(run["id"], "error", error, last_seq=7, error_code=code)
    return conv["id"], run["id"]


def test_continue_endpoint_flow(client, tmp_path, monkeypatch):
    cid, rid = _error_setup(tmp_path, monkeypatch)
    captured: dict = {}

    async def fake_run_stream(
        cid_, rid_, user_text=None, resume_decisions=None, start_seq=0,
        thinking="low", model=None, resume_payload=None, continue_from_checkpoint=False,
    ):
        captured.update(
            cid=cid_, rid=rid_, user_text=user_text, start_seq=start_seq,
            thinking=thinking, model=model, continue_from_checkpoint=continue_from_checkpoint,
        )

    monkeypatch.setattr(runs_api, "run_stream", fake_run_stream)
    # checkpoint 预检放行（真实 agent.db 由 run_stream 惰性建——预检只认已有 thread）
    monkeypatch.setattr(agent_mod, "checkpoint_exists", lambda c: True)

    # 404：不存在的 run
    assert client.post("/api/runs/r_none/continue").status_code == 404
    # 202：抢占翻转 + 续段参数透传（start_seq 接终态 last_seq、档位/模型沿用存档）
    resp = client.post(f"/api/runs/{rid}/continue")
    assert resp.status_code == 202
    _wait_captured(captured, "continue_from_checkpoint")
    assert captured["rid"] == rid
    assert captured["continue_from_checkpoint"] is True
    assert captured["start_seq"] == 7
    assert captured["thinking"] == "high"
    assert captured["model"] == "p2"
    row = db.get_run(rid)
    assert row["status"] == "running"
    assert row["error"] is None and row["error_code"] is None
    # 409：已转 running，再 continue 拒绝（并发双击同款——条件 UPDATE 输家）
    assert client.post(f"/api/runs/{rid}/continue").status_code == 409


def test_continue_preconditions(client, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_mod, "checkpoint_exists", lambda c: True)

    # ① 非 error 状态：waiting_input → 409（带状态人话）
    cid, rid = _error_setup(tmp_path, monkeypatch)
    db.interrupt_run(rid, [{"tool": "ask_human", "args": {"question": "Q"}, "allowed": ["respond"]}], 3)
    resp = client.post(f"/api/runs/{rid}/continue")
    assert resp.status_code == 409
    assert "等待输入" in resp.json()["detail"]

    # ② 定性不可续：cancelled（尊重用户停止意图）→ 409
    cid2, rid2 = _error_setup(tmp_path, monkeypatch, code="cancelled", error="任务已停止")
    resp = client.post(f"/api/runs/{rid2}/continue")
    assert resp.status_code == 409
    assert "不支持从断点继续" in resp.json()["detail"]

    # ③ 非会话最新 run（之后有新 run）→ 409
    cid3, rid3 = _error_setup(tmp_path, monkeypatch)
    db.create_run(cid3)
    resp = client.post(f"/api/runs/{rid3}/continue")
    assert resp.status_code == 409
    assert "新的对话内容" in resp.json()["detail"]

    # ④ 会话有占用中 run：最新 run 自身 waiting_input 时同被 ③ 拦（占用检查是
    #    纵深防御——单会话至多一条占用由发消息 409 守卫保证，latest 检查先命中）
    cid4, rid4 = _error_setup(tmp_path, monkeypatch)
    db.interrupt_run(db.create_run(cid4)["id"], [{"tool": "ask_human", "args": {"question": "Q"}, "allowed": ["respond"]}], 1)
    resp = client.post(f"/api/runs/{rid4}/continue")
    assert resp.status_code == 409
    assert "新的对话内容" in resp.json()["detail"]

    # ⑤ checkpoint 缺失（agent.db 损坏/重建场景）→ 409，run 保持 error 不被翻转
    cid5, rid5 = _error_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_mod, "checkpoint_exists", lambda c: False)
    resp = client.post(f"/api/runs/{rid5}/continue")
    assert resp.status_code == 409
    assert "断点数据缺失" in resp.json()["detail"]
    assert db.get_run(rid5)["status"] == "error"


def test_run_stream_continue_mode(tmp_path, monkeypatch):
    """continue 分支：input=None（断点重拉，与断流重试同款）、agent.started 照发、
    无用户消息写入（转录不被注入空输入）。"""
    from langchain_core.messages import AIMessageChunk

    class _StubAgent:
        def __init__(self, items):
            self._items = items
            self.inputs: list = []

        def stream(self, inp, config=None, stream_mode=None, subgraphs=None):
            self.inputs.append(inp)
            return iter(self._items)

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    rid = db.create_run(conv["id"])["id"]
    db.create_user_message(conv["id"], "原指令", rid=rid)

    stub = _StubAgent([("messages", (AIMessageChunk(content="续跑完成"), {}))])

    async def fake_get_agent(profile_id=None):
        return stub

    monkeypatch.setattr(agent_mod, "get_agent", fake_get_agent)

    async def scenario():
        q = bus.subscribe(conv["id"])
        await agent_mod.run_stream(
            conv["id"], rid, continue_from_checkpoint=True, start_seq=7, thinking="low"
        )
        out = []
        while not q.empty():
            e = q.get_nowait()
            out.append((e["event"], e["data"]))
        bus.unsubscribe(conv["id"], q)
        return out

    out = asyncio.run(scenario())
    # input=None：langgraph 从 checkpoint 恢复 pending 任务（非 user 消息、非 Command）
    assert stub.inputs[0] is None
    # started 照发且 seq 接上一段（start_seq+1），自然收尾到 completed
    assert out[0][0] == "agent.started" and out[0][1]["seq"] == 8
    assert out[-1][0] == "agent.completed"
    # 转录只多最终回复：无新的用户消息被注入
    msgs = db.list_messages(conv["id"])
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["原指令"]
    assert msgs[-1]["content"] == "续跑完成"
