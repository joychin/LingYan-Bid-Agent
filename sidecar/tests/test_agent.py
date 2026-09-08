"""_run_agent_stream：iter_stream 归一化事件 -> SSE 发布载荷的映射。

重点守护 tool.result 的 error 字段透传（历史上曾在重发布时被丢弃，导致前端把
失败工具渲染成成功）；瞬时 LLM 错误的 checkpoint 断点自动重试（重试输入=None、
半截正文清空、残留步骤收尾、trace 留证、额度用尽文案、backoff 尊重停止）。
"""

import threading
import types

import httpx
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage

from app import agent as agent_mod
from app import config as cfg
from app import runctx
from app.agent import _run_agent_stream
from tests.util import init_env


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
    text, error, ecode, trace, interrupt = _run_agent_stream(
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
    text, error, ecode, trace, interrupt = _run_agent_stream(
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
    text, error, ecode, trace, _interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert text == "汇总"
    assert trace["tools"][0]["text"] == "并行读两个文件"
    assert trace["tools"][1]["text"] == ""


def test_main_reasoning_sealed_per_step():
    """主 agent 思考流（DeepSeek reasoning_content）按轮封段：tool.called 到达即把
    未封口思考挂到该步骤 reasoning 字段并清零（与旁白 text 同一条封段规则）；
    最后未封口段 = 最终回复前的思考，随 trace["reasoning"] 落库；
    SSE agent.reasoning 事件照常逐块发布（流式契约不变）。"""
    items = [
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先看评分"})),
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "办法…"})),
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "read", "args": {}, "id": "t1"}])]}}),
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "第二轮思考"})),
        ("messages", AIMessageChunk(content="最终回复")),
    ]
    published: list[tuple[str, dict]] = []
    text, error, ecode, trace, interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    assert interrupt is None
    assert text == "最终回复"
    # 第一段思考封进步骤 reasoning；最后未封口段落 trace["reasoning"]
    assert trace["tools"][0]["reasoning"] == "先看评分办法…"
    assert trace["reasoning"] == "第二轮思考"
    # SSE 逐块发布不受影响，主代理事件的 agent_id 恒为 None
    reason_events = [d for e, d in published if e == "agent.reasoning"]
    assert "".join(d["text"] for d in reason_events) == "先看评分办法…第二轮思考"
    assert all(d["agent_id"] is None for d in reason_events)


def test_main_reasoning_only_first_call_in_batch():
    """同一轮连发多个工具调用：思考只封第一个步骤，后续步骤 reasoning 为空串
    （与旁白 text 的 batch 规则同构）。"""
    items = [
        ("messages", AIMessageChunk(content="", additional_kwargs={"reasoning_content": "并行前思考"})),
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
    ]
    _text, error, ecode, trace, _interrupt = _run_agent_stream(
        _StubAgent(items), "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert trace["tools"][0]["reasoning"] == "并行前思考"
    assert trace["tools"][1]["reasoning"] == ""


def test_task_context_block_injects_clock(tmp_path, monkeypatch):
    """任务上下文注入天级日期（2026-09-06：秒级时间戳会打断前缀缓存，降为
    Claude Code 同款天级精度；模型写时间戳场景已删，日期足够）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import db
    from app.agent import _task_context_block

    db.init_db()
    task = db.create_task("测试任务")
    block = _task_context_block(task["id"], "c1")
    assert "当前任务：测试任务" in block
    assert "今天日期：" in block


def test_subagent_specs():
    """显式注册的子代理守护：执行单元齐全、不直接向用户提问。

    interrupt_on={} 是整体替换继承——漏写会让子代理继承 ask_human 门禁，
    子代理的 ask_human 无人应答会挂死；两个 writer 的提示词必须引用
    references（方法论单一事实源在 skill 里，不复制进提示词）。
    """
    from app.agent import SUBAGENTS

    specs = {s["name"]: s for s in SUBAGENTS}
    assert set(specs) == {"tender-outline-writer", "tender-body-writer"}
    for spec in specs.values():
        assert spec["interrupt_on"] == {}
        assert spec["system_prompt"].strip()
        # 路径罗盘 + 路径自愈必须随子代理挂载（子代理不继承主代理中间件，
        # 漏挂=子代理开局探测继续吃 path_not_found 红错，2026-09-08 修复回归线）
        mws = spec.get("middleware") or []
        assert any(type(m) is agent_mod._SubagentCompassMiddleware for m in mws)
        assert any(type(m) is agent_mod._PathRescueMiddleware for m in mws)
    writer = specs["tender-outline-writer"]
    for ref in ("generate.md", "annotation.md", "revise-gapfill.md", "revise-scoring.md", "revise-walkthrough.md"):
        assert ref in writer["system_prompt"]
    assert "禁止调用 ask_human" in writer["system_prompt"]
    body = specs["tender-body-writer"]
    assert "section-writing.md" in body["system_prompt"]  # 素材先行方法论单一真源
    assert "禁止调用 ask_human" in body["system_prompt"]
    # 承诺纪律与共享写边界（并发下唯一写边界，漏写=子代理改清单/编承诺值）
    assert "承诺清单" in body["system_prompt"]
    assert "禁止改写写作指引与关键事实与承诺清单" in body["system_prompt"]


def test_system_prompt_response_guidelines():
    """主 prompt 含用户回复规范入口与「用户语言」硬约束（内部路径/实现名词不进回复）。"""
    import inspect

    from app.agent import build_agent

    src = inspect.getsource(build_agent)
    assert "_shared/response-guidelines.md" in src, "主 prompt 缺少回复规范入口"
    assert "用户语言" in src, "主 prompt 缺少用户语言约束"


def test_system_prompt_output_format():
    """主 prompt 含排版/语气纪律（Markdown 环境声明、结构化、篇幅、禁 emoji/寒暄）。"""
    import inspect

    from app.agent import build_agent

    src = inspect.getsource(build_agent)
    for kw in ("Markdown 渲染", "列表或表格", "三五句话", "emoji", "寒暄"):
        assert kw in src, f"主 prompt 缺少输出格式关键词：{kw}"


def test_system_prompt_no_internal_codes():
    """主 prompt 不含内部阶段代号（R1/R2），且含反虚构与反问纪律（闲聊层也能约束到）。"""
    import inspect

    from app.agent import build_agent

    src = inspect.getsource(build_agent)
    assert "R1" not in src, "主 prompt 含内部代号 R1（模型会复读给用户）"
    for kw in ("不虚构", "概括层", "反问"):
        assert kw in src, f"主 prompt 缺少用户语言关键词：{kw}"


def test_system_prompt_todo_final_state():
    """主 prompt 含任务清单收尾回写终态纪律（半程清单不留给用户）。"""
    import inspect

    from app.agent import build_agent

    src = inspect.getsource(build_agent)
    for kw in ("write_todos", "真实终态", "收尾汇报前"):
        assert kw in src, f"主 prompt 缺少任务清单纪律关键词：{kw}"


def test_system_prompt_task_retry_guidance():
    """主 prompt 含 task 失败重派纪律（子代理执行错误不静默跳过）。"""
    import inspect

    from app.agent import build_agent

    src = inspect.getsource(build_agent)
    for kw in ("重派一次", "不要静默跳过"):
        assert kw in src, f"主 prompt 缺少 task 失败纪律关键词：{kw}"


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
    text, error, ecode, trace, interrupt = _run_agent_stream(
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
    text, error, ecode, trace, _interrupt = _run_agent_stream(
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
    text, error, ecode, trace, _interrupt = _run_agent_stream(
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
    """非瞬时错误（认证/参数类）不重试：一次失败即 error，trace 无 llm_retry。
    非 openai 类型化异常归 internal（程序错误兜底）。"""
    stub = _FlakyAgent(5, RuntimeError("401 Authentication Fails: invalid api key"), _ok_items())
    _text, error, ecode, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert stub.calls == 1
    assert "401" in error
    assert ecode == "internal"
    assert not [s for s in trace["tools"] if s["tool"] == "llm_retry"]


# ---- 瞬时判定谓词（SSE 流迭代期断连的裸 httpx 异常不在 langchain 包装范围内）----


def _bare_instream_apierror() -> Exception:
    """网关流内错误事件的产物：openai _streaming.py 构造裸基类 APIError（无状态码，
    不落任何子类——2026-09-07 实测 lfans "Our servers are currently overloaded"）。"""
    from openai import APIError

    return APIError(
        message="Our servers are currently overloaded. Please try again later.",
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        body=None,
    )


def _internal_500_error() -> Exception:
    from openai import InternalServerError

    response = httpx.Response(
        500,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={"error": {"code": "server_error", "message": "internal", "type": "server_error"}},
    )
    return InternalServerError("Error code: 500 - internal", response=response, body=None)


def _auth_401_error() -> Exception:
    from openai import AuthenticationError

    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={"error": {"code": "invalid_api_key", "message": "Incorrect API key", "type": "invalid_request_error"}},
    )
    return AuthenticationError("Error code: 401 - Incorrect API key", response=response, body=None)


def test_is_llm_transient_predicate():
    """类型命中 / 裸 httpx 流断连 / 网关流内错误 / 消息关键词兜底 / 永久错误判定。"""
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
    # 网关流内错误事件：裸基类 APIError（openai _streaming.py 唯一来源形态）→ 瞬时
    assert _is_llm_transient(_bare_instream_apierror())
    # 请求级 5xx（langchain 包装后的混合类仍继承 openai.InternalServerError）→ 瞬时
    assert _is_llm_transient(_internal_500_error())
    # 永久错误：认证/参数/业务异常不重试（4xx 全是 APIError 子类，精确类型不误伤）
    assert not _is_llm_transient(_auth_401_error())
    assert not _is_llm_transient(_reasoning_text_400())
    assert not _is_llm_transient(RuntimeError("401 Authentication Fails"))
    assert not _is_llm_transient(ValueError("路径越界"))
    assert not _is_llm_transient(httpx.InvalidURL("bad url"))
    # 关键词兜底：网关过载措辞（异常被换包装/重包的场景）
    assert _is_llm_transient(RuntimeError("Our servers are currently overloaded"))


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
    text, error, ecode, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert text == "完整回复"
    assert stub.calls == 2
    assert len([s for s in trace["tools"] if s["tool"] == "llm_retry"]) == 1


def test_gateway_instream_apierror_retries(monkeypatch):
    """2026-09-07 实测形态：网关在数据流中途推错误事件 → 裸 openai.APIError 基类，
    也走断点重试并成功完成（此前不入瞬时分类、零重试打死 40min run）。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(1, _bare_instream_apierror(), _ok_items())
    text, error, ecode, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert error is None
    assert text == "完整回复"
    assert stub.calls == 2
    assert len([s for s in trace["tools"] if s["tool"] == "llm_retry"]) == 1


def test_retry_exhausted_reports_count(monkeypatch):
    """重试额度用尽（测试压成 2 次；默认 3 次见 _LLM_RETRY_BACKOFFS）仍失败：
    error 定性 llm_unavailable + 人话文案带服务方原文，trace 留等额 llm_retry。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(99, ModelConnectionError("peer closed connection"), _ok_items())
    _text, error, ecode, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None
    )
    assert stub.calls == 3
    assert "已自动重试 2 次" in error
    assert "服务方返回" in error
    assert ecode == "llm_unavailable"
    retries = [s for s in trace["tools"] if s["tool"] == "llm_retry"]
    assert len(retries) == 2


def test_retry_publishes_agent_retry_event(monkeypatch):
    """重试等待期发 agent.retry 事件（2026-09-08 契约 additive）：前端据此显示
    「正在自动重试」shimmer 并清空未封口正文。attempt 从 1 起。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(1, ModelConnectionError("peer closed connection"), _ok_items())
    published: list[tuple[str, dict]] = []
    _text, error, _ecode, _trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    retries = [d for e, d in published if e == "agent.retry"]
    assert len(retries) == 1
    assert retries[0]["attempt"] == 1
    assert retries[0]["total"] == 2
    assert retries[0]["wait_seconds"] == 0.01


def test_classify_error_codes():
    """错误定性（agent.error/run.state 的 code 取值域）：配置缺失/401→llm_auth、
    瞬时→llm_unavailable、其余→internal；文案首行人话+原文次行。"""
    code, msg = agent_mod._classify_error(
        agent_mod.AgentConfigError("模型「X」未配置 API Key（设置 → 模型 → 填写并保存即生效）")
    )
    assert code == "llm_auth"
    assert "未配置 API Key" in msg
    code, msg = agent_mod._classify_error(_auth_401_error())
    assert code == "llm_auth"
    assert "API Key 无效" in msg
    assert "服务方返回" in msg
    code, msg = agent_mod._classify_error(ModelConnectionError("peer closed connection"))
    assert code == "llm_unavailable"
    code, msg = agent_mod._classify_error(ValueError("路径越界"))
    assert code == "internal"
    assert "程序内部错误" in msg


def test_cancel_during_backoff_wins(monkeypatch):
    """backoff 等待期间用户停止：立即走取消路径（不再发起重试）。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.5, 0.5))
    stub = _FlakyAgent(1, ModelConnectionError("peer closed"), _ok_items())
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    _text, error, ecode, _trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None, cancel_event=cancel
    )
    assert error == agent_mod.events.CANCELLED_MESSAGE
    assert ecode == "cancelled"
    assert stub.calls == 1  # 取消发生在等待期，未发起第二次调用


def test_cancel_before_failure_no_retry(monkeypatch):
    """断流时已请求停止：不进重试，直接取消收尾。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    stub = _FlakyAgent(1, ModelConnectionError("peer closed"), _ok_items())
    cancel = threading.Event()
    cancel.set()
    _text, error, ecode, _trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: None, "hi", None, cancel_event=cancel
    )
    assert error == agent_mod.events.CANCELLED_MESSAGE
    assert ecode == "cancelled"
    assert stub.calls == 1


# ---- task 子代理异常收敛（ToolErrorMiddleware，2026-09-07 缺口 2 修复）----


class _FakeToolCallRequest:
    """_task_failure_content 的最小 request 替身（只消费 tool_call dict）。"""

    def __init__(self) -> None:
        self.tool_call = {"name": "task", "args": {}, "id": "call_1"}


def test_task_failure_content_transient_vs_permanent():
    """task 收敛策略：瞬时错误返回 None（上抛走断点重试），永久错误转错误字符串
    （含异常类型与重派指引，模型据此自裁决）。"""
    req = _FakeToolCallRequest()
    assert agent_mod._task_failure_content(ModelConnectionError("peer closed"), req) is None
    assert agent_mod._task_failure_content(_bare_instream_apierror(), req) is None
    content = agent_mod._task_failure_content(RuntimeError("子图内部崩了"), req)
    assert "子代理执行失败" in content
    assert "RuntimeError" in content
    assert "子图内部崩了" in content
    assert "重派" in content


def test_task_error_contained_in_real_graph():
    """真 langchain 链路验证收敛契约（不依赖对库行为的假设）：名为 task 的工具抛
    永久异常 → run 不死、产生 status=error 的 ToolMessage（错误字符串回给模型）；
    抛瞬时异常 → 原样穿出图（主图断点重试可接手）。"""
    import pytest
    from langchain.agents import create_agent
    from langchain.agents.middleware import ToolErrorMiddleware
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool as lc_tool
    from pydantic import PrivateAttr

    class _ScriptedChatModel(BaseChatModel):
        """按剧本顺序回放的假模型（bind_tools 返回自身，供 create_agent 使用）。"""

        responses: list
        _idx: int = PrivateAttr(default=0)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            i = min(self._idx, len(self.responses) - 1)
            self._idx += 1
            return ChatResult(generations=[ChatGeneration(message=self.responses[i])])

        def bind_tools(self, tools, **kwargs):
            return self

        @property
        def _llm_type(self) -> str:
            return "scripted-test"

    def _build(raise_exc: Exception, responses: list):
        @lc_tool
        def task(query: str) -> str:
            """测试用 task 工具（模拟子代理派发）。"""
            raise raise_exc

        return create_agent(
            _ScriptedChatModel(responses=responses),
            tools=[task],
            middleware=[ToolErrorMiddleware(on_error=agent_mod._task_failure_content, tools=["task"])],
        )

    def _collect(agent) -> list:
        msgs = []
        for ev in agent.stream({"messages": [("user", "hi")]}, stream_mode="updates"):
            for upd in ev.values():
                if isinstance(upd, dict):
                    msgs.extend(upd.get("messages", []))
        return msgs

    call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {"query": "x"}, "id": "t1"}],
    )
    # 永久异常：收敛为错误 ToolMessage，run 正常走到最终回复
    msgs = _collect(_build(RuntimeError("子图内部崩了"), [call_msg, AIMessage(content="完成")]))
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert any(m.status == "error" and "子代理执行失败" in m.content for m in tool_msgs)
    assert any(isinstance(m, AIMessage) and m.content == "完成" for m in msgs)

    # 瞬时异常：原样穿出（_run_agent_stream 断点重试的接手契约）
    with pytest.raises(ModelConnectionError):
        _collect(_build(ModelConnectionError("peer closed"), [call_msg]))


# ---- 网关思考回传 400 兜底（_NoThinkingRetryCompletions） ----


def _reasoning_text_400() -> Exception:
    from openai import BadRequestError

    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={
            "error": {
                "code": "invalid_request_error",
                "message": "The `reasoning_text` in the thinking mode must be passed back to the API.",
                "type": "invalid_request_error",
            }
        },
    )
    return BadRequestError(
        "Error code: 400 - The `reasoning_text` in the thinking mode must be passed back to the API.",
        response=response,
        body=None,
    )


def _other_400() -> Exception:
    from openai import BadRequestError

    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={"error": {"code": "invalid_request_error", "message": "quota exceeded", "type": "invalid_request_error"}},
    )
    return BadRequestError("Error code: 400 - quota exceeded", response=response, body=None)


def test_gateway_thinking_fallback_wired():
    """build_agent 把兜底层接在模型 client 上（沿用源码断言先例）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "_NoThinkingRetryCompletions(model.client)" in src


def test_task_error_middleware_wired():
    """build_agent 把 task 异常收敛层接进 middleware 栈（沿用源码断言先例）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert 'ToolErrorMiddleware(on_error=_task_failure_content, tools=["task"])' in src


def test_dispatch_enrich_middleware_wired():
    """派发拼装中间件接进 build_agent；SUBAGENTS 与中间件用同一常量（改名单点生效）；
    写手 prompt 带开局瘦身禁令（2026-09-08 token 治理批，见 dispatch_enrich 模块头）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "_DISPATCH_ENRICH_MW" in src, "派发拼装中间件未接入 build_agent middleware 栈"
    assert agent_mod._BODY_WRITER_NAME == "tender-body-writer"
    writer = next(s for s in agent_mod.SUBAGENTS if s["name"] == agent_mod._BODY_WRITER_NAME)
    prompt = writer["system_prompt"]
    for kw in ("禁止调用", "check_pipeline_state", "禁止读 写作指引", "同一条消息里并发读完"):
        assert kw in prompt, f"写手 prompt 缺少开局瘦身禁令关键词：{kw}"
    # 派发拼装的目标必须确实是 SUBAGENTS 里的名字（防止常量与字面量漂移）
    assert any(
        s["name"] == agent_mod._BODY_WRITER_NAME for s in agent_mod.SUBAGENTS
    )


def test_run_stream_heals_task_skeleton():
    """run 启动自愈任务骨架目录（旧任务只有库行无磁盘目录，沿用源码断言先例）。"""
    import inspect

    src = inspect.getsource(agent_mod.run_stream)
    assert "ensure_task_skeleton" in src, "run_stream 缺少任务目录自愈调用"


def test_run_stream_records_work_files(tmp_path, monkeypatch):
    """「本轮文件」全链路：run 起止 work/ 快照 diff 落 run_traces.files，最终消息
    经 GET /messages 挂载（created/modified 判定真实走 run_stream 的接线）。"""
    import asyncio

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import artifact_store, db

    db.init_db()
    tid = db.create_task("任务")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]
    # run 前既有文件（跑中被改）
    keep = artifact_store.work_dir(tid) / "analysis"
    keep.mkdir(parents=True, exist_ok=True)
    (keep / "keep.md").write_text("旧内容", encoding="utf-8")

    def _stream(*_args, **_kwargs):
        # worker 线程执行期间的真实写入：新建一个 + 修改既有
        (keep / "structure.md").write_text("新建", encoding="utf-8")
        (keep / "keep.md").write_text("新内容-变长", encoding="utf-8")
        return iter([("messages", AIMessageChunk(content="完成"))])

    class _Agent:
        stream = staticmethod(_stream)

    async def _fake_get_agent(*_a, **_k):
        return _Agent()

    monkeypatch.setattr(agent_mod, "get_agent", _fake_get_agent)
    asyncio.run(agent_mod.run_stream(cid, rid, user_text="hi"))

    assert db.get_run(rid)["status"] == "completed"
    trace = db.get_run_trace(rid)
    assert {f["path"]: f["op"] for f in trace["files"]} == {
        "analysis/structure.md": "created",
        "analysis/keep.md": "modified",
    }
    # 最终消息挂载点：trace 行 message_id 指向 assistant 终态消息
    assert trace["message_id"] == db.list_messages(cid)[-1]["id"]


def test_run_stream_error_attaches_trace_to_interrupted_message(tmp_path, monkeypatch):
    """error 终态的 trace 挂到「（任务中断）」半截消息（2026-09-08 修复：此前
    message_id 写死 None，首段 error 的 trace 永远挂不上消息，历史里过程全丢）。"""
    import asyncio

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import db

    db.init_db()
    tid = db.create_task("任务")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]

    def _stream(*_args, **_kwargs):
        yield ("messages", AIMessageChunk(content="写到一半的旁白"))
        raise RuntimeError("boom")

    class _Agent:
        stream = staticmethod(_stream)

    async def _fake_get_agent(*_a, **_k):
        return _Agent()

    monkeypatch.setattr(agent_mod, "get_agent", _fake_get_agent)
    asyncio.run(agent_mod.run_stream(cid, rid, user_text="hi"))

    assert db.get_run(rid)["status"] == "error"
    last = db.list_messages(cid)[-1]
    assert last["role"] == "assistant" and "（任务中断）" in last["content"]
    # GET /messages 按 message_id 挂载 trace：挂上半截消息，历史里过程可见
    assert db.get_run_trace(rid)["message_id"] == last["id"]


def test_save_merged_trace_none_keeps_existing_mount(tmp_path, monkeypatch):
    """续跑段无新产出（error 半截为空）传 None：保留暂停消息挂载的合并语义不回归。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import db

    db.init_db()
    tid = db.create_task("任务")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]
    pause = db.append_assistant_message(cid, "（等待你的输入…）", rid=rid)

    agent_mod._save_merged_trace(rid, cid, pause["id"], {"tools": [], "todos": []}, 1000)
    agent_mod._save_merged_trace(rid, cid, None, {"tools": [], "todos": []}, 500)

    assert db.get_run_trace(rid)["message_id"] == pause["id"]


def test_run_stream_snapshot_failure_does_not_kill_run(tmp_path, monkeypatch):
    """起点快照异常只损失「本轮文件」数据（files 空），run 照常完成——探测绝不能
    打死 run（与终态 diff 的异常纪律镜像，2026-08-31 review 修复）。"""
    import asyncio

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import db
    from app import run_files as run_files_mod

    db.init_db()
    tid = db.create_task("任务")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]

    def _boom(*_a, **_k):
        raise OSError("stat race")

    monkeypatch.setattr(run_files_mod, "snapshot_work_files", _boom)

    class _Agent:
        def stream(self, *_a, **_k):
            return iter([("messages", AIMessageChunk(content="完成"))])

    async def _fake_get_agent(*_a, **_k):
        return _Agent()

    monkeypatch.setattr(agent_mod, "get_agent", _fake_get_agent)
    asyncio.run(agent_mod.run_stream(cid, rid, user_text="hi"))

    assert db.get_run(rid)["status"] == "completed"
    assert db.get_run_trace(rid)["files"] == []


class _RecordingCompletions:
    """可编排行为的 chat.completions 替身，记录每次 create 的 kwargs。"""

    def __init__(self, outcomes):
        # outcomes: 按调用顺序弹出；Exception 则抛出，否则作为返回值
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_no_thinking_retry_downgrades_once():
    """撞上 reasoning_text 400：当次请求降级 effort=none 重试一次并返回结果。"""
    ok = object()
    inner = _RecordingCompletions([_reasoning_text_400(), ok])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner)
    assert wrapper.create(model="m", messages=[], reasoning_effort="low") is ok
    assert [c.get("reasoning_effort") for c in inner.calls] == ["low", "none"]


def test_no_thinking_retry_no_effort_key_adds_none():
    """payload 未带 reasoning_effort（默认思考开）时同样补 none 重试。"""
    ok = object()
    inner = _RecordingCompletions([_reasoning_text_400(), ok])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner)
    assert wrapper.create(model="m", messages=[]) is ok
    assert "reasoning_effort" not in inner.calls[0]
    assert inner.calls[1]["reasoning_effort"] == "none"


def test_no_thinking_retry_skips_when_already_none():
    """effort 已是 none 仍 400：不再重试，原样上抛。"""
    inner = _RecordingCompletions([_reasoning_text_400()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner)
    try:
        wrapper.create(model="m", messages=[], reasoning_effort="none")
        raise AssertionError("应上抛 BadRequestError")
    except Exception as e:
        assert "reasoning_text" in str(e)
    assert len(inner.calls) == 1


def test_no_thinking_retry_passes_other_400_through():
    """其他 400（不同错误）不降级重试。"""
    inner = _RecordingCompletions([_other_400()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner)
    try:
        wrapper.create(model="m", messages=[], reasoning_effort="low")
        raise AssertionError("应上抛 BadRequestError")
    except Exception as e:
        assert "quota" in str(e)
    assert len(inner.calls) == 1


def _overflow_400(message: str) -> Exception:
    from openai import BadRequestError

    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={"error": {"code": "context_length_exceeded", "message": message}},
    )
    return BadRequestError(f"Error code: 400 - {message}", response=response, body=None)


def test_overflow_400_normalized_to_context_overflow():
    """各厂商超限措辞的 400 统一归一化为 ContextOverflowError（deepagents
    SummarizationMiddleware 捕获后当场压缩重试的入口），不重试、原消息保留。"""
    import pytest
    from langchain_core.exceptions import ContextOverflowError

    wordings = [
        # DeepSeek 官方/网关实测原文（2026-08-31 超长 payload 探针捕获；langchain_openai
        # 自带翻译不含此措辞，归一化是唯一入口）
        "This model's maximum context length is 1048576 tokens. However, you requested "
        "1920085 tokens (1920084 in the messages, 1 in the completion). Please reduce the "
        "length of the messages or completion.",
        # Anthropic
        "prompt is too long: 210000 tokens > 200000 maximum",
        # Bedrock / 网关
        "Input tokens exceed the configured limit of 131072",
        # OpenAI 新版措辞
        "input length and `max_tokens` exceed context limit",
        # code 字段措辞
        "error: context_length_exceeded",
    ]
    for w in wordings:
        inner = _RecordingCompletions([_overflow_400(w)])
        wrapper = agent_mod._NoThinkingRetryCompletions(inner)
        with pytest.raises(ContextOverflowError) as ei:
            wrapper.create(model="m", messages=[])
        assert w in str(ei.value)  # 原始报错消息保留，供日志与前端排查
        assert len(inner.calls) == 1


def test_context_window_merged_into_model_profile():
    """用户配置的窗口合并进 model.profile：保留注册表自动解析的能力键，只覆盖
    窗口（deepagents SummarizationMiddleware 据此按 85% 窗口比例触发压缩）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "max_input_tokens" in src, "build_agent 缺少 context_window → model.profile 合并"

    m = agent_mod._RunAwareChatDeepSeek(
        api_key="sk-test", base_url="https://example.invalid/v1", model="deepseek-v4-flash"
    )
    auto = dict(m.profile or {})
    assert auto.get("max_input_tokens") == 1000000, "langchain_deepseek 注册表应自带 deepseek-v4-flash 档案"
    m.profile = {**(m.profile or {}), "max_input_tokens": 128000}
    assert m.profile["max_input_tokens"] == 128000
    for k, v in auto.items():
        if k != "max_input_tokens":
            assert m.profile[k] == v, f"注册表能力键 {k} 不应被窗口覆盖抹掉"


def test_merge_trace_trees_fills_empty_text_reasoning():
    """HITL 续跑合并：重发的 tool.called 新副本 text/reasoning 必为空串（封段在新段
    开场即发生），就地替换时不能把暂停前封下的旁白/思考抹掉——新副本为空且回退旧值，
    新副本非空（如子代理 children reasoning）时以新值优先。"""
    from app.agent import _merge_trace_trees

    old = [
        {
            "id": "t1", "tool": "task", "status": "paused", "text": "派发前旁白",
            "reasoning": "派发前思考", "children": [],
        }
    ]
    new = [
        {
            "id": "t1", "tool": "task", "status": "done", "text": "",
            "reasoning": "", "children": [{"id": "s1", "reasoning": "子代理思考"}],
        }
    ]
    merged = _merge_trace_trees(old, new)
    assert merged[0]["status"] == "done"
    assert merged[0]["text"] == "派发前旁白"
    assert merged[0]["reasoning"] == "派发前思考"
    assert merged[0]["children"][0]["reasoning"] == "子代理思考"
    # 新段真有产出时不被旧值覆盖
    new2 = [{"id": "t1", "tool": "task", "status": "done", "text": "", "reasoning": "续段思考", "children": []}]
    merged2 = _merge_trace_trees(old, new2)
    assert merged2[0]["reasoning"] == "续段思考"


# ---------------------------------------------------------------------------
# 子代理路径罗盘 + 文件工具路径自愈（2026-09-08）
# ---------------------------------------------------------------------------


def test_path_rescue_candidates_covers_observed_forms():
    """实测四类猜错形态 + 两层叠加 + 归一/穿越安全（纯函数，不碰文件系统）。"""
    from app.agent import _norm_vpath, _path_rescue_candidates

    root = "/Users/z/dev/sidecar/data/workspace"
    t = "t_abc123"
    # ① 多余 /workspace 段
    assert "/t_abc123/work/body" in _path_rescue_candidates("/workspace/t_abc123/work/body", t, root)
    # ② 本机真实根前缀，且两层叠加出任务前缀候选
    cands = _path_rescue_candidates(f"{root}/work/body", t, root)
    assert "/work/body" in cands and f"/{t}/work/body" in cands
    # ③ 缺任务前缀（主形态：ls work/body/商务技术册 ×14）
    assert f"/{t}/work/body/商务技术册" in _path_rescue_candidates("/work/body/商务技术册", t, root)
    # ④ 任务前缀误套全局目录
    assert "/skills/tender-body/references" in _path_rescue_candidates(
        f"/{t}/skills/tender-body/references", t, root
    )
    # 复合形态：/workspace/t_x/skills/… 两层换算到全局 skills
    assert "/skills/x" in _path_rescue_candidates(f"/workspace/{t}/skills/x", t, root)
    # 相对路径先归一（防御：函数自归一，调用方传 norm 幂等）
    assert f"/{t}/work" in _path_rescue_candidates("work", t, root)
    # 已是正确形态 → 无候选（不画蛇添足）
    assert _path_rescue_candidates(f"/{t}/work/body", t, root) == []
    # 穿越段/家目录在归一层拦下
    assert _norm_vpath("a/../../etc/passwd") is None
    assert _norm_vpath("~/x") is None
    assert _norm_vpath("work/body") == "/work/body"


def _tc_request(tool: str, args: dict):
    from langgraph.prebuilt.tool_node import ToolCallRequest

    return ToolCallRequest(
        tool_call={"name": tool, "args": args, "id": "call_test", "type": "tool_call"},
        tool=None,
        state={},
        runtime=types.SimpleNamespace(),
    )


def test_path_rescue_middleware_rewrites_to_task_prefix(tmp_path, monkeypatch):
    """开局红错主形态：ls work/body/商务技术册（缺前缀）→ 换算到任务目录并附注记。"""
    task, _conv = init_env(tmp_path, monkeypatch)
    from app.artifact_store import ensure_task_skeleton

    tid = task["id"]
    ensure_task_skeleton(tid)
    (cfg.workspace_dir() / tid / "work" / "body" / "商务技术册").mkdir(parents=True, exist_ok=True)

    seen = {}

    def handler(req):
        seen["args"] = dict(req.tool_call["args"])
        return ToolMessage(content="['x.md']", name="ls", tool_call_id="call_test")

    runctx.set_run("c1", "r1", tid)
    try:
        out = agent_mod._PATH_RESCUE_MW.wrap_tool_call(
            _tc_request("ls", {"path": "/work/body/商务技术册"}), handler
        )
    finally:
        runctx.clear_run()
    assert seen["args"]["path"] == f"/{tid}/work/body/商务技术册"
    assert "路径已按任务上下文解析为" in out.content


def test_path_rescue_middleware_noop_and_global_strip(tmp_path, monkeypatch):
    """目标存在不改写；任务前缀误套全局目录剥掉；非文件工具/无任务上下文直通。"""
    task, _conv = init_env(tmp_path, monkeypatch)
    tid = task["id"]
    (cfg.workspace_dir() / "skills" / "tender-body" / "references").mkdir(parents=True, exist_ok=True)

    seen = {}

    def handler(req):
        seen["args"] = dict(req.tool_call["args"])
        return ToolMessage(content="ok", name=req.tool_call["name"], tool_call_id="call_test")

    runctx.set_run("c1", "r1", tid)
    try:
        out = agent_mod._PATH_RESCUE_MW.wrap_tool_call(
            _tc_request("ls", {"path": "/skills/tender-body/references"}), handler
        )
        assert seen["args"]["path"] == "/skills/tender-body/references"  # 存在→不改写
        assert out.content == "ok"
        agent_mod._PATH_RESCUE_MW.wrap_tool_call(
            _tc_request("ls", {"path": f"/{tid}/skills/tender-body/references"}), handler
        )
        assert seen["args"]["path"] == "/skills/tender-body/references"  # 误套前缀→剥掉
        agent_mod._PATH_RESCUE_MW.wrap_tool_call(_tc_request("task", {"description": "x"}), handler)
        assert seen["args"] == {"description": "x"}  # 非文件工具直通
    finally:
        runctx.clear_run()
    seen.clear()
    agent_mod._PATH_RESCUE_MW.wrap_tool_call(_tc_request("ls", {"path": "/work/body"}), handler)
    assert seen["args"]["path"] == "/work/body"  # 无任务上下文直通


def test_path_rescue_middleware_enriches_terminal_error(tmp_path, monkeypatch):
    """换算无命中时错误文案自带罗盘（模型一步纠正而非盲猜 2–3 轮）。"""
    task, _conv = init_env(tmp_path, monkeypatch)

    def handler(_req):
        return ToolMessage(
            content="Error: Path '/nope/zzz': path_not_found",
            name="ls",
            tool_call_id="call_test",
            status="error",
        )

    runctx.set_run("c1", "r1", task["id"])
    try:
        out = agent_mod._PATH_RESCUE_MW.wrap_tool_call(_tc_request("ls", {"path": "/nope/zzz"}), handler)
    finally:
        runctx.clear_run()
    assert "path_not_found" in out.content
    assert "【路径罗盘】" in out.content
    assert task["id"] in out.content


def test_path_rescue_middleware_write_parent_rule(tmp_path, monkeypatch):
    """write_file：原父目录在（真新文件）不改写；原父缺、候选父在 → 换算防散落。"""
    task, _conv = init_env(tmp_path, monkeypatch)
    from app.artifact_store import ensure_task_skeleton

    tid = task["id"]
    ensure_task_skeleton(tid)
    seen = {}

    def handler(req):
        seen["args"] = dict(req.tool_call["args"])
        return ToolMessage(content="Updated file", name="write_file", tool_call_id="call_test")

    runctx.set_run("c1", "r1", tid)
    try:
        agent_mod._PATH_RESCUE_MW.wrap_tool_call(
            _tc_request("write_file", {"file_path": "/work/body/new.md", "content": "x"}), handler
        )
        assert seen["args"]["file_path"] == f"/{tid}/work/body/new.md"
        agent_mod._PATH_RESCUE_MW.wrap_tool_call(
            _tc_request("write_file", {"file_path": "/skills/brandnew/deep/x.md", "content": "x"}), handler
        )
        assert seen["args"]["file_path"] == "/skills/brandnew/deep/x.md"  # 真新区域不动
    finally:
        runctx.clear_run()


def test_subagent_compass_injection():
    """罗盘注入：有任务上下文时追加到 system 且 run 内字节稳定；无上下文不动。"""
    import dataclasses as dc

    @dc.dataclass
    class _Req:
        system_message: object

    req = _Req(system_message=SystemMessage(content="子代理提示词"))
    seen = {}

    def handler(r):
        seen["content"] = r.system_message.content
        return "resp"

    for _ in range(2):  # 两次同任务调用 → 字节稳定（前缀缓存铁律）
        runctx.set_run("c1", "r1", "t_x9")
        try:
            agent_mod._SUBAGENT_COMPASS_MW.wrap_model_call(req, handler)
        finally:
            runctx.clear_run()
        if "first" in seen:
            assert seen["content"] == seen["first"]
        seen["first"] = seen["content"]
    assert seen["content"].startswith("子代理提示词")
    assert "【路径罗盘】" in seen["content"] and "t_x9/" in seen["content"]
    agent_mod._SUBAGENT_COMPASS_MW.wrap_model_call(req, handler)  # 无任务上下文
    assert seen["content"] == "子代理提示词"
