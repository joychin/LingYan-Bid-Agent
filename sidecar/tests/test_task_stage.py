"""首页任务列表的阶段推导（task_stage.py）：六阶段推进、批量元信息、三端点透出。

判据全来自既有真值（work/ 文件 + 产物索引），本测试逐级造出这些真值并断言阶段
单调推进；另钉死两条容易回归的陷阱：目录预建但为空不算「已解析」、阶段只看文件
内容是否存在而不读文件内容（与 workbench 首行读法无关）。
"""

import pytest
from fastapi.testclient import TestClient

from app import artifact_store, db, task_stage
from tests.util import create_task

DIR_KEY = "tender.directory/tender-response-docs@1"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from app.main import app

    db.init_db()
    with TestClient(app) as c:
        yield c


def _task(tmp_path, monkeypatch, title="市政项目投标"):
    """建任务 + 骨架（与 API 的 POST /tasks 同口径）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task(title)
    artifact_store.ensure_task_skeleton(task["id"])
    return task


def _write_work(task_id: str, rel: str, name: str = "f.md") -> None:
    d = artifact_store.work_dir(task_id) / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("x", encoding="utf-8")


def _publish_row(task_id: str, schema_id: str, artifact_id: str, updated_at: str) -> None:
    """直接写索引行（阶段推导只读索引 + 磁盘，不走发布入口——保持测试聚焦）。"""
    db.upsert_artifact_index(
        {
            "artifact_id": artifact_id,
            "task_id": task_id,
            "conversation_id": None,
            "kind": "tender.directory",
            "schema_id": schema_id,
            "schema_version": 1,
            "cardinality": "task-single",
            "display_name": "投标目录",
            "content_path": f"{artifact_id}/content.json",
            "updated_at": updated_at,
        }
    )


def test_stage_progresses_monotonically(tmp_path, monkeypatch):
    task = _task(tmp_path, monkeypatch)
    tid = task["id"]

    def stage() -> str:
        return task_stage.derive_stage(tid, set(db.list_task_artifact_signals().get(tid, {})))

    # 骨架刚建（parse/analysis/outline/body 目录都在但全空）→ 不能算已解析
    assert stage() == "new"

    _write_work(tid, "parse", "招标文件.md")
    assert stage() == "parsed"

    _write_work(tid, "analysis", "要点.md")
    assert stage() == "analyzed"

    # 目录产物发布（无 body 文件时判 outlined）
    _publish_row(tid, "tender-response-docs", "a_dir", "2026-01-01T00:00:00+00:00")
    assert stage() == "outlined"

    _write_work(tid, "body", "第1章.docx")
    assert stage() == "drafting"

    _publish_row(tid, "tender-volume-docx", "a_vol", "2026-01-02T00:00:00+00:00")
    assert stage() == "delivered"


def test_artifacts_subtree_does_not_count(tmp_path, monkeypatch):
    """work/artifacts/（产物包）不参与阶段判定：只有包、没有过程文件仍是 new。"""
    task = _task(tmp_path, monkeypatch)
    tid = task["id"]
    _write_work(tid, "body/artifacts", "pack.json")
    assert task_stage.derive_stage(tid, set()) == "new"


def test_last_activity_is_max_of_created_run_artifact(tmp_path, monkeypatch):
    task = _task(tmp_path, monkeypatch, "t")
    tid = task["id"]
    conv = db.create_conversation(tid, "c")
    _publish_row(tid, "tender-response-docs", "a1", "2030-01-01T00:00:00+00:00")
    db.create_run(conv["id"])  # 起始时间=现在，晚于 created_at、早于产物

    meta = task_stage.compute_task_meta([task])[tid]
    assert meta["last_activity_at"] == "2030-01-01T00:00:00+00:00"


def test_compute_task_meta_batched(tmp_path, monkeypatch):
    """多任务批量：各自独立阶段，互不串台。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    t1 = _task(tmp_path, monkeypatch, "甲")
    t2 = _task(tmp_path, monkeypatch, "乙")
    _write_work(t1["id"], "parse")
    _write_work(t2["id"], "body")

    meta = task_stage.compute_task_meta([t1, t2])
    assert meta[t1["id"]]["stage"] == "parsed"
    assert meta[t2["id"]]["stage"] == "drafting"
    assert set(meta) == {t1["id"], t2["id"]}


def test_list_tasks_endpoint_exposes_stage(client, tmp_path, monkeypatch):
    """GET /tasks 每行带 stage / last_activity_at（前端首页列表直接消费）。"""
    created = create_task(client, "政务云采购")
    tid = created["task"]["id"]
    # POST 应答也带字段
    assert created["task"]["stage"] == "new"
    assert created["task"]["last_activity_at"]

    _write_work(tid, "parse")

    rows = client.get("/api/tasks").json()["tasks"]
    row = next(r for r in rows if r["id"] == tid)
    assert row["stage"] == "parsed"
    assert row["last_activity_at"] >= created["task"]["created_at"]


def test_patch_task_returns_stage(client):
    """PATCH（改进度便签）应答同样带字段——契约 extra=forbid，字段缺一即红。"""
    created = create_task(client, "任务A")
    tid = created["task"]["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"progress_note": "- 解析 已完成"})
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "new"
    assert "last_activity_at" in body


def test_empty_task_list_ok(client):
    assert client.get("/api/tasks").json()["tasks"] == []
