"""_run_agent_stream：iter_stream 归一化事件 -> SSE 发布载荷的映射。

重点守护 tool.result 的 error 字段透传（历史上曾在重发布时被丢弃，导致前端把
失败工具渲染成成功）；瞬时 LLM 错误的 checkpoint 断点自动重试（重试输入=None、
半截正文清空、残留步骤收尾、trace 留证、额度用尽文案、backoff 尊重停止）。
"""

import asyncio
import threading
import types

import httpx
from langchain_core.exceptions import ModelConnectionError
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

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
    # 方法论单一真源=section-writing.md，但 2026-09-12 起由主代理派发时内联
    # （dispatch_enrich._skill_text），写手 prompt 只留「已随任务描述给出、不要再读」
    # 的指引——全库该文件此前被 215 次读取、205 次在子代理，每节白付一次往返。
    assert "section-writing.md" in body["system_prompt"]  # 指出单一真源
    assert "不要再 read_file" in body["system_prompt"] or "不要 read_file" in body["system_prompt"]
    # 素材复用纪律（2026-09-10 收口回归线）：派发已给块清单不再重检索素材库
    assert "直接采用" in body["system_prompt"]
    assert "不再调用 search_references" in body["system_prompt"]
    # 注入粒度自选（2026-09-15 契约修正批）：块=拷贝授权范围非注入原子，写手
    # 按节挑选整块或块内区间（lines），同一内容区间不得进两节
    assert "拷贝授权范围" in body["system_prompt"]
    assert "同一内容区间不得进两节" in body["system_prompt"]
    assert "blk_…:L起-L止" in body["system_prompt"]  # validate 后缀写法教学在位
    assert "禁止调用 ask_human" in body["system_prompt"]
    # 读取瘦身纪律（2026-09-14 回读收敛批）：禁探测/禁编号/不回读
    assert "开局禁止 ls/glob 探测目录" in body["system_prompt"]
    assert "禁止 grep/检索 REQ/MAND/SCORE/TPL" in body["system_prompt"]
    assert "不回读视图确认" in body["system_prompt"]
    # 表格通道纪律（2026-09-14）：body 块混排 + 图示清单按计划产出
    assert "body 块序列（段落+表格混排）" in body["system_prompt"]
    assert "本节图示清单" in body["system_prompt"] and "docx_diagram_insert" in body["system_prompt"]
    # 界面原型纪律（2026-09-14 批二）：HTML 内联/禁外链/失败降级
    assert "docx_html_figure" in body["system_prompt"] and "禁外链禁脚本" in body["system_prompt"]
    # 承诺纪律与共享写边界（并发下唯一写边界，漏写=子代理改清单/编承诺值）
    assert "承诺清单" in body["system_prompt"]
    assert "禁止改写写作指引与关键事实与承诺清单" in body["system_prompt"]
    # 素材异议出口（2026-09-13）：用户手选素材与本节要求不符时，写手此前只有
    # 「顺从」和「沉默」两种反应——没有反弹回路。现放开一条受限异议通道：
    # 仍照常注入+改写（不动产物路径、不丢素材图），只额外留一条「素材异议」批注
    # 并在摘要单列。这三句是配套的：不许跳过/不许换块（否则产物路径分叉）、
    # 批注固定前缀（可机械识别）、摘要单列（带回给用户与主 agent）。
    assert "素材异议" in body["system_prompt"]
    assert "不得自行跳过该块或改换" in body["system_prompt"]
    assert "仍须照常注入并改写" in body["system_prompt"]


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


def test_system_prompt_glossary_and_no_invented_paths():
    """主 prompt 含资料词汇表（版式=格式/素材=内容）与无机制如实说纪律。

    动因（2026-09-09）：「为整本应用模板」请求下 agent 把素材库文件列成
    「模板库」候选——版式库对 agent 零可见，只能按日常语义把历史标书当模板。
    同日「模板库」定名改「版式库」，关键词随改（正文守卫句保留「模板」字样
    ——用户提问仍用日常词，守卫按日常词触发）。
    """
    import inspect

    from app.agent import build_agent

    src = inspect.getsource(build_agent)
    for kw in (
        "资料词汇表",
        "写作素材库=用户手工挑选的章节素材块",
        "版式库=纯版式资产",
        "不要把素材库文件当「模板」候选",
        "不存在「把版式应用到整本/已写章节」的工具",
        "不要发明替代路径凑合执行",
    ):
        assert kw in src, f"主 prompt 缺少词汇表/无机制纪律关键词：{kw}"


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
    不落任何子类——2026-09-07 实测自建网关 "Our servers are currently overloaded"）。"""
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


def _payment_402_error() -> Exception:
    """402 欠费：openai SDK 无专属子类，落到 APIStatusError 基类（DeepSeek 实测形态）。"""
    from openai import APIStatusError

    response = httpx.Response(
        402,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={"error": {"code": "insufficient_balance", "message": "Insufficient Balance", "type": "invalid_request_error"}},
    )
    return APIStatusError("Error code: 402 - Insufficient Balance", response=response, body=None)


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
    # 抖动（2026-09-15）：wait_seconds 是抖动后的真值（基准 0.01 × [0.5, 1.5]）
    assert 0.005 <= retries[0]["wait_seconds"] <= 0.015
    # scope 缺省 main（stub 直抛未标记异常；2026-09-15 additive）
    assert retries[0]["scope"] == "main"


def test_classify_error_codes():
    """错误定性（agent.error/run.state 的 code 取值域）：配置缺失/401/402→llm_auth、
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
    # 402 欠费（2026-09-12 实装）：同样归 llm_auth（重试救不了），文案指向服务商充值
    code, msg = agent_mod._classify_error(_payment_402_error())
    assert code == "llm_auth"
    assert "额度不足" in msg
    assert "服务商平台充值" in msg
    assert "设置 → 模型" not in msg  # 设置里充不了值，不误导
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
    assert "_NoThinkingRetryCompletions(model.client" in src
    # 撞线学习回调必须接到共享模型实例的 profile（比例档压缩中间件活读它）
    assert "on_overflow_window=_learn_overflow_window" in src


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
    for kw in ("禁止调用", "check_pipeline_state", "禁止读 写作指引", "一次读齐"):
        assert kw in prompt, f"写手 prompt 缺少开局瘦身禁令关键词：{kw}"
    # 派发拼装的目标必须确实是 SUBAGENTS 里的名字（防止常量与字面量漂移）
    assert any(
        s["name"] == agent_mod._BODY_WRITER_NAME for s in agent_mod.SUBAGENTS
    )


def test_body_writer_minimal_toolset():
    """写手最小工具集（2026-09-10；2026-09-14 加 docx_diagram_insert/docx_html_figure 共 15 个）：
    spec 带 tools 字段收窄；集合内名字必须在 TOOLS 注册表（防拼错=静默丢工具）；
    禁用名不得「顺手加回」。"""
    from app.tools import TOOLS

    writer = next(s for s in agent_mod.SUBAGENTS if s["name"] == agent_mod._BODY_WRITER_NAME)
    assert "tools" in writer, "写手 spec 缺 tools 字段——deepagents 会继承全量 TOOLS"
    names = {t.name for t in writer["tools"]}
    assert names == set(agent_mod._BODY_WRITER_TOOLS), "spec 工具集与常量漂移"
    registry = {t.name for t in TOOLS}
    unknown = names - registry
    assert not unknown, f"写手工具集含未注册名字（拼错即静默丢工具）：{unknown}"
    banned = {
        "ask_human", "check_pipeline_state", "docx_assemble_volume", "read_artifact",
        "assemble_tender", "publish_artifact", "update_task_progress",
        "validate_analysis", "list_templates",
    }
    assert not (names & banned), f"禁用工具混入写手工具集：{names & banned}"


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
    assert "_apply_window_profile(model, p)" in src, "build_agent 缺少窗口四层取值接线"

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


def test_apply_window_profile_four_layers(monkeypatch):
    """窗口四层取值：用户手选 > DeepSeek 注册表 > 社区缓存 > 保守默认 17 万。"""
    monkeypatch.setattr(
        agent_mod.model_registry,
        "lookup",
        lambda name: 131072 if name == "gw-alias" else None,
    )

    def _model(name):
        return agent_mod._RunAwareChatDeepSeek(
            api_key="sk-test", base_url="https://example.invalid/v1", model=name
        )

    def _profile(name, context_window=None):
        return cfg.ModelProfile(
            id="p1", name="A", base_url="https://example.invalid/v1",
            model=name, context_window=context_window,
        )

    # 层1：用户手选最高优先（注册表已知名也覆盖）
    m = _model("deepseek-v4-flash")
    agent_mod._apply_window_profile(m, _profile("deepseek-v4-flash", context_window=128000))
    assert m.profile["max_input_tokens"] == 128000

    # 层2：注册表已知名（deepseek 系）不覆盖
    m2 = _model("deepseek-v4-flash")
    agent_mod._apply_window_profile(m2, _profile("deepseek-v4-flash"))
    assert m2.profile["max_input_tokens"] == 1000000

    # 层3：社区注册表缓存命中
    m3 = _model("gw-alias")
    agent_mod._apply_window_profile(m3, _profile("gw-alias"))
    assert m3.profile["max_input_tokens"] == 131072

    # 层4：兜底保守默认（并进入比例档——学习校准后档位能立即生效的前提）
    m4 = _model("another-custom")
    agent_mod._apply_window_profile(m4, _profile("another-custom"))
    assert m4.profile["max_input_tokens"] == agent_mod._FALLBACK_WINDOW_TOKENS == 170_000


def test_make_summarization_middleware_caps_trim():
    """自建压缩中间件：复刻库默认档（比例/固定随 profile 有无），仅 trim 改 200K。"""
    m = agent_mod._RunAwareChatDeepSeek(
        api_key="sk-test", base_url="https://example.invalid/v1", model="deepseek-v4-flash"
    )
    mw = agent_mod._make_summarization_middleware(m, backend=object())
    assert mw._lc_helper.trigger == ("fraction", 0.85)
    assert mw._lc_helper.keep == ("fraction", 0.1)
    assert mw._lc_helper.trim_tokens_to_summarize == agent_mod._SUMMARY_INPUT_CAP == 200_000

    # 未知模型名且未预设 profile：与库工厂同款固定档（build_agent 实际路径总是先
    # _apply_window_profile 兜底进比例档，此处验证工厂本身不私改无档案行为）
    m2 = agent_mod._RunAwareChatDeepSeek(
        api_key="sk-test", base_url="https://example.invalid/v1", model="custom-gw-name"
    )
    mw2 = agent_mod._make_summarization_middleware(m2, backend=object())
    assert mw2._lc_helper.trigger == ("tokens", 170000)
    assert mw2._lc_helper.keep == ("messages", 6)


def test_deepagents_same_name_replacement_semantics():
    """库行为守卫：middleware 列表里同名实例原地顶掉内置压缩中间件——本批接线
    （主栈/subagent spec/GP 继承）全部押在这个语义上，deepagents 升级若改掉当场红。"""
    from deepagents.backends import StateBackend
    from deepagents.graph import _apply_custom_middleware
    from deepagents.middleware.summarization import create_summarization_middleware

    m = agent_mod._RunAwareChatDeepSeek(
        api_key="sk-test", base_url="https://example.invalid/v1", model="deepseek-v4-flash"
    )
    ours = agent_mod._make_summarization_middleware(m, backend=StateBackend())
    assert ours.name == "SummarizationMiddleware", "公开别名直接构造的实例名必须恰为同名替换键"

    base = [create_summarization_middleware(m, StateBackend())]
    out = _apply_custom_middleware(base, [ours], core_names={base[0].name})
    assert out[0] is ours, "同名条目应原地替换而非追加（追加=双压缩中间件）"


def test_summarization_middleware_wired_in_build_agent():
    """接线守卫：主栈与 subagent spec 都注入自建压缩中间件（同名替换路径）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "_make_summarization_middleware(model, backend)" in src
    assert 'subagents=[{**spec, "middleware": [summ, *spec["middleware"]]} for spec in SUBAGENTS]' in src
    assert "middleware=[\n            summ," in src


def test_overflow_400_learns_window_from_message():
    """撞线学习：超限文案披露真实上限时回调校准（DeepSeek/OpenAI 兼容主流措辞）。"""
    import pytest
    from langchain_core.exceptions import ContextOverflowError

    learned = []
    inner = _RecordingCompletions(
        [
            _overflow_400(
                "This model's maximum context length is 131072 tokens. However, you "
                "requested 150000 tokens. Please reduce the length of the messages."
            )
        ]
    )
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, on_overflow_window=learned.append)
    with pytest.raises(ContextOverflowError):
        wrapper.create(model="m", messages=[])
    assert learned == [131072]


def test_overflow_400_learn_rejects_unparseable_wordings():
    """宁缺勿错：无数字措辞 / 数字超 sanity 区间都不学（学到偏大值会压不住撞线）。"""
    import pytest
    from langchain_core.exceptions import ContextOverflowError

    # Anthropic 措辞（数字不在两种受认模式里）→ 不学
    learned = []
    inner = _RecordingCompletions([_overflow_400("prompt is too long: 210000 tokens > 200000 maximum")])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, on_overflow_window=learned.append)
    with pytest.raises(ContextOverflowError):
        wrapper.create(model="m", messages=[])
    assert learned == []

    # 数字位数爆炸（截取前 9 位 = 999999999 > sanity 上限 2M）→ 不学
    learned2 = []
    inner2 = _RecordingCompletions(
        [_overflow_400("maximum context length is 99999999999999 tokens")]
    )
    wrapper2 = agent_mod._NoThinkingRetryCompletions(inner2, on_overflow_window=learned2.append)
    with pytest.raises(ContextOverflowError):
        wrapper2.create(model="m", messages=[])
    assert learned2 == []

    # 纯解析函数边界：三位数不匹配 \d{4,9}
    assert agent_mod._parse_context_limit("maximum context length is 999 tokens") is None
    assert agent_mod._parse_context_limit("context window is 131072") == 131072


# ---- 自适应并发闸接线（2026-09-15，llm_throttle） ----


def _rate_limit_429() -> Exception:
    from openai import RateLimitError

    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://gw.example/v1/chat/completions"),
        json={"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached for requests", "type": "rate_limit_error"}},
    )
    return RateLimitError(
        "Error code: 429 - Rate limit reached for requests",
        response=response,
        body=None,
    )


def _request_timeout() -> Exception:
    from openai import APITimeoutError

    return APITimeoutError(request=httpx.Request("POST", "https://gw.example/v1/chat/completions"))


def test_throttle_429_shrinks_limiter_hard_and_reraises():
    """429 = 硬背压：许可按 hard 归还（limit 减半）且原样上抛走既有重试链。"""
    import pytest
    from openai import RateLimitError

    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([_rate_limit_429()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    with pytest.raises(RateLimitError):
        wrapper.create(model="m", messages=[])
    assert lim.limit == 4
    assert lim.inflight == 0


def test_throttle_timeout_soft_shrinks_one_step():
    """请求超时 = 弱背压：soft 归还（limit −1）后上抛。"""
    import pytest
    from openai import APITimeoutError

    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([_request_timeout()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    with pytest.raises(APITimeoutError):
        wrapper.create(model="m", messages=[])
    assert lim.limit == 7
    assert lim.inflight == 0


def test_throttle_other_errors_neutral():
    """其余异常（如普通 400）只归还许可，不调闸——与网关容量无关。"""
    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([_other_400()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    try:
        wrapper.create(model="m", messages=[], reasoning_effort="low")
        raise AssertionError("应上抛 BadRequestError")
    except Exception:
        pass
    assert lim.limit == 8
    assert lim.inflight == 0


def test_throttle_nonstream_success_releases_ok():
    """非流式成功：ok 归还（limit 不动），响应原样透传。"""
    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    ok = object()
    inner = _RecordingCompletions([ok])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    assert wrapper.create(model="m", messages=[]) is ok
    assert lim.inflight == 0
    assert lim.limit == 8


def test_throttle_stream_releases_on_exhaustion():
    """流式：create 返回时许可仍持有（流未消费），耗尽后才 ok 归还。"""
    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([["a", "b"]])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    stream = wrapper.create(model="m", messages=[], stream=True)
    assert lim.inflight == 1, "流式 create 返回≠流结束，许可必须仍持有"
    assert list(stream) == ["a", "b"]
    assert lim.inflight == 0
    assert lim.limit == 8


def test_throttle_stream_releases_on_early_exit():
    """流式提前放弃（with 块未耗尽退出）：__exit__ 路径归还许可，不泄漏。"""
    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([iter(["a", "b", "c"])])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    with wrapper.create(model="m", messages=[], stream=True) as stream:
        it = iter(stream)  # 持引用：临时 iter() 被式后 GC 会走生成器 finally 归还（另一条合法归路）
        assert next(it) == "a"
        assert lim.inflight == 1
    assert lim.inflight == 0, "with 提前退出应经 __exit__ 归还许可"


def test_throttle_stream_releases_on_generator_gc():
    """消费方弃掉迭代器（持引用消失 → GC close 生成器）：finally 路径归还许可。

    这是许可防泄漏的关键兜底——流式 create 已返回、迭代器又被弃置时，没有这条
    路许可会一直被占（直到进程重启）。"""
    import gc

    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([iter(["a", "b", "c"])])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    stream = wrapper.create(model="m", messages=[], stream=True)
    it = iter(stream)
    assert next(it) == "a"
    assert lim.inflight == 1
    del it, stream
    gc.collect()  # 生成器引用归零 → close → GeneratorExit → finally 归还
    assert lim.inflight == 0


def test_throttle_release_idempotent_across_paths():
    """归还可以多路触发（流耗尽 + __exit__/GC）：one-shot 抢锁保证不重复归还。"""
    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([iter(["a"])])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    with wrapper.create(model="m", messages=[], stream=True) as stream:
        list(stream)  # 耗尽 → 生成器 finally 已归还
    # with 退出 → __exit__ 再触发一次 on_release；inflight 不应为 -1
    assert lim.inflight == 0


def test_throttle_stream_explicit_close_releases():
    """显式 close()（不经 with 协议、也从未迭代）：必须归还许可且不算成功样本。

    close 若走 __getattr__ 委派到内层就绕过了归还钩子——没人 iter 过时生成器
    finally 不存在，许可直接漏。"""
    from app import llm_throttle

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([iter(["a", "b"])])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    stream = wrapper.create(model="m", messages=[], stream=True)
    assert lim.inflight == 1
    stream.close()
    assert lim.inflight == 0
    # NEUTRAL 归还：成功连击不因半途 close +1（streak 保持 0）
    assert lim.limit == 8


def test_throttle_wired_in_build_agent():
    """build_agent 把 per-profile 并发闸接进 wrapper（沿用源码断言先例）；
    上限与图并发步数单源对齐。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "llm_throttle.for_profile(p.id, ceiling=_MAX_CONCURRENT_STEPS)" in src
    assert "limiter=limiter" in src


def test_jittered_backoff_stays_in_bounds():
    """退避抖动 ±50%：多轮采样全部落在界内（载荷与真实等待共用抖动值）。"""
    for _ in range(50):
        v = agent_mod._jittered_backoff(3.0)
        assert 1.5 <= v <= 4.5
    assert agent_mod._jittered_backoff(10.0) <= 15.0


# ---- 重试失败源归属（2026-09-15，agent.retry scope additive） ----


def test_exc_agent_scope_walker():
    """walker：直挂 / cause 链穿透（langchain raise ... from e）/ 无标记兜底 main /
    环链不死循环。"""
    e1 = ValueError("直挂")
    e1._tender_agent_scope = "sub"
    assert agent_mod._exc_agent_scope(e1) == "sub"
    inner = ValueError("inner")
    inner._tender_agent_scope = "sub"
    outer = ValueError("outer")
    outer.__cause__ = inner  # langchain 包装同款形状
    assert agent_mod._exc_agent_scope(outer) == "sub"
    # 深链：两层 cause 也能读到
    deeper = ValueError("deeper")
    deeper._tender_agent_scope = "sub"
    mid = ValueError("mid")
    mid.__cause__ = deeper
    outer2 = ValueError("outer2")
    outer2.__cause__ = mid
    assert agent_mod._exc_agent_scope(outer2) == "sub"
    # 无标记
    assert agent_mod._exc_agent_scope(ValueError("plain")) == "main"
    # 环链（防御：深度上限兜住）
    a, b = ValueError("a"), ValueError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert agent_mod._exc_agent_scope(a) == "main"


def test_throttle_wrapper_tags_scope_on_error():
    """建连期错误（429）：抛出点在 runctx 作用域内挂 scope——异常带着归属上抛。"""
    import pytest
    from openai import RateLimitError

    from app import llm_throttle
    from app import runctx as _rc

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([_rate_limit_429()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    token = _rc.set_agent_scope("sub")
    try:
        with pytest.raises(RateLimitError) as ei:
            wrapper.create(model="m", messages=[])
    finally:
        _rc.reset_agent_scope(token)
    assert getattr(ei.value, "_tender_agent_scope", None) == "sub"


def test_stream_midstream_error_tagged_scope():
    """流中途断连（裸 httpx 异常不经 langchain 包装）：生成器 except 是挂归属的
    唯一机会。"""
    import pytest

    from app import llm_throttle
    from app import runctx as _rc

    def _boom_stream():
        yield "a"
        raise httpx.RemoteProtocolError("peer closed connection")

    lim = llm_throttle.AIMDLimiter(ceiling=8)
    inner = _RecordingCompletions([_boom_stream()])
    wrapper = agent_mod._NoThinkingRetryCompletions(inner, limiter=lim)
    token = _rc.set_agent_scope("sub")
    try:
        with pytest.raises(httpx.RemoteProtocolError) as ei:
            list(wrapper.create(model="m", messages=[], stream=True))
    finally:
        _rc.reset_agent_scope(token)
    assert getattr(ei.value, "_tender_agent_scope", None) == "sub"
    assert lim.inflight == 0  # 异常路径许可照常归还


def test_retry_payload_carries_scope_from_tagged_exception(monkeypatch):
    """worker 重试：异常链带 sub 标记 → agent.retry 载荷 scope=sub + llm_retry
    伪步骤 summary 标「子代理」（用户可见断在哪一侧）。"""
    monkeypatch.setattr(agent_mod, "_LLM_RETRY_BACKOFFS", (0.01, 0.01))
    inner = ModelConnectionError("peer closed connection")
    inner._tender_agent_scope = "sub"
    wrapped = ModelConnectionError("peer closed connection")
    wrapped.__cause__ = inner  # langchain raise ... from e 同款形状
    stub = _FlakyAgent(1, wrapped, _ok_items())
    published: list[tuple[str, dict]] = []
    _text, error, _ecode, trace, _interrupt = _run_agent_stream(
        stub, "c1", "r1", None, lambda e, d: published.append((e, d)), "hi", None
    )
    assert error is None
    retries = [d for e, d in published if e == "agent.retry"]
    assert len(retries) == 1
    assert retries[0]["scope"] == "sub"
    steps = [s for s in trace["tools"] if s["tool"] == "llm_retry"]
    assert len(steps) == 1
    assert steps[0]["args"]["scope"] == "sub"
    assert "子代理" in steps[0]["summary"]


def test_llm_retry_step_scope_default_main():
    """伪步骤 scope 缺省 main（旧调用方兼容），summary 标「主线程」。"""
    step = agent_mod._llm_retry_step(2, "boom", 8.0)
    assert step["args"]["scope"] == "main"
    assert "主线程" in step["summary"]


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


def _todo_stale_messages(n_rounds: int, *, with_write: bool = True) -> list:
    """构造「write_todos 之后又跑了 n 轮工具」的消息序列（每轮 AI 派发+结果两条）。"""
    msgs = [HumanMessage(content="开写整本")]
    if with_write:
        msgs.append(AIMessage(content="", tool_calls=[{"name": "write_todos", "args": {}, "id": "w1"}]))
        msgs.append(ToolMessage(content="Updated todo list to [...]", tool_call_id="w1"))
    for i in range(n_rounds):
        cid = f"t{i}"
        msgs.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": cid}]))
        msgs.append(ToolMessage(content=f"节 {i} 完成", tool_call_id=cid))
    return msgs


def test_todo_freshness_middleware_nudges_when_stale():
    """清单陈旧提醒：距上次 write_todos 超阈值 → 末条 ToolMessage 尾部追加提醒
    （含消息数实数）；system 与其余消息原对象不动（前缀缓存字节不变）。"""
    import dataclasses as dc

    @dc.dataclass
    class _Req:
        system_message: object
        messages: list

    msgs = _todo_stale_messages(6)  # write_todos 之后 12 条 ≥ 阈值 10
    req = _Req(system_message=SystemMessage(content="主提示词"), messages=msgs)
    seen = {}

    def handler(r):
        seen["msgs"] = r.messages
        seen["system"] = r.system_message
        return "resp"

    agent_mod._TodoFreshnessMiddleware().wrap_model_call(req, handler)
    out = seen["msgs"]
    assert out[-1].content.endswith("再继续当前工作。")
    assert "12 条消息未更新" in out[-1].content
    assert seen["system"] is req.system_message
    assert all(a is b for a, b in zip(out[:-1], msgs[:-1]))  # 只有末条是拷贝
    assert out[-1] is not msgs[-1]


def test_todo_freshness_middleware_quiet_paths():
    """四不提醒：清单新鲜 / 本 run 从未写清单 / 末条是 HumanMessage（HITL resume 后
    不往用户消息上贴）；回写后（新一轮 write_todos 落在尾部附近）提醒消失。"""
    import dataclasses as dc

    @dc.dataclass
    class _Req:
        system_message: object
        messages: list

    mw = agent_mod._TodoFreshnessMiddleware()

    def run(req):
        seen = {}

        def handler(r):
            seen["msgs"] = r.messages
            return "resp"

        mw.wrap_model_call(req, handler)
        return seen["msgs"]

    fresh = _Req(system_message=None, messages=_todo_stale_messages(3))  # 6 条 < 10
    assert run(fresh) is fresh.messages
    never = _Req(system_message=None, messages=_todo_stale_messages(6, with_write=False))
    assert run(never) is never.messages
    hitl = _Req(
        system_message=None,
        messages=_todo_stale_messages(6) + [HumanMessage(content="确认，按指引开写")],
    )
    assert run(hitl) is hitl.messages
    rewritten = _todo_stale_messages(6) + [
        AIMessage(content="", tool_calls=[{"name": "write_todos", "args": {}, "id": "w2"}]),
        ToolMessage(content="Updated todo list to [...]", tool_call_id="w2"),
    ]
    out = run(_Req(system_message=None, messages=rewritten))
    assert out[-1].content == "Updated todo list to [...]"


def test_todo_freshness_middleware_wired():
    """陈旧提醒只挂主 agent（TodoListMiddleware 旁）；SUBAGENTS 不挂——子代理
    没有 todos（tools 步骤树按 agent_id 归子代理、todo.updated 仅主图）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "_TodoFreshnessMiddleware()" in src
    assert not any(
        isinstance(m, agent_mod._TodoFreshnessMiddleware)
        for s in agent_mod.SUBAGENTS
        for m in (s.get("middleware") or [])
    )


# ---- 清单同步守卫（after_model，2026-09-13 二批） ----


def _gate_state(msgs, todos=None):
    """after_model 的 state 形状：messages + todos（None=用非空默认，模拟已建清单）。"""
    if todos is None:
        todos = [{"content": "写正文", "status": "in_progress"}]
    return {"messages": msgs, "todos": todos}


def test_todo_sync_gate_rejects_stale_dispatch_batch():
    """滞后超阈值 + 纯 task 批 → 每个 task 调用得 error ToolMessage（带对应 id 与
    指引文案）；路由层把这些调用判为「已应答」不再执行、跳回模型节点——零个派发
    落地（全批原子，漏放行半个批=带着旧清单继续执行）。"""
    msgs = _todo_stale_messages(6)  # write_todos 之后 12 条 ≥ 守卫阈值 6
    msgs.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": f"b{i}"} for i in range(3)]))
    out = agent_mod._TodoFreshnessMiddleware().after_model(_gate_state(msgs), None)
    assert out is not None and len(out["messages"]) == 3
    errs = out["messages"]
    assert {e.tool_call_id for e in errs} == {"b0", "b1", "b2"}
    assert all(e.status == "error" and e.name == "task" for e in errs)
    assert all(agent_mod._TODO_GATE_MARK in e.content for e in errs)
    assert "距上次回写" in errs[0].content


def test_todo_sync_gate_same_batch_write_exemption():
    """同批豁免：write_todos 与 task 同一 AIMessage → 放行（「回写+派发」同轮的
    常态路径，免重试往返；write_todos 禁并行的只是多个 write_todos）。"""
    msgs = _todo_stale_messages(6)
    msgs.append(AIMessage(content="", tool_calls=[
        {"name": "write_todos", "args": {}, "id": "w9"},
        {"name": "task", "args": {}, "id": "b0"},
    ]))
    assert agent_mod._TodoFreshnessMiddleware().after_model(_gate_state(msgs), None) is None


def test_todo_sync_gate_quiet_paths():
    """放行：清单新鲜（刚回写）/ 会话从未建清单（todos 空）/ 批内无 task 调用 /
    纯文本回复无 tool_calls / state 缺消息键（防御，增强逻辑绝不打断 run）。"""
    mw = agent_mod._TodoFreshnessMiddleware()
    fresh = _todo_stale_messages(0)  # [Human, AI(write), Tool(write)]
    fresh.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "b0"}]))
    assert mw.after_model(_gate_state(fresh), None) is None  # 距基线 1 条 < 6
    stale = _todo_stale_messages(6)
    stale.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "b0"}]))
    assert mw.after_model(_gate_state(stale, todos=[]), None) is None  # 无清单不逼建
    other = _todo_stale_messages(6)
    other.append(AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "f1"}]))
    assert mw.after_model(_gate_state(other), None) is None  # 非 task 批不拦
    plain = _todo_stale_messages(6) + [AIMessage(content="阶段汇报")]
    assert mw.after_model(_gate_state(plain), None) is None
    assert mw.after_model({"todos": [{"content": "x", "status": "pending"}]}, None) is None


def test_todo_sync_gate_forces_refresh_after_hitl_answer():
    """裁决后未回写即派发 → 计数再低也拒（2026-09-13 实测事故的回归用例：回答完
    直接派第一波、面板停在上一阶段 4 分钟）。代答识别 = tool_call_id 对应
    ask_human 调用、位于最后一次 write_todos 结果之后。"""
    msgs = [
        HumanMessage(content="开写整本"),
        AIMessage(content="", tool_calls=[{"name": "write_todos", "args": {}, "id": "w1"}]),
        ToolMessage(content="Updated todo list to [...]", tool_call_id="w1"),
        AIMessage(content="", tool_calls=[{"name": "ask_human", "args": {}, "id": "a1"}]),
        ToolMessage(content="已选：确认，按指引开写（推荐）", tool_call_id="a1"),  # HITL 代答
        AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "b0"}]),
    ]
    out = agent_mod._TodoFreshnessMiddleware().after_model(_gate_state(msgs), None)
    assert out is not None and "你刚收到用户的回答" in out["messages"][0].content


def test_todo_sync_gate_valve_opens_after_bounded_rejections():
    """泄压阀：同一基线之后已有 3 条守卫拒绝仍不回写 → 放行派发（有界拒绝防病态
    循环卡死 run）；2 条时仍在拦。拒绝按文案标记从消息序列无状态计数。"""
    mw = agent_mod._TodoFreshnessMiddleware()
    base = _todo_stale_messages(6)
    for n in (2, 3):
        msgs = list(base)
        for i in range(n):
            msgs.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": f"r{i}"}]))
            msgs.append(ToolMessage(
                content=f"{agent_mod._TODO_GATE_MARK}任务清单已滞后实际进度（距上次回写 13 条消息）。",
                tool_call_id=f"r{i}", status="error", name="task",
            ))
        msgs.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "b0"}]))
        out = mw.after_model(_gate_state(msgs), None)
        if n < agent_mod._TODO_GATE_VALVE:
            assert out is not None
        else:
            assert out is None


def test_todo_sync_gate_aafter_model_delegates():
    """基类默认 aafter_model 空实现不委托同步版（框架按执行模式择一调用）——
    显式转发必须有，否则异步图里守卫静默失灵。"""
    msgs = _todo_stale_messages(6)
    msgs.append(AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "b0"}]))

    async def _run():
        return await agent_mod._TodoFreshnessMiddleware().aafter_model(_gate_state(msgs), None)

    out = asyncio.run(_run())
    assert out is not None and out["messages"][0].tool_call_id == "b0"


# ---- 重派守卫（wrap_tool_call，2026-09-15 路径可靠性批） ----

_DIR_KEY = "tender.directory/tender-response-docs@1"


def _replay_env(tmp_path, monkeypatch, *, with_section=True, mtime=None):
    """重派守卫测试环境：任务+会话+run（起点=created_at）+目录产物+节文件。

    返回 (tid, run, sec_path)。mtime 显式指定可模拟「历史 run 写的旧节」。"""
    import os

    from app import db, publish
    from app.artifact_store import work_dir

    task, conv = init_env(tmp_path, monkeypatch)
    tid = task["id"]
    publish.publish_artifact(
        _DIR_KEY,
        {
            "response_documents": [
                {
                    "name": "技术部分",
                    "scope": "",
                    "directory": [
                        {"目录名称": "3.1 项目理解与需求分析", "level": 1, "children": [],
                         "交付形态": "正文编写"},
                    ],
                }
            ],
            "registry": {},
        },
        task_id=tid,
    )
    run = db.create_run(conv["id"])
    body = work_dir(tid) / "body"
    body.mkdir(parents=True, exist_ok=True)
    sec = body / "3.1 项目理解与需求分析.docx"
    if with_section:
        sec.write_bytes(b"docx")
        if mtime is not None:
            os.utime(sec, (mtime, mtime))
    return tid, run, sec


def _replay_dispatch(desc, handler_seen):
    def handler(req):
        handler_seen.append(dict(req.tool_call["args"]))
        return ToolMessage(content="ok", name="task", tool_call_id="call_test")

    return agent_mod._REPLAY_GUARD_MW.wrap_tool_call(
        _tc_request(
            "task",
            {"description": desc, "subagent_type": agent_mod._BODY_WRITER_NAME},
        ),
        handler,
    )


def test_replay_guard_blocks_same_run_rewrite_without_intent(tmp_path, monkeypatch):
    """本轮已写出的节 + 无重写意图 → 拒绝执行（handler 不被调），文案带守卫标记、
    规范路径与对账指引（r_eedd621716b5：13 节整波重放、86 次派发对 59 节书）。"""
    tid, run, _sec = _replay_env(tmp_path, monkeypatch)  # 节文件在 run 之后写（mtime 新）
    seen: list = []
    runctx.set_run("c1", run["id"], tid)
    try:
        out = _replay_dispatch("写 3.1 项目理解", seen)
    finally:
        runctx.clear_run()
        agent_mod._REPLAY_GUARD_STATE.clear()
    assert seen == []  # 未执行
    assert isinstance(out, ToolMessage) and out.status == "error"
    assert agent_mod._REPLAY_GUARD_MARK in out.content
    assert "body/3.1 项目理解与需求分析.docx" in out.content
    assert "check_pipeline_state" in out.content


def test_replay_guard_passes_for_intent_old_or_missing(tmp_path, monkeypatch):
    """放行面：描述含意图词（重写）/ 历史 run 写的旧节 / 节文件不存在 → 照常执行。"""
    import time as _time

    tid, run, sec = _replay_env(tmp_path, monkeypatch, mtime=_time.time() - 3600)
    seen: list = []
    runctx.set_run("c1", run["id"], tid)
    try:
        out = _replay_dispatch("重写 3.1 项目理解，按新要求更新", seen)
        assert out.content == "ok" and len(seen) == 1  # 意图词放行
        out = _replay_dispatch("写 3.1 项目理解", seen)
        assert out.content == "ok" and len(seen) == 2  # 旧文件（早于 run 起点）放行
        sec.unlink()
        out = _replay_dispatch("写 3.1 项目理解", seen)
        assert out.content == "ok" and len(seen) == 3  # 文件不存在放行
    finally:
        runctx.clear_run()
        agent_mod._REPLAY_GUARD_STATE.clear()


def test_replay_guard_blocks_multi_section_if_any_written_this_run(tmp_path, monkeypatch):
    """多节派发（2026-09-15 模型自主拆分批）：捆内任一节本轮已写 → 整体拒绝并
    点名已写节——把模型推回「对账后只补派缺失的节」（守卫若对多节首行失配即
    放行，断点续跑的整波重放就绕过守卫了）。"""
    from app import publish

    tid, run, sec = _replay_env(tmp_path, monkeypatch)  # 3.1 已在本轮写出
    publish.publish_artifact(
        _DIR_KEY,
        {
            "response_documents": [
                {
                    "name": "技术部分",
                    "scope": "",
                    "directory": [
                        {"目录名称": "3.1 项目理解与需求分析", "level": 1, "children": [],
                         "交付形态": "正文编写"},
                        {"目录名称": "3.2 总体设计方案", "level": 1, "children": [],
                         "交付形态": "正文编写"},
                    ],
                }
            ],
            "registry": {},
        },
        task_id=tid,
    )
    seen: list = []
    runctx.set_run("c1", run["id"], tid)
    try:
        out = _replay_dispatch("写 3.1 项目理解、3.2 总体设计", seen)
    finally:
        runctx.clear_run()
        agent_mod._REPLAY_GUARD_STATE.clear()
    assert seen == []  # 未执行（整捆拒绝，哪怕 3.2 还没写）
    assert isinstance(out, ToolMessage) and out.status == "error"
    assert "3.1 项目理解与需求分析" in out.content  # 点名已写节
    assert "check_pipeline_state" in out.content


def test_replay_guard_valve_opens_after_bounded_rejections(tmp_path, monkeypatch):
    """泄压阀：同 run 拒绝满 _REPLAY_GUARD_VALVE 次后放行（防「拒绝→原样重发」
    死循环烧轮次）；拒绝计数在 run 收尾清理（finally 钩子）。"""
    tid, run, _sec = _replay_env(tmp_path, monkeypatch)
    seen: list = []
    runctx.set_run("c1", run["id"], tid)
    try:
        for _ in range(agent_mod._REPLAY_GUARD_VALVE):
            _replay_dispatch("写 3.1 项目理解", seen)
        assert len(seen) == 0  # 阀内全拒
        out = _replay_dispatch("写 3.1 项目理解", seen)
        assert out.content == "ok" and len(seen) == 1  # 阀打开放行
    finally:
        runctx.clear_run()
        agent_mod._REPLAY_GUARD_STATE.clear()


def test_replay_guard_quiet_paths(tmp_path, monkeypatch):
    """非 task / 非写手子代理 / 无任务上下文 / 节名对不上 → 直通不评判。"""
    tid, run, _sec = _replay_env(tmp_path, monkeypatch)
    seen: list = []

    def handler(req):
        seen.append(req.tool_call["name"])
        return ToolMessage(content="ok", name=req.tool_call["name"], tool_call_id="call_test")

    runctx.set_run("c1", run["id"], tid)
    try:
        agent_mod._REPLAY_GUARD_MW.wrap_tool_call(_tc_request("ls", {"path": "/x"}), handler)
        agent_mod._REPLAY_GUARD_MW.wrap_tool_call(
            _tc_request("task", {"description": "写 3.1 项目理解", "subagent_type": "general-purpose"}),
            handler,
        )
        agent_mod._REPLAY_GUARD_MW.wrap_tool_call(
            _tc_request("task", {"description": "写一个不存在的节", "subagent_type": agent_mod._BODY_WRITER_NAME}),
            handler,
        )
    finally:
        runctx.clear_run()
        agent_mod._REPLAY_GUARD_STATE.clear()
    runctx.clear_run()
    agent_mod._REPLAY_GUARD_MW.wrap_tool_call(
        _tc_request("task", {"description": "写 3.1 项目理解", "subagent_type": agent_mod._BODY_WRITER_NAME}),
        handler,
    )
    assert seen == ["ls", "task", "task", "task"]  # 全部直通


def test_replay_guard_wired():
    """守卫只挂主栈（派发归主线程；写手子代理不派 task）；SUBAGENTS 不挂。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "_REPLAY_GUARD_MW" in src
    assert not any(
        isinstance(m, agent_mod._ReplayGuardMiddleware)
        for s in agent_mod.SUBAGENTS
        for m in (s.get("middleware") or [])
    )


def test_sub_reasoning_buffer_collapses_to_single_copy():
    """子代理思考缓冲 join 后收敛为单元素：run 期间思考文本单份驻留（不再
    chunk 列表+拼好串双份），后续 chunk 追加的增量 join 语义不变。"""
    steps = [{"tool": "task", "tool_call_id": "s1", "reasoning": ""}]
    bufs = {"s1": ["思", "考", "片", "段"]}
    agent_mod._sync_sub_reasoning(steps, bufs)
    assert steps[0]["reasoning"] == "思考片段"
    assert bufs["s1"] == ["思考片段"]
    bufs["s1"].append("继续")
    agent_mod._sync_sub_reasoning(steps, bufs)
    assert steps[0]["reasoning"] == "思考片段继续"
    assert bufs["s1"] == ["思考片段继续"]


def test_live_trace_throttle_dense_events_share_one_copy(monkeypatch):
    """快照节流：窗口内密集 set 只真拷一次（pending 记引用），读侧窗口内沿用
    旧快照、超窗后补拷最新——治「每结构性事件整树 deepcopy」的平方放大。"""
    clock = {"t": 1000.0}
    monkeypatch.setattr(agent_mod.time, "monotonic", lambda: clock["t"])
    copies = {"n": 0}
    real = agent_mod._copy_live_trace

    def counting(rid, trace):
        copies["n"] += 1
        return real(rid, trace)

    monkeypatch.setattr(agent_mod, "_copy_live_trace", counting)

    tree = {"tools": [{"id": "t1", "tool": "read"}], "todos": [], "reasoning": ""}
    agent_mod.set_live_trace("r_th", tree)
    clock["t"] += 0.1
    agent_mod.set_live_trace("r_th", {**tree, "reasoning": "第2次"})
    clock["t"] += 0.1
    agent_mod.set_live_trace("r_th", {**tree, "reasoning": "第3次"})
    assert copies["n"] == 1  # 密集期只有首次真拷
    snap = agent_mod.get_live_trace("r_th")
    assert snap["reasoning"] == ""  # 窗口内读侧沿用旧快照，不并发拷 worker 的树
    clock["t"] += agent_mod._LIVE_TRACE_WINDOW  # 超窗
    snap = agent_mod.get_live_trace("r_th")
    assert copies["n"] == 2  # 读侧补拷 pending 的最新树
    assert snap["reasoning"] == "第3次"
    agent_mod.clear_live_trace("r_th")
    assert agent_mod.get_live_trace("r_th") is None
    assert "r_th" not in agent_mod._LIVE_TRACE_PENDING
    assert "r_th" not in agent_mod._LIVE_TRACE_TS


def test_tool_timeout_middleware_wired():
    """超时中间件接进 build_agent 与两个 SUBAGENTS 条目（子代理直接调 docx 族
    工具）；重工具档的名字必须是真实注册的工具名（防漂移；task 来自 deepagents
    注入、不在 TOOLS 注册表）。"""
    import inspect

    src = inspect.getsource(agent_mod.build_agent)
    assert "_TOOL_TIMEOUT_MW" in src
    assert all(
        agent_mod._TOOL_TIMEOUT_MW in (s.get("middleware") or []) for s in agent_mod.SUBAGENTS
    )
    names = {getattr(t, "name", None) for t in agent_mod.TOOLS}
    heavy = {k for k, v in agent_mod._TOOL_TIMEOUTS.items() if v == agent_mod._TOOL_TIMEOUT_HEAVY}
    assert heavy <= names
    # 兜底制（2026-09-12）：ask_human 之外的任意工具都有档（未列名走默认档）
    assert agent_mod._TOOL_TIMEOUT_SKIP == frozenset({"ask_human"})


def test_tool_timeout_middleware_times_out_and_passes_through(monkeypatch):
    """超时中间件：默认档兜底（未列名工具也限时）、超时返回错误 ToolMessage（模型
    可缩小范围重试、run 正常收尾）；正常完成/异常原样透传；ask_human 不包。"""
    import time

    monkeypatch.setattr(agent_mod, "_TOOL_TIMEOUT_DEFAULT", 0.05)
    mw = agent_mod._ToolTimeoutMiddleware()

    class _Req:
        def __init__(self, name):
            self.tool_call = {"name": name, "id": f"tc_{name}", "args": {}}

    def slow(_req):
        time.sleep(0.3)
        return ToolMessage(content="不应到达", tool_call_id="tc_read_file")

    # 未列名工具走默认档（此前清单外工具 hang 无上界——会话被 409 钉死的死角）
    out = mw.wrap_tool_call(_Req("read_file"), slow)
    assert isinstance(out, ToolMessage) and out.status == "error"
    assert "工具超时" in out.content and "read_file" in out.content

    ok = ToolMessage(content="完成", tool_call_id="tc_docx_section_read")
    assert mw.wrap_tool_call(_Req("docx_section_read"), lambda _r: ok) is ok
    plain = "普通快速工具同步完成"
    assert mw.wrap_tool_call(_Req("read_file"), lambda _r: plain) is plain
    # ask_human 瞬时中断型：不包线程（身份透传）
    passthrough = object()
    assert mw.wrap_tool_call(_Req("ask_human"), lambda _r: passthrough) is passthrough

    def boom(_req):
        raise ValueError("工具异常原样回传")

    try:
        mw.wrap_tool_call(_Req("read_file"), boom)
        raise AssertionError("应当原样抛出")
    except ValueError:
        pass


def test_tool_timeout_middleware_cancel_aware(monkeypatch):
    """取消感知（2026-09-12）：等待循环查 CANCEL_EVENTS——置位即抛 _ToolCancelledError
    中止节点（不再等工具自然返回），入口预检挡掉 langgraph 的节点重试空转；
    task 档无硬上限、只靠取消停。"""
    import time

    from app import runctx

    monkeypatch.setattr(agent_mod, "_TOOL_CANCEL_POLL", 0.02)
    mw = agent_mod._ToolTimeoutMiddleware()
    rid = "r_cancel_test"
    event = threading.Event()
    agent_mod.CANCEL_EVENTS[rid] = event
    try:
        runctx.set_run("c1", rid, None, "low")

        class _Req:
            def __init__(self, name):
                self.tool_call = {"name": name, "id": f"tc_{name}", "args": {}}

        def slow(_req):
            time.sleep(0.5)
            return "不应到达"

        # 执行中置位取消（0.05s 后）→ ≤轮询粒度内抛出（0.5s 慢工具 vs 0.02 轮询）
        threading.Timer(0.05, event.set).start()
        t0 = time.monotonic()
        try:
            mw.wrap_tool_call(_Req("read_file"), slow)
            raise AssertionError("取消后应当抛出 _ToolCancelledError")
        except agent_mod._ToolCancelledError:
            pass
        assert time.monotonic() - t0 < 0.4

        # 入口预检：取消已置位时不再起线程执行 handler
        called = []

        def probe(_req):
            called.append(1)
            return "不应执行"

        try:
            mw.wrap_tool_call(_Req("read_file"), probe)
            raise AssertionError("应当预检抛出")
        except agent_mod._ToolCancelledError:
            pass
        assert called == []

        # task 档（无硬上限）取消同样生效
        event.clear()
        threading.Timer(0.05, event.set).start()
        t0 = time.monotonic()
        try:
            mw.wrap_tool_call(_Req("task"), lambda _r: time.sleep(1))
            raise AssertionError("task 取消后应当抛出")
        except agent_mod._ToolCancelledError:
            pass
        assert time.monotonic() - t0 < 0.6
    finally:
        agent_mod.CANCEL_EVENTS.pop(rid, None)
        runctx.clear_run()


def test_tool_timeout_middleware_no_runctx_task_passthrough(monkeypatch):
    """无 run 语境（独立实例）且无硬上限（task）时不包线程——只有开销没有收益。"""
    mw = agent_mod._ToolTimeoutMiddleware()
    runctx.clear_run()

    class _Req:
        tool_call = {"name": "task", "id": "tc_task", "args": {}}

    sentinel = object()
    assert mw.wrap_tool_call(_Req(), lambda _r: sentinel) is sentinel


def test_wrap_tool_call_runs_off_event_loop_in_real_graph():
    """守护超时中间件的承重假设：sync stream 驱动下 wrap_tool_call 在执行器
    线程跑、所在线程无事件循环（langgraph tool_node 的 async 路径若只有 sync
    钩子会在协程里直接调——届时 _ToolTimeoutMiddleware 的 done.wait(600) 会
    卡死事件循环，本测试红=驱动方式变了，须先改超时实现）。"""
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool as lc_tool
    from pydantic import PrivateAttr

    seen: dict = {}

    class _Probe(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            try:
                asyncio.get_running_loop()
                seen["loop"] = True
            except RuntimeError:
                seen["loop"] = False
            seen["main"] = threading.current_thread() is threading.main_thread()
            return handler(request)

    class _ScriptedChatModel(BaseChatModel):
        responses: list
        _idx: int = PrivateAttr(default=0)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            i = min(self._idx, len(self.responses) - 1)
            self._idx += 1
            return ChatResult(generations=[ChatGeneration(message=self.responses[i])])

        def bind_tools(self, tools, **kwargs):
            return self

        @property
        def _llm_type(self):
            return "scripted-test"

    @lc_tool
    def parse_document(file_path: str) -> str:
        """测试工具。"""
        return "ok"

    call_msg = AIMessage(
        content="", tool_calls=[{"name": "parse_document", "args": {"file_path": "x"}, "id": "t1"}]
    )
    graph = create_agent(
        _ScriptedChatModel(responses=[call_msg, AIMessage(content="done")]),
        tools=[parse_document],
        middleware=[_Probe()],
    )

    # 与 _run_agent_stream 同构：worker 线程里同步 stream
    t = threading.Thread(
        target=lambda: list(graph.stream({"messages": [("user", "hi")]}, stream_mode="updates"))
    )
    t.start()
    t.join()
    assert seen, "探针未被调用（真图未走到工具节点）"
    assert seen["loop"] is False, "wrap_tool_call 跑在事件循环线程上——超时中间件的阻塞等待会卡死 loop"
    assert seen["main"] is False


def test_retry_retired_steps_revive_on_same_call_id():
    """断流重试假终态收口（2026-09-10 review）：tools 节点失败的瞬时错误重试会
    复用同 tool_call_id 复跑——先标死的步骤要能被同 id 的真实 tool.result 覆写
    （_find_pending 放宽）与同 id 的 tool.called 复活（不产生第二张卡），
    done/真实 error 不受影响。"""
    from app.agent import (
        _RETRY_RETIRED_ERROR,
        _find_pending,
        _new_trace_step,
        _retire_broken_steps,
        _revive_step,
    )

    top = [_new_trace_step({"tool": "task", "tool_call_id": "call_1", "args": {"x": 1}})]
    top[0]["text"] = "派发前旁白"  # 封段产物
    published = []
    _retire_broken_steps(top, "r1", "c1", lambda ev, p: published.append((ev, p)))
    assert top[0]["status"] == "error" and top[0]["error"] == _RETRY_RETIRED_ERROR
    assert len(published) == 1 and published[0][1]["error"] == _RETRY_RETIRED_ERROR

    # ① 回填放宽：同 id 的真实 tool.result 找得到假终态步骤
    hit = _find_pending(top, {"tool": "task", "tool_call_id": "call_1"})
    assert hit is top[0]

    # ② 同 id 的 tool.called 复活：复位执行态、保留封段字段、不新建第二张
    revived = _revive_step(top, {"tool": "task", "tool_call_id": "call_1", "args": {}})
    assert revived is top[0]
    assert len(top) == 1
    assert top[0]["status"] == "running" and top[0]["error"] is None and top[0]["endedAt"] is None
    assert top[0]["text"] == "派发前旁白"  # 封段产物不被覆写

    # ③ 真实终态不受影响：done / 真实 error 既不回填也不复活
    top[0]["status"] = "done"
    assert _find_pending(top, {"tool": "task", "tool_call_id": "call_1"}) is None
    assert _revive_step(top, {"tool": "task", "tool_call_id": "call_1"}) is None
    top[0]["status"] = "error"
    top[0]["error"] = "真实工具错误"
    assert _find_pending(top, {"tool": "task", "tool_call_id": "call_1"}) is None
    assert _revive_step(top, {"tool": "task", "tool_call_id": "call_1"}) is None

    # ④ 子代理 children 里的假终态同样可回填（递归路径）
    child = _new_trace_step({"tool": "task", "tool_call_id": "call_kid"})
    child["status"] = "error"
    child["error"] = _RETRY_RETIRED_ERROR
    top2 = [
        {
            "id": "parent", "tool": "task", "status": "done", "summary": "", "error": None,
            "tool_call_id": "call_p", "children": [child], "args": {},
        }
    ]
    assert _find_pending(top2, {"tool": "task", "tool_call_id": "call_kid"}) is child
    assert _revive_step(top2, {"tool": "task", "tool_call_id": "call_kid"}) is child


def test_frozen_ctx_eviction_and_cleanup(monkeypatch):
    """_FROZEN_CTX 容量守卫收口（2026-09-10 review）：满 64 只逐条淘汰最旧、
    绝不全表 clear（旧版 clear 会把在跑长 run 的冻结块一并抹掉，system 中途
    变化=前缀缓存铁律事故复发）；run 终态由 _frozen_ctx_cleanup 清自己的条目。"""
    from app import agent as am

    monkeypatch.setattr(am, "_task_context_block", lambda tid, cid: f"块({tid})")
    saved = dict(am._FROZEN_CTX)
    am._FROZEN_CTX.clear()
    try:
        # 终态清理：清自己的、幂等、缺省静默
        am._FROZEN_CTX["r1"] = "块1"
        am._frozen_ctx_cleanup("r1")
        assert "r1" not in am._FROZEN_CTX
        am._frozen_ctx_cleanup(None)
        am._frozen_ctx_cleanup("r_missing")

        # 守卫：预塞 80 条（模拟清理失灵的长驻），新增一条后总量被压回 64、
        # 最旧的被淘汰、其余全保留（旧版 clear() 会清成 1 条）
        for i in range(80):
            am._FROZEN_CTX[f"r_old_{i:03d}"] = f"块{i}"
        am._FROZEN_CTX.pop("r_active", None)
        # 在跑长 run 的块：为验证不被误伤，把 r_active 塞为第 81 个（最新）
        am._FROZEN_CTX["r_active"] = "活跃块"
        am._task_context_block_frozen("t_x", "c_x", "r_new")
        assert len(am._FROZEN_CTX) <= 64
        assert "r_old_000" not in am._FROZEN_CTX  # 最旧被淘汰
        assert "r_active" in am._FROZEN_CTX  # 活跃块不被全清误伤
        assert "r_new" in am._FROZEN_CTX and am._FROZEN_CTX["r_new"]
        # 二次取值字节稳定（run 内冻结语义）
        again = am._task_context_block_frozen("t_x", "c_x", "r_new")
        assert again == am._FROZEN_CTX["r_new"]
    finally:
        am._FROZEN_CTX.clear()
        am._FROZEN_CTX.update(saved)
