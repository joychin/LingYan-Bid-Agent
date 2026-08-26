"""LLM 发布工具：任务 drafts/ 草稿 containment、runctx 来源、合法草稿发布。"""

import json

import pytest

from app import artifact_store, db, publish, runctx
from app.tools.publish import publish_artifact as publish_tool
from tests.util import init_env

KEY = "tender.directory/tender-response-docs@1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    artifact_store.task_drafts_dir(task["id"]).mkdir(parents=True, exist_ok=True)
    return {"root": tmp_path, "task": task, "conv": conv}


def _drafts_root(env):
    return artifact_store.task_drafts_dir(env["task"]["id"])


def _draft(env, name="toc.json", obj=None):
    p = _drafts_root(env) / name
    p.write_text(
        json.dumps(obj or {"response_documents": [{"name": "整册"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def test_publish_tool_happy_path_records_runctx(env):
    _draft(env)
    runctx.set_run(env["conv"]["id"], "r_abc", env["task"]["id"])
    try:
        out = publish_tool.invoke({"contract": KEY, "draft_path": "toc.json"})
    finally:
        runctx.clear_run()

    assert out.startswith("[发布成功]")
    row = db.list_artifact_index()[0]
    assert row["last_thread_id"] == env["conv"]["id"]
    assert row["last_run_id"] == "r_abc"
    assert row["task_id"] == env["task"]["id"]
    manifest = artifact_store.read_manifest(row["artifact_id"], row)
    assert manifest["source"] == {"skill": "direct", "thread_id": env["conv"]["id"], "run_id": "r_abc"}


def test_publish_tool_accepts_task_prefixed_draft_path(env):
    """模型按任务目录前缀给路径（如 <task>/drafts/x.json）与裸文件名都能解析。"""
    _draft(env, name="toc2.json")
    runctx.set_run(env["conv"]["id"], "r_abc", env["task"]["id"])
    try:
        prefixed = f"{env['task']['id']}/drafts/toc2.json"
        assert publish_tool.invoke({"contract": KEY, "draft_path": prefixed}).startswith("[发布成功]")
    finally:
        runctx.clear_run()


def test_publish_tool_rejects_draft_outside(env):
    outside = env["root"] / "evil.json"
    outside.write_text("{}", encoding="utf-8")
    runctx.set_run(env["conv"]["id"], "r_abc", env["task"]["id"])
    try:
        out = publish_tool.invoke({"contract": KEY, "draft_path": str(outside)})
        assert out.startswith("[发布失败]")
        assert "越界" in out
        assert db.list_artifact_index() == []

        # 相对路径逃逸（../）同样拒绝
        out = publish_tool.invoke({"contract": KEY, "draft_path": "../evil.json"})
        assert out.startswith("[发布失败]")
    finally:
        runctx.clear_run()


def test_publish_tool_rejects_invalid_json_and_schema(env):
    p = _drafts_root(env) / "bad.json"
    p.write_text("not json", encoding="utf-8")
    runctx.set_run(env["conv"]["id"], "r_abc", env["task"]["id"])
    try:
        assert "不是合法 JSON" in publish_tool.invoke({"contract": KEY, "draft_path": "bad.json"})

        _draft(env, name="wrong.json", obj={"foo": 1})
        out = publish_tool.invoke({"contract": KEY, "draft_path": "wrong.json"})
        assert "不符合契约" in out
        assert db.list_artifact_index() == []
    finally:
        runctx.clear_run()


def test_publish_tool_requires_task_context(env):
    """§16：草稿区在任务目录下，无任务上下文（不在 run 中）直接失败。"""
    _draft(env)
    out = publish_tool.invoke({"contract": KEY, "draft_path": "toc.json"})
    assert out.startswith("[发布失败]")
    assert "任务上下文" in out
    assert db.list_artifact_index() == []
