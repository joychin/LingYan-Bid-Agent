"""GET /runs/{rid}/snapshot：运行中过程快照（SSE 断线/页面重挂对账）。

live 快照来自 sidecar 进程内存（_run_agent_stream 在结构性事件边界更新），无 live
时回退 run_traces 落库快照；两者皆无返回空树。只读端点，不产生消息、不改变 run 状态。
"""

from app import agent as agent_mod
from app import db
from tests.util import create_conversation


def test_snapshot_prefers_live_trace(client):
    conv = create_conversation(client)
    rid = db.create_run(conv["id"])["id"]
    agent_mod.set_live_trace(
        rid,
        {
            "tools": [
                {
                    "id": "c1", "tool": "task", "args": {"description": "检索"}, "status": "running",
                    "summary": "", "error": None, "tool_call_id": "c1", "reasoning": "", "text": "",
                    "children": [], "startedAt": 1, "endedAt": None,
                }
            ],
            "todos": [{"content": "检索", "status": "in_progress"}],
            "reasoning": "主代理思考",
        },
    )
    try:
        r = client.get(f"/api/runs/{rid}/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == rid
        assert data["conversation_id"] == conv["id"]
        assert data["status"] == "running"
        assert data["tools"][0]["tool"] == "task"
        assert data["todos"][0]["content"] == "检索"
        assert data["reasoning"] == "主代理思考"
    finally:
        agent_mod.clear_live_trace(rid)


def test_snapshot_falls_back_to_persisted_trace(client):
    conv = create_conversation(client)
    rid = db.create_run(conv["id"])["id"]
    msg = db.append_assistant_message(conv["id"], "半截\n\n（等待你的输入…）")
    db.save_run_trace(rid, conv["id"], msg["id"], [{"id": "c1", "tool": "ls"}], [], None, "")
    data = client.get(f"/api/runs/{rid}/snapshot").json()
    assert data["tools"][0]["tool"] == "ls"
    assert data["status"] == "running"


def test_snapshot_empty_when_no_trace(client):
    conv = create_conversation(client)
    rid = db.create_run(conv["id"])["id"]
    data = client.get(f"/api/runs/{rid}/snapshot").json()
    assert data["tools"] == []
    assert data["todos"] == []
    assert data["status"] == "running"


def test_snapshot_404_for_unknown_run(client):
    assert client.get("/api/runs/r_nope/snapshot").status_code == 404
