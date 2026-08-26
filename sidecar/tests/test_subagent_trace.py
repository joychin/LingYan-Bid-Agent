"""子代理过程透传：events.iter_stream 的 ns 分流/归属、middleware 插桩注册、run_traces 落库。"""

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app import db, events
from app.agent import _SubagentTagMiddleware


def _chunk(text="", reasoning=""):
    kw = {"reasoning_content": reasoning} if reasoning else {}
    return AIMessageChunk(content=text, additional_kwargs=kw)


def _model_update(msgs, todos=None):
    """子图/主图 model 节点的 update dict。"""
    u = {"messages": msgs}
    if todos is not None:
        u["todos"] = todos
    return {"model": u}


def _tools_update(msgs):
    return {"tools": {"messages": msgs}}


def _ai_with_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _run(items):
    return list(events.iter_stream(iter(items)))


def test_two_tuple_compat_no_subgraphs():
    """未开 subgraphs 的二元组流：主图行为与旧契约一致。"""
    out = _run([("messages", (_chunk(text="你好"), {}))])
    assert ("token", "你好") in out


def test_three_tuple_main_graph_events():
    out = _run([((), "messages", (_chunk(text="汇总", reasoning="想想"), {}))])
    assert ("token", "汇总") in out
    reasoning = [p for k, p in out if k == "reasoning"]
    assert reasoning == [{"text": "想想", "agent_id": None}]


def test_subagent_registry_attribution():
    """注册 ns→tool_call_id 后：子代理 reasoning 透传带 agent_id、正文 token 被跳过。"""
    events.register_subagent("tools:t1", "call_A1")
    try:
        out = _run([
            (("tools:t1",), "messages", (_chunk(text="子代理正文", reasoning="先抓页面"), {})),
        ])
    finally:
        events.clear_subagent_registry()
    kinds = [k for k, _ in out]
    assert "token" not in kinds  # 子代理正文不透传
    reasoning = [p for k, p in out if k == "reasoning"]
    assert reasoning == [{"text": "先抓页面", "agent_id": "call_A1"}]


def test_subagent_tool_events_carry_agent_id():
    events.register_subagent("tools:t1", "call_A1")
    try:
        out = _run([
            (("tools:t1",), "updates", _model_update([_ai_with_call("fetch_url", {"url": "https://x"}, "call_B1")])),
            (("tools:t1",), "updates", _tools_update([ToolMessage(content="页面内容", tool_call_id="call_B1", name="fetch_url")])),
        ])
    finally:
        events.clear_subagent_registry()
    (called,) = [p for k, p in out if k == "tool_called"]
    (result,) = [p for k, p in out if k == "tool_result"]
    assert called["agent_id"] == "call_A1"
    assert called["tool_call_id"] == "call_B1"
    assert result["agent_id"] == "call_A1"
    assert result["summary"] == "页面内容"


def test_main_graph_tool_called_carries_tool_call_id():
    out = _run([
        ((), "updates", _model_update([_ai_with_call("task", {"description": "调研"}, "call_A1")])),
    ])
    (payload,) = [p for k, p in out if k == "tool_called"]
    assert payload["tool"] == "task"
    assert payload["tool_call_id"] == "call_A1"
    assert payload["agent_id"] is None


def test_subagent_todos_filtered():
    """todos 只在主图 state；子代理 update 里的 todos 键被忽略（防御）。"""
    events.register_subagent("tools:t1", "call_A1")
    try:
        out = _run([
            (("tools:t1",), "updates", _model_update([], todos=[{"content": "x", "status": "pending"}])),
            ((), "updates", _model_update([], todos=[{"content": "y", "status": "pending"}])),
        ])
    finally:
        events.clear_subagent_registry()
    (todos,) = [p for k, p in out if k == "todo_updated"]
    assert todos[0]["content"] == "y"


def test_unmapped_subagent_ns_falls_back_to_none():
    """注册表未命中（异常路径）时 agent_id 为 None，事件不丢。"""
    out = _run([
        (("tools:t404",), "messages", (_chunk(reasoning="思考"), {})),
    ])
    reasoning = [p for k, p in out if k == "reasoning"]
    assert reasoning == [{"text": "思考", "agent_id": None}]


class _FakeRequest:
    def __init__(self, name, call_id, ns):
        self.tool_call = {"name": name, "args": {}, "id": call_id}
        self.tool = None
        self.state = {}
        self.runtime = type("R", (), {"config": {"configurable": {"checkpoint_ns": ns}}})()


def test_middleware_registers_task_only():
    """_SubagentTagMiddleware：task 调用登记 ns→call_id，非 task 不登记。"""
    events.clear_subagent_registry()
    mw = _SubagentTagMiddleware()

    def handler(request):
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    mw.wrap_tool_call(_FakeRequest("fetch_url", "c1", "tools:other"), handler)
    assert events._SUBAGENT_NS_TO_CALL == {}

    mw.wrap_tool_call(_FakeRequest("task", "call_A9", "tools:t9"), handler)
    assert events._SUBAGENT_NS_TO_CALL == {"tools:t9": "call_A9"}
    events.clear_subagent_registry()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    return tmp_path


def test_run_trace_roundtrip_and_cascade(env):
    cid = db.create_conversation()["id"]
    msg = db.append_assistant_message(cid, "汇总正文")
    db.save_run_trace(
        "r1", cid, msg["id"],
        [{"tool": "task", "children": [{"tool": "fetch_url"}]}],
        [{"content": "todo", "status": "completed"}],
    )
    traces = db.get_traces_for_messages([msg["id"]])
    assert traces[msg["id"]]["tools"][0]["children"][0]["tool"] == "fetch_url"

    db.delete_conversation(cid)
    assert db.get_traces_for_messages([msg["id"]]) == {}
