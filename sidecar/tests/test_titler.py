"""会话自动命名：条件写入护栏 + conversation.renamed 推送 + 端点接线。"""

import asyncio
import time

from app import bus, db, titler
from tests.util import create_conversation


def _run_titler(cid: str, text: str = "帮我分析这份招标文件"):
    return asyncio.run(titler.maybe_generate_title(cid, text))


def _drain(q):
    out = []
    while not q.empty():
        e = q.get_nowait()
        out.append((e["event"], e["data"]))
    return out


def test_publishes_renamed_event(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setattr(titler, "_generate", lambda key, text: "测试标题")
    cid = create_conversation(client)["id"]

    q = bus.subscribe(cid)
    try:
        _run_titler(cid)
        assert db.get_conversation(cid)["title"] == "测试标题"
        # 契约字段断言：恰为 conversation_id + title，无 seq（连接级事件）
        assert _drain(q) == [
            ("conversation.renamed", {"conversation_id": cid, "title": "测试标题"})
        ]
    finally:
        bus.unsubscribe(cid, q)


def test_skips_custom_title(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setattr(titler, "_generate", lambda key, text: (_ for _ in ()).throw(AssertionError("不应调用")))
    cid = create_conversation(client, title="自定义名")["id"]

    q = bus.subscribe(cid)
    try:
        _run_titler(cid)
        assert db.get_conversation(cid)["title"] == "自定义名"
        assert _drain(q) == []
    finally:
        bus.unsubscribe(cid, q)


def test_swallows_generate_errors(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")

    def boom(key, text):
        raise RuntimeError("LLM 挂了")

    monkeypatch.setattr(titler, "_generate", boom)
    cid = create_conversation(client)["id"]
    _run_titler(cid)  # 不抛
    assert db.get_conversation(cid)["title"] == "新对话"


def test_skips_without_key(client, monkeypatch):
    monkeypatch.setattr(titler, "_generate", lambda key, text: (_ for _ in ()).throw(AssertionError("不应调用")))
    cid = create_conversation(client)["id"]
    _run_titler(cid)
    assert db.get_conversation(cid)["title"] == "新对话"


def test_clean():
    assert titler._clean("标题：投标要点分析\n") == "投标要点分析"
    assert titler._clean('「目录梳理」') == "目录梳理"
    assert titler._clean("  帮我\n看看  这份  文件 ") == "帮我 看看 这份 文件"
    assert titler._clean("字" * 50) == "字" * 30
    assert titler._clean("   ") is None
    # 内容块列表（与 events._chunk_text 同款兼容）
    assert titler._clean([{"type": "text", "text": "报价策略"}]) == "报价策略"


def test_create_message_triggers_titler(client, monkeypatch):
    """fire-and-forget 接线：POST 消息后 titler 被调用（沿 test_hitl 的捕获轮询先例）。"""
    captured: dict = {}

    async def fake_maybe(cid_, text_):
        captured.update(cid=cid_, text=text_)

    monkeypatch.setattr(titler, "maybe_generate_title", fake_maybe)
    cid = create_conversation(client)["id"]
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).status_code == 202
    for _ in range(200):
        if "cid" in captured:
            break
        time.sleep(0.01)
    assert captured == {"cid": cid, "text": "hi"}
