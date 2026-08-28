"""双库恢复语义：checkpoint 是记忆真值、messages 表是恢复源。

覆盖三个边界：启动记忆对账（recover_agent_memory）、删会话连带清 thread
（delete_thread_memory + DELETE 端点）、中断 run 半截回复落库。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from app import db


def _reset_agent_module():
    from app import agent as agent_mod

    if agent_mod._saver_conn is not None:
        agent_mod._saver_conn.close()
    agent_mod._saver_conn = None
    agent_mod._saver = None
    agent_mod._agents.clear()


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """带假 key 的 agent 环境（build_agent 只构造不调用，不会发真实请求）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    db.init_db()
    _reset_agent_module()
    from app import agent as agent_mod

    yield agent_mod
    _reset_agent_module()


# ---------- 启动记忆对账 ----------


def test_recover_agent_memory_rebuilds_missing_thread(agent_env):
    cid = db.create_conversation(None, "t")["id"]
    db.create_user_message(cid, "你好")
    db.append_assistant_message(cid, "在的")

    assert asyncio.run(agent_env.recover_agent_memory()) == 1

    agent = asyncio.run(agent_env.get_agent())
    msgs = agent.get_state({"configurable": {"thread_id": cid}}).values["messages"]
    assert [m.type for m in msgs] == ["human", "ai"]
    assert msgs[0].content == "你好"
    assert msgs[1].content == "在的"
    # 幂等：重建后再次对账不再动
    assert asyncio.run(agent_env.recover_agent_memory()) == 0


def test_recover_agent_memory_skips_healthy_thread(agent_env):
    cid = db.create_conversation(None, "t")["id"]
    db.create_user_message(cid, "hi")
    agent = asyncio.run(agent_env.get_agent())
    agent.update_state(
        {"configurable": {"thread_id": cid}},
        {"messages": [("user", "hi"), ("assistant", "checkpoint 原始内容")]},
    )

    assert asyncio.run(agent_env.recover_agent_memory()) == 0
    msgs = agent.get_state({"configurable": {"thread_id": cid}}).values["messages"]
    assert msgs[-1].content == "checkpoint 原始内容"  # 健在的 thread 不被 messages 表覆盖


def test_recover_agent_memory_skips_empty_conversations(agent_env):
    db.create_conversation(None, "空会话")  # 无消息：不探测不重建
    assert asyncio.run(agent_env.recover_agent_memory()) == 0


def test_recover_agent_memory_without_key_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    _reset_agent_module()
    from app.agent import recover_agent_memory

    assert asyncio.run(recover_agent_memory()) == 0
    _reset_agent_module()


# ---------- 删会话连带清 thread ----------


def test_delete_thread_memory_clears_thread(agent_env):
    cid = db.create_conversation(None, "t")["id"]
    agent = asyncio.run(agent_env.get_agent())
    cfg = {"configurable": {"thread_id": cid}}
    agent.update_state(cfg, {"messages": [("user", "hi")]})
    assert agent.get_state(cfg).values.get("messages")

    agent_env.delete_thread_memory(cid)
    assert not (agent.get_state(cfg).values or {}).get("messages")


def test_delete_endpoint_clears_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("SIDECAR_TOKEN", raising=False)
    _reset_agent_module()
    from app import agent as agent_mod
    from app.main import app

    with TestClient(app) as c:
        tid = c.post("/api/tasks", json={"title": "t"}).json()["task"]["id"]
        cid = c.post("/api/conversations", json={"task_id": tid}).json()["id"]
        agent = asyncio.run(agent_mod.get_agent())
        cfg = {"configurable": {"thread_id": cid}}
        agent.update_state(cfg, {"messages": [("user", "hi")]})
        assert agent.get_state(cfg).values.get("messages")

        assert c.delete(f"/api/conversations/{cid}").status_code == 200
        assert not (agent.get_state(cfg).values or {}).get("messages")
    _reset_agent_module()


# ---------- 中断 run 半截回复落库 ----------


class _PartialBoomAgent:
    """流出一段 token 后崩溃（模拟 LLM 网络中断）。"""

    def stream(self, *_a, **_k):
        yield ("messages", (AIMessageChunk(content="半截回复"), {}))
        raise RuntimeError("LLM 网络错误")


class _ImmediateBoomAgent:
    """一个 token 都没流出就失败（如 401 invalid key）。"""

    def stream(self, *_a, **_k):
        raise RuntimeError("401 invalid key")
        yield  # pragma: no cover - 仅为成为生成器函数


def _drive_run_stream(agent_env, monkeypatch, stub):
    cid = db.create_conversation(None, "t")["id"]
    rid = db.create_run(cid)["id"]

    async def _fake_get_agent(profile_id=None):
        return stub()

    monkeypatch.setattr(agent_env, "get_agent", _fake_get_agent)
    asyncio.run(agent_env.run_stream(cid, rid, "hi"))
    return cid


def test_run_stream_persists_partial_text_on_error(agent_env, monkeypatch):
    cid = _drive_run_stream(agent_env, monkeypatch, _PartialBoomAgent)
    msgs = db.list_messages(cid)
    assert msgs[-1]["role"] == "assistant"
    assert "半截回复" in msgs[-1]["content"]
    assert "（任务中断）" in msgs[-1]["content"]
    assert db.get_latest_run(cid)["status"] == "error"


def test_run_stream_error_without_text_no_message(agent_env, monkeypatch):
    cid = _drive_run_stream(agent_env, monkeypatch, _ImmediateBoomAgent)
    assert db.list_messages(cid) == []  # 没流出过文本：不造空消息
    assert db.get_latest_run(cid)["status"] == "error"
