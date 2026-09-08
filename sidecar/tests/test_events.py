"""iter_stream 对 todos 的提取与去重（todo.updated 只发变化），以及 reasoning 增量提取。"""

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from app.events import iter_stream

REMOVE_ALL = REMOVE_ALL_MESSAGES


def _updates(updates: list[dict]):
    """构造 agent.stream 的 ("updates", {node: update}) 片段。"""
    for u in updates:
        yield ("updates", {"model": u})


def _node_updates(node: str, updates: list[dict]):
    """构造指定节点的 updates 片段（测试中间件伪节点用）。"""
    for u in updates:
        yield ("updates", {node: u})


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


# ---------- 中间件伪节点的历史重放不得翻译成工具事件（2026-09-08 跨 run 重放修复） ----------


def _patch_update() -> dict:
    """deepagents PatchToolCallsMiddleware.before_agent 的状态重写载荷：
    [RemoveMessage(REMOVE_ALL), *整段历史消息原对象, *补插的取消 ToolMessage]——
    上一 run 中断遗留悬空 tool_calls 时，新 run 开头会下发这份整段历史。"""
    history = [
        AIMessage(
            content="查一下",
            tool_calls=[{"name": "read_file", "args": {"file_path": "a.md"}, "id": "call_L1_A", "type": "tool_call"}],
        ),
        ToolMessage(content="文件内容", name="read_file", tool_call_id="call_L1_A"),
    ]
    cancelled = ToolMessage(
        content="Tool call task with id call_L1_B was cancelled - another message came in before it could be completed.",
        name="task",
        tool_call_id="call_L1_B",
    )
    return {"messages": [RemoveMessage(id=REMOVE_ALL), *history, cancelled]}


def test_patch_tool_calls_history_rewrite_not_translated():
    """before_agent 补洞更新的整段历史重放：不得产出任何 tool_called/tool_result。"""
    stream = _node_updates("PatchToolCallsMiddleware.before_agent", [_patch_update()])
    assert [k for k, _ in iter_stream(stream)] == []


def test_summarization_before_model_rewrite_not_translated():
    """langchain 裸变体压缩的 before_model 状态重写（含保留消息原对象）同样跳过。"""
    rewrite = {
        "messages": [
            RemoveMessage(id=REMOVE_ALL),
            HumanMessage(content="Here is a summary of the conversation"),
            AIMessage(
                content="批",
                tool_calls=[{"name": "task", "args": {}, "id": "call_X", "type": "tool_call"}],
            ),
            ToolMessage(content="ok", name="task", tool_call_id="call_X"),
        ]
    }
    stream = _node_updates("SummarizationMiddleware.before_model", [rewrite])
    assert [k for k, _ in iter_stream(stream)] == []


def test_real_nodes_still_translated():
    """白名单不伤正常链路：model 节点的新 AIMessage(tool_calls) 与 tools 节点的 ToolMessage 照常翻译。"""
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "args": {"file_path": "b.md"}, "id": "call_new", "type": "tool_call"}],
    )
    tm = ToolMessage(content="done", name="read_file", tool_call_id="call_new")
    stream = iter(
        [
            ("updates", {"model": {"messages": [ai]}}),
            ("updates", {"tools": {"messages": [tm]}}),
        ]
    )
    kinds = [k for k, _ in iter_stream(stream)]
    assert kinds == ["tool_called", "tool_result"]


def test_pseudo_node_todos_still_flow():
    """todos 提取不 gated 白名单：伪节点更新携带 todos 时照常去重下发。"""
    todos = [{"content": "a", "status": "pending"}]
    stream = _node_updates("PatchToolCallsMiddleware.before_agent", [{"todos": todos, "messages": []}])
    assert [k for k, _ in iter_stream(stream)] == ["todo_updated"]
