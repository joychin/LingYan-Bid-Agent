"""REST DTO 契约测试：真实端点响应逐字段过 contracts.dto 的 pydantic 模型。

DTO 单一事实源 = app/contracts/dto.py（scripts/gen_ts_types.py 生成前端 dto.gen.ts）。
模型不绑 response_model（零运行时行为变化），对齐靠本测试对真实响应 model_validate：
端点响应形状漂移（多键/缺键/类型变）在此挂掉。
"""

import io

from app import db, publish
from app.contracts import dto

KEY = "tender.directory/tender-response-docs@1"


def _content(name="技术部分"):
    return {
        "response_documents": [
            {"name": name, "scope": "", "directory": [{"目录名称": "目录", "level": 1, "children": []}]}
        ]
    }


def _task_conv():
    task = db.create_task("测试任务")
    conv = db.create_conversation(task["id"])
    return task, conv


def _upload_kb(client, name="a.txt", body=b"# t\n\ncontent"):
    return client.post(
        "/api/kb/files",
        files={"file": (name, io.BytesIO(body), "application/octet-stream")},
    )


def test_task_conversation_settings_contracts_dto(client):
    created = client.post("/api/tasks", json={"title": "t"}).json()
    dto.Task.model_validate(created["task"])  # POST 响应是 {task, conversation} 信封
    dto.Conversation.model_validate(created["conversation"])
    task = db.create_task("测试任务2")
    dto.Task.model_validate(task)
    dto.Task.model_validate(client.get("/api/tasks").json()["tasks"][0])

    conv = client.post("/api/conversations", json={"task_id": task["id"]}).json()
    dto.Conversation.model_validate(conv)

    dto.Settings.model_validate(client.get("/api/settings").json())

    for c in client.get("/api/contracts").json()["contracts"]:
        dto.ArtifactContract.model_validate(c)


def test_files_dto(client):
    task, _ = _task_conv()
    r = client.post(
        "/api/files",
        params={"task_id": task["id"]},
        files={"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    dto.UploadResult.model_validate(r.json())
    files = client.get("/api/files", params={"task_id": task["id"]}).json()["files"]
    for f in files:
        dto.FileItem.model_validate(f)


def test_artifact_dto(client):
    task, conv = _task_conv()
    m = publish.publish_artifact(KEY, _content(), conversation_id=conv["id"])
    arts = client.get("/api/artifacts", params={"conversation_id": conv["id"]}).json()["artifacts"]
    assert len(arts) == 1
    dto.Artifact.model_validate(arts[0])
    # artifact.created 载荷同源（events.artifact_created_payload ↔ _to_api 口径一致）
    assert arts[0]["artifact_id"] == m["artifact_id"]


def test_message_dto(client):
    """assistant 消息 + run_traces 回填（tools/todos/durationMs/reasoning）过 Message 模型。"""
    _, conv = _task_conv()
    run = db.create_run(conv["id"])
    msg = db.append_assistant_message(conv["id"], "完成")
    db.save_run_trace(
        run["id"],
        conv["id"],
        msg["id"],
        [{"id": "c1", "tool": "fetch_url", "args": {}, "status": "done", "summary": "ok",
          "error": None, "tool_call_id": "c1", "reasoning": "", "text": "旁白", "children": [],
          "startedAt": 1, "endedAt": 2}],
        [{"content": "t", "status": "pending"}],
        1234,
        "思考整段",
    )
    msgs = client.get(f"/api/conversations/{conv['id']}/messages").json()["messages"]
    target = next(m for m in msgs if m["id"] == msg["id"])
    parsed = dto.Message.model_validate(target)
    assert parsed.durationMs == 1234
    assert parsed.reasoning == "思考整段"
    assert parsed.tools and parsed.tools[0]["text"] == "旁白"


def test_runinfo_dto(client):
    _, conv = _task_conv()
    run = db.create_run(conv["id"])
    db.interrupt_run(run["id"], [{"tool": "ask_human", "args": {}, "description": "问",
                                  "allowed": ["respond"]}], 3)
    latest = client.get(f"/api/conversations/{conv['id']}/runs/latest").json()["run"]
    parsed = dto.RunInfo.model_validate(latest)
    assert parsed.status == "waiting_input"
    assert parsed.requests and parsed.requests[0].tool == "ask_human"


def test_active_runs_dto(client):
    _, conv = _task_conv()
    run = db.create_run(conv["id"])
    runs = client.get("/api/runs/active").json()["runs"]
    parsed = dto.ActiveRun.model_validate(runs[0])
    assert parsed.conversation_id == conv["id"]
    assert parsed.status == "running"

    db.interrupt_run(run["id"], [], 0)
    runs = client.get("/api/runs/active").json()["runs"]
    parsed = dto.ActiveRun.model_validate(runs[0])
    assert parsed.status == "waiting_input"


def test_run_snapshot_dto(client):
    from app import agent as agent_mod

    _, conv = _task_conv()
    run = db.create_run(conv["id"])
    agent_mod.set_live_trace(run["id"], {"tools": [], "todos": [], "reasoning": "思考"})
    try:
        snap = client.get(f"/api/runs/{run['id']}/snapshot").json()
        parsed = dto.RunTraceSnapshot.model_validate(snap)
        assert parsed.status == "running"
        assert parsed.reasoning == "思考"
    finally:
        agent_mod.clear_live_trace(run["id"])


def test_kb_dto(client):
    for t in client.get("/api/kb/types").json()["types"]:
        dto.KbFieldType.model_validate(t)
    assert _upload_kb(client).status_code == 201
    items = client.get("/api/kb/items").json()["items"]
    assert len(items) == 1
    parsed = dto.KbItem.model_validate(items[0])
    assert parsed.parse_status in ("pending", "parsing", "ready", "failed")
