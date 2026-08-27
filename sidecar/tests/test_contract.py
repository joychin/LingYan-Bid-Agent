"""§5.5 事件契约测试：每个流事件的 payload 必填字段与类型。

字段清单须与 frontend/src/api/sse.ts 的 AgentEventData 人工同步——前后端字段错位
（如已修的 agent.reasoning 文本键 text 被前端误读为 reasoning）从此在测试层挂掉。
agent.completed / agent.error / artifact.created 的 payload 构造在 run_stream 层
（含 seq 注入），由 e2e 冒烟（tests/test_smoke_e2e.py）覆盖；这里驱动
_run_agent_stream 覆盖六类流事件。注意 agent.error 自 2026-08-27 起 additive 带
code（cancelled=用户主动停止，恒有键、非取消为 null），run.state 的 error 分支
同款——同步时一并核对 sse.ts 的 AgentEventData。
"""

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.agent import _run_agent_stream

# 每事件的必填字段 + 允许的类型（tuple = 多选）。可选字段不在此列。
EVENT_SCHEMAS: dict[str, dict[str, tuple[type, ...]]] = {
    "agent.reasoning": {
        "run_id": (str,),
        "conversation_id": (str,),
        "text": (str,),
        "agent_id": (str, type(None)),
    },
    "agent.token": {
        "run_id": (str,),
        "conversation_id": (str,),
        "text": (str,),
    },
    "tool.called": {
        "run_id": (str,),
        "conversation_id": (str,),
        "tool": (str,),
        "args": (dict,),
        "tool_call_id": (str, type(None)),
        "agent_id": (str, type(None)),
    },
    "tool.result": {
        "run_id": (str,),
        "conversation_id": (str,),
        "tool": (str,),
        "summary": (str,),
        "error": (str, type(None)),
        "tool_call_id": (str, type(None)),
        "agent_id": (str, type(None)),
    },
    "todo.updated": {
        "run_id": (str,),
        "conversation_id": (str,),
        "done": (int,),
        "total": (int,),
        "items": (list,),
    },
}


class _StubAgent:
    def __init__(self, items):
        self._items = items

    def stream(self, *_args, **_kwargs):
        return iter(self._items)


def test_stream_event_payloads_match_contract():
    """六类流事件的 payload 字段名/类型逐一符合契约（含 additive 扩展）。"""
    chunk = AIMessageChunk(content="你好", additional_kwargs={"reasoning_content": "想想"})
    calls = AIMessage(
        content="",
        tool_calls=[{"name": "fetch_url", "args": {"url": "https://x"}, "id": "c1"}],
    )
    result = ToolMessage(content="页面内容", tool_call_id="c1", name="fetch_url")
    items = [
        ("messages", (chunk, {})),
        ("updates", {"model": {"messages": [calls]}}),
        ("updates", {"tools": {"messages": [result]}}),
        ("updates", {"model": {"todos": [{"content": "t", "status": "pending"}], "messages": []}}),
    ]
    published: list[tuple[str, dict]] = []
    _run_agent_stream(_StubAgent(items), "cid", "rid", None, lambda e, d: published.append((e, d)), "hi", None)

    seen = {e for e, _ in published}
    for event, schema in EVENT_SCHEMAS.items():
        assert event in seen, f"事件 {event} 未被产出（契约覆盖缺失）"
        for e, data in published:
            if e != event:
                continue
            for field, types in schema.items():
                assert field in data, f"{event} 缺字段 {field}（前后端契约错位）"
                assert isinstance(data[field], types), (
                    f"{event}.{field} 类型 {type(data[field]).__name__} 不在 {types}"
                )


def test_artifact_created_payload_matches_contract():
    """artifact.created 载荷（run 边界与转正端点共用 events.artifact_created_payload）。"""
    from app.events import artifact_created_payload

    row = {
        "artifact_id": "art_000000000001",
        "display_name": "投标目录",
        "kind": "tender.directory",
        "schema_id": "tender-response-docs",
        "schema_version": 1,
        # §16 真实形状：过程稿索引行也恒带所属 task_id（publish 经会话反查），
        # 以 conversation_id 区分两层（同 api/artifacts._to_api 口径）
        "task_id": "t_1",
        "conversation_id": "c_1",
        "promotion_proposed": 1,
    }
    data = artifact_created_payload(row, "r_1", "c_1", 7)
    assert data["scope"] == "conversation"
    assert data["task_id"] == "t_1"
    assert data["promotion_proposed"] is True
    assert data["seq"] == 7
    for field in ("run_id", "conversation_id", "artifact_id", "display_name", "kind", "schema_id", "schema_version"):
        assert field in data

    formal = {**row, "task_id": "t_1", "conversation_id": None, "promotion_proposed": 0}
    data2 = artifact_created_payload(formal, "r_1", "c_1", 8)
    assert data2["scope"] == "task"
    assert data2["task_id"] == "t_1"
    assert data2["promotion_proposed"] is False
