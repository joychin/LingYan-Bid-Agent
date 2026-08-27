"""_run_agent_stream：iter_stream 归一化事件 -> SSE 发布载荷的映射。

重点守护 tool.result 的 error 字段透传（历史上曾在重发布时被丢弃，导致前端把
失败工具渲染成成功）；瞬时 LLM 错误的 checkpoint 断点自动重试（重试输入=None、
半截正文清空、残留步骤收尾、trace 留证、额度用尽文案、backoff 尊重停止）。
"""

import threading

import httpx
import pytest
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app import agent as agent_mod
from app.agent import _run_agent_stream


class _StubAgent:
    """只需 stream()：产出 ("updates", {node: update}) 形状的片段。"""

    def __init__(self, items):
        self._items = items
        self.inputs = []
        self.calls = 0

    def stream(self, *args, **_kwargs):
        self.inputs.append(args[0] if args else None)
        self.calls += 1
        return iter(self._items)


class _FlakyAgent:
    """前 fail_times 次抛瞬时异常，之后返回 items；记录每次输入供断言重试语义。"""

    def __init__(self, fail_times: int, error: Exception, items):
        self.fail_times = fail_times
        self.error = error
        self.items = items
        self.inputs = []
        self.calls = 0

    def stream(self, *args, **_kwargs):
        self.inputs.append(args[0] if args else None)
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return iter(self.items)


def test_tool_result_error_passthrough():
    calls = AIMessage(
        content="",
        tool_calls=[
            {"name": "convert_doc", "args": {}, "id": "c1"},
            {"name": "build_doc", "args": {}, "id": "c2"},
        ],
    )
    bad = ToolMessage(
        content="FileNotFoundError: /tmp/nope",
        name="convert_doc",
        status="error",
        tool_call_id="c1",
    )
    ok = ToolMessage(
        content="已生成 out/a.md",
        name="build_doc",
        status="success",
        tool_call_id="c2",
    )
    items = [
        ("updates", {"model": {"messages": [calls]}}),
        ("updates", {"tools": {"messages": [bad, ok]}}),
    ]
    published: list[tuple[str, dict]] = []
    text, error, trace, interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert interrupt is None
    assert error is None
    assert text == ""
    assert trace["todos"] == []
    assert [s["tool"] for s in trace["tools"]] == ["convert_doc", "build_doc"]
    assert trace["tools"][0]["status"] == "error"
    results = [d for e, d in published if e == "tool.result"]
    assert len(results) == 2
    assert results[0]["tool"] == "convert_doc"
    assert results[0]["error"] is not None
    assert "FileNotFoundError" in results[0]["error"]
    assert results[1]["tool"] == "build_doc"
    assert results[1]["error"] is None


def test_narration_segmentation():
    """段切分：tool.called 把之前流出的正文封为旁白挂到该步骤 text；
    最终回复 = 最后未被 tool.called 跟随的段（不再与旁白拼接）。"""
    items = [
        ("messages", AIMessageChunk(content="读取评分办法")),
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "t1"}])]}}),
        ("messages", AIMessageChunk(content="开始写目录")),
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "write", "args": {}, "id": "t2"}])]}}),
        ("messages", AIMessageChunk(content="完成，已发布")),
    ]
    published: list[tuple[str, dict]] = []
    text, error, trace, interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    assert interrupt is None
    assert text == "完成，已发布"
    by_tool = {s["tool"]: s for s in trace["tools"]}
    assert by_tool["read"]["text"] == "读取评分办法"
    assert by_tool["write"]["text"] == "开始写目录"
    # token 事件不受段切分影响：流式全量实时发布
    tokens = "".join(d["text"] for e, d in published if e == "agent.token")
    assert tokens == "读取评分办法开始写目录完成，已发布"


def test_narration_only_first_call_in_batch():
    """同一轮连发多个工具调用：旁白只挂第一个步骤，后续步骤 text 为空串。"""
    items = [
        ("messages", AIMessageChunk(content="并行读两个文件")),
        (
            "updates",
            {
                "model": {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[
                                {"name": "read", "args": {}, "id": "b1"},
                                {"name": "read", "args": {}, "id": "b2"},
                            ],
                        )
                    ]
                }
            },
        ),
        ("messages", AIMessageChunk(content="汇总")),
    ]
    text, error, trace, _interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert text == "汇总"
    assert trace["tools"][0]["text"] == "并行读两个文件"
    assert trace["tools"][1]["text"] == ""


def test_main_reasoning_accumulated_into_trace():
    """主 agent 思考流（DeepSeek reasoning_content）整段累积进 trace["reasoning"]：
    跨工具轮不封段（与旁白 text 不同），run 结束随 run_traces 落库供历史「深度思考」渲染；
    SSE agent.reasoning 事件照常逐块发布（流式契约不变）。"""
    items = [
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先看评分"})),
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "办法…"})),
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "t1"}])]}}),
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "第二轮思考"})),
        ("messages", AIMessageChunk(content="最终回复")),
    ]
    published: list[tuple[str, dict]] = []
    text, error, trace, interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    assert interrupt is None
    assert text == "最终回复"
    # 跨轮整段拼接（reasoning 不按 tool.called 封段）
    assert trace["reasoning"] == "先看评分办法…第二轮思考"
    # SSE 逐块发布不受影响，主代理事件的 agent_id 恒为 None
    reason_events = [d for e, d in published if e == "agent.reasoning"]
    assert "".join(d["text"] for d in reason_events) == "先看评分办法…第二轮思考"
    assert all(d["agent_id"] is None for d in reason_events)


def test_task_context_block_injects_clock(tmp_path, monkeypatch):
    """任务上下文注入当前时间：模型不知道时间，写时间戳（analysis 产物头部等）会编造。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import db
    from app.agent import _task_context_block

    db.init_db()
    task = db.create_task("测试任务")
    block = _task_context_block(task["id"], "c1")
    assert "当前任务：测试任务" in block
    assert "当前时间：" in block


def test_subagent_specs():
    """显式注册的子代理守护：执行单元齐全、不直接向用户提问。

    interrupt_on={} 是整体替换继承——漏写会让子代理继承 ask_human/task 门禁，
    子代理的 ask_human 无人应答会挂死；tender-outline-writer 的提示词必须引用
    references（方法论单一事实源在 skill 里，不复制进提示词）。
    """
    from app.agent import SUBAGENTS

    specs = {s["name"]: s for s in SUBAGENTS}
    assert set(specs) == {"tender-outline-writer"}
    for spec in specs.values():
        assert spec["interrupt_on"] == {}
        assert spec["system_prompt"].strip()
    writer = specs["tender-outline-writer"]
    for ref in ("generate.md", "annotation.md", "revise-gapfill.md", "revise-scoring.md", "revise-walkthrough.md"):
        assert ref in writer["system_prompt"]
    assert "禁止调用 ask_human" in writer["system_prompt"]


# ---- 瞬时 LLM 错误自动重试（2026-08-27 全量测试 T07 API 流断的修复）----


def _ok_items() -> list:
    """一段最小成功流：token + 最终回复。"""
    return [("messages", AIMessageChunk(content="完整回复"))]


def test_transient_error_retries_from_checkpoint(monkeypatch):
    """ModelConnectionError → 以 input=None 从 checkpoint 断点重拉一次成功：
    run 正常完成、失败那轮的半截正文不进最终回复、trace 留 llm_retry 伪步骤。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(1, ModelConnectionError("peer closed connection"), _ok_items())
    published: list[tuple[str, dict]] = []
    text, error, trace, interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    assert interrupt is None
    assert text == "完整回复"
    assert stub.calls == 2
    # 重试语义：首段传消息 dict，重试段传 None（langgraph 从 checkpoint 恢复 pending 任务）
    assert stub.inputs[0] == {"messages": [("user", "hi")]}
    assert stub.inputs[1] is None
    retries = [s for s in trace["tools"] if s["tool"] == "llm_retry"]
    assert len(retries) == 1
    assert retries[0]["status"] == "done"
    assert retries[0]["args"]["attempt"] == 1
    # 失败那轮已发出的 token 事件不做撤回（已知显示局限），但成功段的 token 照常发布
    tokens = "".join(d["text"] for e, d in published if e == "agent.token")
    assert tokens == "完整回复"


def test_transient_error_clears_partial_text(monkeypatch):
    """失败那轮流出的半截正文必须清空——重试会完整重流出，保留会拼进最终回复。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))

    def _fail_gen():
        yield ("messages", AIMessageChunk(content="半截"))
        raise ModelConnectionError("incomplete chunked read")

    stub = _FlakyAgent(0, ModelConnectionError("x"), _ok_items())

    def stream(*args, **kwargs):
        stub.inputs.append(args[0] if args else None)
        stub.calls += 1
        if stub.calls == 1:
            return _fail_gen()  # 先流出半截 token，再断流
        return iter(stub.items)

    stub.stream = stream
    text, error, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert text == "完整回复"  # 「半截」被清空，未混入最终回复


def test_broken_steps_retired_and_republished_on_retry(monkeypatch):
    """断流时残留的 running 步骤（该轮工具实际未执行）收尾为 error 并补发
    tool.result（error）让前端实时卡片收敛；重试轮的新调用以新 tool_call_id 落新步骤。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    ghost_call = ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "old1"}])]}})

    def _fail_gen():
        yield ghost_call
        raise ModelConnectionError("peer closed")

    ok = [
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "new1"}])]}}),
        ("updates", {"tools": {"messages": [ToolMessage(content="ok", name="read", status="success", tool_call_id="new1")]}}),
        ("messages", AIMessageChunk(content="done")),
    ]
    stub = _FlakyAgent(0, ModelConnectionError("x"), ok)
    calls = 0

    def stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _fail_gen()
        return iter(ok)

    stub.stream = stream
    published: list[tuple[str, dict]] = []
    text, error, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    assert text == "done"
    tools = {s.get("tool_call_id"): s for s in trace["tools"] if s.get("tool") == "read"}
    assert tools["old1"]["status"] == "error"
    assert "LLM 流中断" in tools["old1"]["error"]
    assert tools["new1"]["status"] == "done"
    ghost_results = [d for e, d in published if e == "tool.result" and d.get("tool_call_id") == "old1"]
    assert len(ghost_results) == 1
    assert ghost_results[0]["error"]


def test_permanent_error_no_retry():
    """非瞬时错误（认证/参数类）不重试：一次失败即 error，trace 无 llm_retry。"""
    stub = _FlakyAgent(5, RuntimeError("401 Authentication Fails: invalid api key"), _ok_items())
    _text, error, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert stub.calls == 1
    assert "401" in error
    assert not [s for s in trace["tools"] if s["tool"] == "llm_retry"]


# ---- 瞬时判定谓词（SSE 流迭代期断连的裸 httpx 异常不在 langchain 包装范围内）----


def test_is_llm_transient_predicate():
    """类型命中 / 裸 httpx 流断连 / 消息关键词兜底 / 永久错误四类判定。"""
    from app.agent import _is_llm_transient

    assert _is_llm_transient(ModelConnectionError("x"))
    assert _is_llm_transient(
        httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )
    )
    # 库版本更替下同类瞬断换了包装：非 httpx 类型但消息可识别
    assert _is_llm_transient(RuntimeError("Server disconnected without sending a message (peer closed connection)"))
    assert _is_llm_transient(Exception("...incomplete chunked read..."))
    assert _is_llm_transient(RuntimeError("Connection reset by peer"))
    # 永久错误：认证/参数/业务异常不重试
    assert not _is_llm_transient(RuntimeError("401 Authentication Fails"))
    assert not _is_llm_transient(ValueError("路径越界"))
    assert not _is_llm_transient(httpx.InvalidURL("bad url"))


def test_bare_httpx_stream_disconnect_retries(monkeypatch):
    """T07 实测形态：流迭代期裸 httpx.RemoteProtocolError（非 langchain 包装）
    也走断点重试并成功完成。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(
        1,
        httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        ),
        _ok_items(),
    )
    text, error, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert text == "完整回复"
    assert stub.calls == 2
    assert len([s for s in trace["tools"] if s["tool"] == "llm_retry"]) == 1


def test_retry_exhausted_reports_count(monkeypatch):
    """重试额度（2 次）用尽仍失败：error 文案注明已重试次数，trace 留两条 llm_retry。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(99, ModelConnectionError("peer closed connection"), _ok_items())
    _text, error, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert stub.calls == 3
    assert "已自动重试 2 次" in error
    retries = [s for s in trace["tools"] if s["tool"] == "llm_retry"]
    assert len(retries) == 2


def test_cancel_during_backoff_wins(monkeypatch):
    """backoff 等待期间用户停止：立即走取消路径（不再发起重试）。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.5, 0.5))
    stub = _FlakyAgent(1, ModelConnectionError("peer closed"), _ok_items())
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    _text, error, _trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None, cancel_event=cancel
    )
    assert error == agent_mod.events.CANCELLED_MESSAGE
    assert stub.calls == 1  # 取消发生在等待期，未发起第二次调用


def test_cancel_before_failure_no_retry(monkeypatch):
    """断流时已请求停止：不进重试，直接取消收尾。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(1, ModelConnectionError("peer closed"), _ok_items())
    cancel = threading.Event()
    cancel.set()
    _text, error, _trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None, cancel_event=cancel
    )
    assert error == agent_mod.events.CANCELLED_MESSAGE
    assert stub.calls == 1
