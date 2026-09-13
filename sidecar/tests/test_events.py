"""iter_stream 对 todos 的提取与去重（todo.updated 只发变化），以及 reasoning 增量提取。"""

from langchain.agents.middleware.internal_call_transformer import (
    INTERNAL_CALL_METADATA_KEY,
    internal_call_metadata,
)
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


# ---------- 中间件内部模型调用（压缩总结）不得流进正文/思考（2026-09-12 泄漏修复） ----------


def _internal_meta() -> dict:
    """langchain 内部调用标记：与 SummarizationMiddleware 打的标记同源同值。"""
    return {"langgraph_node": "model", **internal_call_metadata()}


def test_internal_call_chunks_not_streamed():
    """带内部调用标记的 chunk（token+reasoning）不产出任何事件——压缩总结
    （SESSION INTENT/SUMMARY/…）不得当正文/思考直播给用户；子代理 ns 同口径。"""
    chunks = [
        ((), "messages", (
            AIMessageChunk(
                content="## SESSION INTENT\n用户要编制标书……",
                additional_kwargs={"reasoning_content": "Let me construct the summary."},
            ),
            _internal_meta(),
        )),
        (("tools:t1",), "messages", (
            AIMessageChunk(
                content="",
                additional_kwargs={"reasoning_content": "subagent internal"},
            ),
            _internal_meta(),
        )),
    ]
    assert list(iter_stream(iter(chunks))) == []


def test_untagged_chunks_stream_normally():
    """普通调用的元数据（无内部标记键）照常产出，不受过滤影响。"""
    items = [
        ((), "messages", (AIMessageChunk(content="正文", additional_kwargs={"reasoning_content": "思考"}), {"langgraph_node": "model"})),
        ((), "messages", (AIMessageChunk(content="继续"), None)),
    ]
    assert list(iter_stream(iter(items))) == [
        ("reasoning", {"text": "思考", "agent_id": None}),
        ("token", "正文"),
        ("token", "继续"),
    ]


def test_spoofed_marker_token_mismatch_streams():
    """标记键存在但令牌不符（伪造形态）：与上游防伪同口径放行。"""
    items = [
        ((), "messages", (
            AIMessageChunk(content="正文"),
            {INTERNAL_CALL_METADATA_KEY: "not-the-real-token"},
        )),
    ]
    assert list(iter_stream(iter(items))) == [("token", "正文")]


def test_internal_call_marker_survives_real_graph_stream():
    """守卫（上游假设）：过滤修复真正押注的是「图节点内带 lc_internal_call
    标记的模型调用，其 chunk 会原样携带标记出现在 messages 流的 (chunk, meta)
    元组里」——langchain 的 InternalCallTransformer 只挂 v2 事件路径够不着
    v1 流，若 langgraph 升级改变 metadata 的合并/回传，泄漏会静默复发且上面
    手工构造 meta 的测试仍绿。本例走真实 langgraph：假流式模型 + mini 图，
    节点按 SummarizationMiddleware._create_summary 的同款 invoke 形状
    （config metadata 携 internal_call_metadata()）调模型——与安装版
    langchain.agents.middleware.summarization 逐字对齐。标记调用产出必须为
    空、无标记对照正常流出。"""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
    from langgraph.graph import END, START, MessagesState, StateGraph

    class _StreamingProbeModel(BaseChatModel):
        """模拟 streaming 档的真模型：invoke 内部走流式回调（总结漏出的路径）。"""

        @property
        def _llm_type(self) -> str:
            return "probe"

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            for txt in ("SESSION SUMMARY ", "PART2"):
                chunk = AIMessageChunk(content=txt)
                if run_manager:
                    run_manager.on_llm_new_token(txt, chunk=chunk)
                yield ChatGenerationChunk(message=chunk)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            final = None
            for gen in self._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                final = gen if final is None else final + gen
            assert final is not None
            return ChatResult(generations=[ChatGeneration(message=final.message)])

    model = _StreamingProbeModel()

    def build(marker: bool | None):
        def node(state):
            meta = (
                {"lc_source": "summarization", **internal_call_metadata()}
                if marker else {"langgraph_node": "model"}
            )
            return {"messages": [model.invoke(state["messages"], config={"metadata": meta})]}

        builder = StateGraph(MessagesState)
        builder.add_node("summarize", node)
        builder.add_edge(START, "summarize")
        builder.add_edge("summarize", END)
        return builder.compile()

    marked = build(marker=True).stream(
        {"messages": [("user", "hi")]}, stream_mode=["messages", "updates"]
    )
    assert list(iter_stream(marked)) == []  # 压缩总结不得当正文直播
    plain = build(marker=False).stream(
        {"messages": [("user", "hi")]}, stream_mode=["messages", "updates"]
    )
    assert list(iter_stream(plain)) == [("token", "SESSION SUMMARY "), ("token", "PART2")]


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


# ---------- HITL 伪节点代答 ToolMessage → tool.result（2026-09-12 ask_human 终态修复） ----------


def _hitl_answer_update(answered: ToolMessage) -> dict:
    """HumanInTheLoopMiddleware.after_model 在 resume 后下发的 update：
    [改写 tool_calls 后的原 AIMessage（历史重写）, 代答 ToolMessage]。"""
    ai_rewrite = AIMessage(
        content="",
        tool_calls=[{"name": "ask_human", "args": {"question": "选哪个？"}, "id": answered.tool_call_id, "type": "tool_call"}],
    )
    return {"messages": [ai_rewrite, answered]}


def test_hitl_pseudo_node_answer_translated_to_tool_result():
    """respond 裁决的代答 ToolMessage 翻译成 tool.result（tool_call_id 沿用原调用）；
    同批的 AIMessage 是历史重写，不得产出重复 tool.called。"""
    answered = ToolMessage(content="方案A", name="ask_human", tool_call_id="call_ask_1")
    stream = _node_updates("HumanInTheLoopMiddleware.after_model", [_hitl_answer_update(answered)])
    out = list(iter_stream(stream))
    assert [k for k, _ in out] == ["tool_result"]
    payload = out[0][1]
    assert payload["tool"] == "ask_human"
    assert payload["tool_call_id"] == "call_ask_1"
    assert "方案A" in payload["summary"]
    assert payload["error"] is None


def test_hitl_pseudo_node_reject_carries_error():
    """reject 裁决的代答 ToolMessage status=error → tool.result 带 error 字段（前端渲染失败态）。"""
    rejected = ToolMessage(
        content="User rejected the tool call for `ask_human`.",
        name="ask_human",
        tool_call_id="call_ask_2",
        status="error",
    )
    stream = _node_updates("HumanInTheLoopMiddleware.after_model", [_hitl_answer_update(rejected)])
    out = list(iter_stream(stream))
    assert [k for k, _ in out] == ["tool_result"]
    assert out[0][1]["error"] is not None
