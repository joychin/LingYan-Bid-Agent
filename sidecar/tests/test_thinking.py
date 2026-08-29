"""思考档位（reasoning_effort）：按 run 注入模型请求 + 随消息入 runs 表。

_RunAwareChatDeepSeek 在 _get_request_payload 现读 runctx 档位（并发 run 各在
自己 to_thread 工作线程的 context 拷贝里互不串扰，实例共享只读）；POST
/messages 的 thinking 字段落 runs 行（HITL 续跑沿用存档值）；档位词表封闭
low/medium/high（模型默认开思考，无关闭项）。
"""

import pytest
from langchain_core.messages import HumanMessage

from app import db, runctx
from app.agent import _RunAwareChatDeepSeek
from tests.util import create_conversation


def _model() -> _RunAwareChatDeepSeek:
    # 假 key/base_url：只构建 payload，不发请求
    return _RunAwareChatDeepSeek(
        api_key="sk-test", base_url="https://example.invalid/v1", model="deepseek-v4-flash"
    )


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    return tmp_path


def test_payload_injects_effort_per_run_level():
    m = _model()
    try:
        for level in ("low", "medium", "high"):
            runctx.set_run("c1", "r1", "t1", level)
            payload = m._get_request_payload([HumanMessage(content="hi")], stop=None)
            assert payload["reasoning_effort"] == level
    finally:
        runctx.clear_run()


def test_payload_defaults_low_without_run():
    # 不在 run 中（如测试直接调工具/模型）兜底 low；set_run 老三参调用路径同样默认 low
    m = _model()
    assert m._get_request_payload([HumanMessage(content="hi")], stop=None)["reasoning_effort"] == "low"
    try:
        runctx.set_run("c1", "r1")
        assert m._get_request_payload([HumanMessage(content="hi")], stop=None)["reasoning_effort"] == "low"
    finally:
        runctx.clear_run()


def test_create_run_stores_thinking(db_env):
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid, "high")["id"]
    assert db.get_run(rid)["thinking"] == "high"
    assert db.create_run(cid)["thinking"] == "low"  # 缺省档位


def test_message_body_rejects_unknown_level(client):
    cid = create_conversation(client)["id"]
    for bad in ("off", "", "ultra"):
        r = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi", "thinking": bad})
        assert r.status_code == 422, (bad, r.text)


def test_message_stores_thinking_on_run(client):
    cid = create_conversation(client)["id"]
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi", "thinking": "high"})
    assert r.status_code == 202, r.text
    assert db.get_run(r.json()["run_id"])["thinking"] == "high"
    # 不带字段 = 默认 low（收尾首个 run 再发，避免撞会话级 running 守卫）
    db.finish_run(r.json()["run_id"], "completed")
    r2 = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    assert r2.status_code == 202, r2.text
    assert db.get_run(r2.json()["run_id"])["thinking"] == "low"
