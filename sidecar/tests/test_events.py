"""iter_stream 对 todos 的提取与去重（todo.updated 只发变化），以及 reasoning 增量提取。"""

from langchain_core.messages import AIMessageChunk, ToolMessage

from app.events import iter_stream


def _updates(updates: list[dict]):
    """构造 agent.stream 的 ("updates", {node: update}) 片段。"""
    for u in updates:
        yield ("updates", {"model": u})


def _messages(chunks: list[AIMessageChunk]):
    """构造 agent.stream 的 ("messages", (AIMessageChunk, meta)) 片段。"""
    for c in chunks:
        yield ("messages", (c, None))


def test_todo_updated_yielded_on_change():
    stream = _updates(
        [
            {"todos": [{"content": "a", "status": "pending"}], "messages": []},
            {
                "todos": [
                    {"content": "a", "status": "completed"},
                    {"content": "b", "status": "in_progress"},
                ],
                "messages": [],
            },
        ]
    )
    kinds = [k for k, _ in iter_stream(stream)]
    assert kinds == ["todo_updated", "todo_updated"]


def test_todo_updated_dedup_same():
    stream = _updates(
        [
            {"todos": [{"content": "a", "status": "pending"}], "messages": []},
            {"todos": [{"content": "a", "status": "pending"}], "messages": []},
        ]
    )
    kinds = [k for k, _ in iter_stream(stream)]
    assert kinds == ["todo_updated"]


def test_todo_updated_payload_is_todos():
    todos = [{"content": "解析招标文件", "status": "in_progress"}]
    stream = _updates([{"todos": todos, "messages": []}])
    _, payload = next(iter_stream(stream))
    assert payload == todos


def test_messages_still_flow_alongside_todos():
    """todos 存在时，messages 分支的 token 事件不受影响。"""
    stream = _updates(
        [
            {
                "todos": [{"content": "a", "status": "pending"}],
                "messages": [],
            }
        ]
    )
    assert [k for k, _ in iter_stream(stream)] == ["todo_updated"]


def test_tool_result_with_error_field_on_task_failure():
    """ToolMessage status=error 时 tool_result 应携带 error 字段。"""
    msg = ToolMessage(
        content="FileNotFoundError: /tmp/nope",
        name="convert_doc",
        status="error",
        tool_call_id="call_1",
    )
    stream = _updates([{"messages": [msg]}])
    kinds = [(k, p) for k, p in iter_stream(stream)]
    assert kinds[0][0] == "tool_result"
    payload = kinds[0][1]
    assert payload["tool"] == "convert_doc"
    assert payload["summary"].startswith("FileNotFoundError")
    assert payload["error"] is not None
    assert "FileNotFoundError" in payload["error"]


def test_tool_result_without_error_field_on_success():
    """ToolMessage status 正常时 tool_result 不应携带 error（None）。"""
    msg = ToolMessage(
        content="已生成 out/a.md",
        name="convert_doc",
        status="success",
        tool_call_id="call_2",
    )
    stream = _updates([{"messages": [msg]}])
    _, payload = next(iter_stream(stream))
    assert payload["error"] is None


def test_reasoning_yielded_when_chunk_has_reasoning_content():
    """AIMessageChunk 携带 reasoning_content 时应发 reasoning 事件（dict，agent_id 主图为 None）。"""
    chunk = AIMessageChunk(
        content="最终回答",
        additional_kwargs={"reasoning_content": "先读文档结构"},
    )
    kinds = list(iter_stream(_messages([chunk])))
    assert kinds == [
        ("reasoning", {"text": "先读文档结构", "agent_id": None}),
        ("token", "最终回答"),
    ]


def test_reasoning_not_yielded_without_reasoning_content():
    """无推理内容（非推理模型）时只有 token，不发 reasoning。"""
    chunk = AIMessageChunk(content="普通回答")
    kinds = list(iter_stream(_messages([chunk])))
    assert kinds == [("token", "普通回答")]


def test_reasoning_accumulates_across_chunks():
    """推理增量应逐块下发（前端累积），与 token 顺序一致。"""
    chunks = [
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "第一步"}),
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "第二步"}),
        AIMessageChunk(content="正文"),
    ]
    kinds = list(iter_stream(_messages(chunks)))
    assert kinds == [
        ("reasoning", {"text": "第一步", "agent_id": None}),
        ("reasoning", {"text": "第二步", "agent_id": None}),
        ("token", "正文"),
    ]


def test_reasoning_content_list_of_blocks():
    """reasoning_content 以内容块列表形式给出时也能提取。"""
    chunk = AIMessageChunk(
        content="",
        additional_kwargs={
            "reasoning_content": [{"type": "reasoning_text", "text": "推理片段"}]
        },
    )
    kinds = list(iter_stream(_messages([chunk])))
    assert kinds == [("reasoning", {"text": "推理片段", "agent_id": None})]
