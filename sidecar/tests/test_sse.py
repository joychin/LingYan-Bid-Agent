"""SSE 端点：连接建立时下发的 run.state 对账事件。"""

import asyncio
import json


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

    cid = client.post("/api/conversations", json={}).json()["id"]
    rid = db.create_run(cid)["id"]

    frame = _first_frame(cid)
    assert frame["event"] == "run.state"
    data = json.loads(frame["data"])
    assert data == {
        "run_id": rid,
        "conversation_id": cid,
        "status": "running",
        "error": None,
    }


def test_run_state_carries_terminal_status(client):
    from app import db

    cid = client.post("/api/conversations", json={}).json()["id"]
    rid = db.create_run(cid)["id"]
    db.finish_run(rid, "error", "LLM_API_KEY 未设置")

    frame = _first_frame(cid)
    data = json.loads(frame["data"])
    assert data["status"] == "error"
    assert data["error"] == "LLM_API_KEY 未设置"


def test_run_state_omitted_when_no_runs(client, monkeypatch):
    """从无 run 的会话：第一帧应是 ping（无对账事件可发）。"""
    from app.api import sse as sse_mod

    monkeypatch.setattr(sse_mod, "PING_INTERVAL", 0.05)
    cid = client.post("/api/conversations", json={}).json()["id"]

    frame = _first_frame(cid)
    assert frame["event"] == "ping"
