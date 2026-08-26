"""read_artifact 工具：按契约读取当前内容、无成果引导、未知契约。"""

import json

import pytest

from app import artifact_store, db, publish, runctx
from app.tools.read import read_artifact as read_tool
from tests.util import init_env

KEY = "tender.directory/tender-response-docs@1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    return {"root": tmp_path, "task": task, "conv": conv}


def _content(name="技术部分"):
    return {"response_documents": [{"name": name, "directory": [{"目录名称": "目录", "level": 1}]}]}


def _in_run(env):
    runctx.set_run(env["conv"]["id"], "r_t", env["task"]["id"])


def test_read_returns_current_content(env):
    publish.publish_artifact(KEY, _content("商务部分"), conversation_id=env["conv"]["id"])
    _in_run(env)
    try:
        out = read_tool.invoke({"contract": KEY})
    finally:
        runctx.clear_run()
    assert "商务部分" in out
    assert "response_documents" in out


def test_read_without_artifact_gives_guidance(env):
    _in_run(env)
    try:
        out = read_tool.invoke({"contract": KEY})
    finally:
        runctx.clear_run()
    assert out.startswith("[无成果]")
    assert "投标目录" in out


def test_read_unknown_contract_lists_available(env):
    out = read_tool.invoke({"contract": "no.such/contract@1"})
    assert out.startswith("[读取失败]")
    assert KEY in out  # 列出可用契约


def test_read_reflects_user_update(env):
    """用户编辑保存后的当前内容对后续 AI 可见（消费闭环）。"""
    m = publish.publish_artifact(KEY, _content("旧"), conversation_id=env["conv"]["id"])
    aid = m["artifact_id"]
    artifact_store.replace_current_content(
        aid, m, json.dumps(_content("用户调整后"), ensure_ascii=False)
    )
    row = db.get_artifact_index(aid)
    db.upsert_artifact_index({**row, "content_seq": row["content_seq"] + 1})
    _in_run(env)
    try:
        out = read_tool.invoke({"contract": KEY})
    finally:
        runctx.clear_run()
    assert "用户调整后" in out
