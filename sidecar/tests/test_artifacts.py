"""类型化 Artifact：/api/contracts、/api/artifacts 列表与内容端点。"""

from app import artifact_store, db, publish
from tests.util import create_task

KEY = "tender.directory/tender-response-docs@1"


def _content(name="技术部分"):
    return {
        "response_documents": [
            {"name": name, "scope": "", "directory": [{"目录名称": "目录", "level": 1, "children": []}]}
        ]
    }


def _task_conv():
    """§16：发布需要任务上下文；client fixture 已隔离 DATA_DIR。"""
    task = db.create_task("测试任务")
    conv = db.create_conversation(task["id"])
    return task, conv


def _pub(content, conv=None, **kw):
    """发布到会话过程稿；不传 conv 时新建任务+会话（覆盖语义需要同一 conv）。"""
    if conv is None:
        _, conv = _task_conv()
    return publish.publish_artifact(KEY, content, conversation_id=conv["id"], **kw)


def test_contracts_endpoint(client):
    r = client.get("/api/contracts")
    assert r.status_code == 200
    contracts = r.json()["contracts"]
    keys = [c["key"] for c in contracts]
    assert KEY in keys
    dir_c = next(c for c in contracts if c["key"] == KEY)
    assert dir_c["kind"] == "tender.directory"
    assert dir_c["cardinality"] == "task-single"
    assert dir_c["llm_write_mode"] == "suggest"
    assert dir_c["editable"] is True
    assert dir_c["default_display_name"] == "投标目录"


def test_artifacts_list_and_content(client):
    task, conv = _task_conv()
    m = publish.publish_artifact(
        KEY, _content(), conversation_id=conv["id"],
        source={"skill": "demo-skill", "thread_id": conv["id"], "run_id": "r_1"},
    )
    aid = m["artifact_id"]

    r = client.get("/api/artifacts")
    assert r.status_code == 200
    arts = r.json()["artifacts"]
    assert len(arts) == 1
    a = arts[0]
    assert a["artifact_id"] == aid
    assert a["display_name"] == "投标目录"
    assert a["kind"] == "tender.directory"
    assert a["schema_id"] == "tender-response-docs"
    assert a["schema_version"] == 1
    assert a["editable"] is True
    assert a["source"] == {"thread_id": conv["id"], "run_id": "r_1"}
    assert a["scope"] == "conversation"
    # §16：过程稿包路径在 <task>/threads/<conv>/ 下
    assert a["path"].endswith(
        f"{task['id']}/threads/{conv['id']}/{aid}/current/content.json"
    )

    r = client.get(f"/api/artifacts/{aid}/content")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["response_documents"][0]["name"] == "技术部分"

    assert client.get("/api/artifacts/nope/content").status_code == 404


def test_put_content_flow_no_lease(client):
    """编辑保存无租约（文件夹语义）：正常保存、409 探测、force 用户裁决覆盖（留恢复点）、422。"""
    m = _pub(_content())
    aid = m["artifact_id"]

    # 正常保存：无需任何租约
    updated = _content()
    updated["response_documents"][0]["name"] = "用户改后"
    r = client.put(f"/api/artifacts/{aid}/content", json={"content": updated, "base_content_seq": 1})
    assert r.status_code == 200
    assert r.json()["content_seq"] == 2
    assert "用户改后" in client.get(f"/api/artifacts/{aid}/content").text

    # 再保存一次（seq 2 → 3）
    r = client.put(f"/api/artifacts/{aid}/content", json={"content": updated, "base_content_seq": 2})
    assert r.status_code == 200 and r.json()["content_seq"] == 3

    # 基于旧 seq 保存 → 409 探测信号（客户端据此弹「拉取最新/保留我的」）
    r = client.put(f"/api/artifacts/{aid}/content", json={"content": updated, "base_content_seq": 2})
    assert r.status_code == 409

    # force：用户裁决保留自己的版本，无条件覆盖，被顶掉的版本留恢复点
    mine = _content()
    mine["response_documents"][0]["name"] = "我的版本"
    r = client.put(
        f"/api/artifacts/{aid}/content",
        json={"content": mine, "base_content_seq": 1, "force": True},
    )
    assert r.status_code == 200 and r.json()["content_seq"] == 4
    assert "我的版本" in client.get(f"/api/artifacts/{aid}/content").text

    # 列表带 content_seq 与 restore_available
    a = client.get("/api/artifacts").json()["artifacts"][0]
    assert a["content_seq"] == 4
    assert a["restore_available"] is True

    # schema 破坏始终拒绝（force 也不豁免）
    r = client.put(
        f"/api/artifacts/{aid}/content",
        json={"content": {"foo": 1}, "base_content_seq": 4, "force": True},
    )
    assert r.status_code == 422


def test_restore_roundtrip(client):
    """恢复点安全网：发布覆盖留底 → 恢复上一版 → 恢复本身可再撤销。"""
    _, conv = _task_conv()
    _pub(_content("初版"), conv=conv, source={"skill": "t"})
    m2 = _pub(_content("新版"), conv=conv, source={"skill": "t"})
    aid = m2["artifact_id"]

    r = client.post(f"/api/artifacts/{aid}/restore")
    assert r.status_code == 200
    assert "初版" in client.get(f"/api/artifacts/{aid}/content").text

    # 再次恢复 → 回到「新版」（恢复前也留了底）
    r = client.post(f"/api/artifacts/{aid}/restore")
    assert r.status_code == 200
    assert "新版" in client.get(f"/api/artifacts/{aid}/content").text


def test_put_unknown_artifact(client):
    r = client.put(
        "/api/artifacts/art_0000000000ff/content", json={"content": {}, "base_content_seq": 1}
    )
    assert r.status_code == 404
    assert client.post("/api/artifacts/art_0000000000ff/restore").status_code == 404


def test_artifacts_list_filters_missing_package(client):
    """索引在、磁盘包被删：列表过滤、内容端点 410（与工具侧 containment 同标准）。"""
    m = _pub(_content())
    aid = m["artifact_id"]

    import shutil

    shutil.rmtree(artifact_store.artifact_dir(aid, m))
    assert client.get("/api/artifacts").json()["artifacts"] == []
    assert client.get(f"/api/artifacts/{aid}/content").status_code == 410
