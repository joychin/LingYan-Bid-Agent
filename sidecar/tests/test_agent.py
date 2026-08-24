"""_run_agent_stream：iter_stream 归一化事件 -> SSE 发布载荷的映射。

重点守护 tool.result 的 error 字段透传（历史上曾在重发布时被丢弃，导致前端把
失败工具渲染成成功）。
"""

from langchain_core.messages import ToolMessage

from app.agent import _run_agent_stream


class _StubAgent:
    """只需 stream()：产出 ("updates", {node: update}) 形状的片段。"""

    def __init__(self, items):
        self._items = items

    def stream(self, *_args, **_kwargs):
        return iter(self._items)


def test_tool_result_error_passthrough():
    bad = ToolMessage(
        content="FileNotFoundError: /tmp/nope",
        name="convert_tender",
        status="error",
        tool_call_id="c1",
    )
    ok = ToolMessage(
        content="已生成 out/a.md",
        name="build_tender",
        status="success",
        tool_call_id="c2",
    )
    items = [("updates", {"model": {"messages": [bad, ok]}})]
    published: list[tuple[str, dict]] = []
    text, error = _run_agent_stream(
        _StubAgent(items), "hi", "c1", "r1", lambda e, d: published.append((e, d))
    )
    assert error is None
    assert text == ""
    results = [d for e, d in published if e == "tool.result"]
    assert len(results) == 2
    assert results[0]["tool"] == "convert_tender"
    assert results[0]["error"] is not None
    assert "FileNotFoundError" in results[0]["error"]
    assert results[1]["tool"] == "build_tender"
    assert results[1]["error"] is None
