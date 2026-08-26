"""_run_agent_stream：iter_stream 归一化事件 -> SSE 发布载荷的映射。

重点守护 tool.result 的 error 字段透传（历史上曾在重发布时被丢弃，导致前端把
失败工具渲染成成功）。
"""

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.agent import _run_agent_stream


class _StubAgent:
    """只需 stream()：产出 ("updates", {node: update}) 形状的片段。"""

    def __init__(self, items):
        self._items = items

    def stream(self, *_args, **_kwargs):
        return iter(self._items)


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
    """显式注册的子代理守护：两个执行单元齐全、都不直接向用户提问。

    interrupt_on={} 是整体替换继承——漏写会让子代理继承 ask_human/task 门禁，
    子代理的 ask_human 无人应答会挂死；tender-outline-writer 的提示词必须引用
    references（方法论单一事实源在 skill 里，不复制进提示词）。
    """
    from app.agent import SUBAGENTS

    specs = {s["name"]: s for s in SUBAGENTS}
    assert set(specs) == {"news-researcher", "tender-outline-writer"}
    for spec in specs.values():
        assert spec["interrupt_on"] == {}
        assert spec["system_prompt"].strip()
    writer = specs["tender-outline-writer"]
    for ref in ("generate.md", "annotation.md", "revise-gapfill.md", "revise-scoring.md", "revise-walkthrough.md"):
        assert ref in writer["system_prompt"]
    assert "禁止调用 ask_human" in writer["system_prompt"]
