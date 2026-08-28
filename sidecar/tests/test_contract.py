"""§5.5 事件契约测试：真实发布的 payload 逐一过 contracts.events 的 pydantic 模型。

契约单一事实源 = app/contracts/events.py（本文件校验真实数据 ↔ 模型；
scripts/gen_ts_types.py 用同一批模型生成前端 events.gen.ts——前后端字段对齐从
「注释纪律」变成「模型断言 + 生成」）。事件名常量真值在 app/events.py（适配层），
注册表键集与常量集的对齐也在本文件断言（改一边不改另一边即红）。
六类流事件由 _StubAgent 驱动 _run_agent_stream 产出；run 边界事件（completed/error/
run.state）由 e2e 冒烟（tests/test_smoke_e2e.py）覆盖，payload 构造函数
（events.*_payload）在此直接校验。
"""

from pathlib import Path

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app import events as events_module
from app.agent import _run_agent_stream
from app.contracts.events import EVENT_PAYLOAD_MODELS, ArtifactCreated


def test_generated_ts_files_cover_all_models():
    """events.gen.ts / dto.gen.ts 覆盖全部契约模型（漏重新生成在此挂掉；
    check.sh 的重生成 + git diff --exit-code 是完整防线）。"""
    root = Path(__file__).resolve().parents[2]
    events_gen = (root / "frontend/src/api/events.gen.ts").read_text(encoding="utf-8")
    for model in EVENT_PAYLOAD_MODELS.values():
        assert f"interface {model.__name__}" in events_gen, f"events.gen.ts 缺 {model.__name__}（重新生成）"

    from app.contracts import dto as dto_module

    dto_gen = (root / "frontend/src/api/dto.gen.ts").read_text(encoding="utf-8")
    for name in ("Task", "Conversation", "Message", "RunInfo", "Artifact", "ArtifactContract", "KbItem", "KbParseMeta", "Settings"):
        assert f"interface {name}" in dto_gen, f"dto.gen.ts 缺 {name}（重新生成）"
        assert hasattr(dto_module, name)


def test_event_registry_matches_events_module_constants():
    """contracts 注册表 ↔ events.py 事件名常量键集一致（单一事实源与适配层对齐）。"""
    constants = {
        v for k, v in vars(events_module).items() if k.startswith("EVENT_") and isinstance(v, str)
    }
    assert set(EVENT_PAYLOAD_MODELS) == constants, (
        "contracts/events.py 与 app/events.py 的事件清单不一致（改一边忘了另一边）"
    )


class _StubAgent:
    def __init__(self, items):
        self._items = items

    def stream(self, *_args, **_kwargs):
        return iter(self._items)


def test_stream_event_payloads_match_contract():
    """六类流事件的 payload 逐一通过契约模型（字段名/类型/必填，含 additive 扩展）。

    _run_agent_stream 直发的 payload 不带 seq（由 run_stream 的 _publish 外层注入，
    见 agent.py：payload = {**data, "seq": next_seq()}）——这里同样注入后校验。"""
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
    counter = iter(range(1, 100))

    def capture(e: str, d: dict) -> None:
        published.append((e, {**d, "seq": next(counter)}))

    _run_agent_stream(_StubAgent(items), "cid", "rid", None, capture, "hi", None)

    seen = {e for e, _ in published}
    for expected in ("agent.reasoning", "agent.token", "tool.called", "tool.result", "todo.updated"):
        assert expected in seen, f"事件 {expected} 未被产出（契约覆盖缺失）"
    for e, data in published:
        model = EVENT_PAYLOAD_MODELS.get(e)
        if model is not None:
            model.model_validate(data)  # 字段错位/缺必填在此抛 ValidationError


def test_run_boundary_payload_builders_match_contract():
    """run 边界事件构造函数（agent.py/titler 调用）过契约模型；code 恒有键。"""
    EVENT_PAYLOAD_MODELS["agent.started"].model_validate(
        events_module.started_payload("r", "c", 1)
    )
    EVENT_PAYLOAD_MODELS["agent.completed"].model_validate(
        events_module.completed_payload("r", "c", "m", 2)
    )
    err = events_module.error_payload("r", "c", "boom", None, 3)
    EVENT_PAYLOAD_MODELS["agent.error"].model_validate(err)
    assert "code" in err  # 契约要求恒有键（此前 run_stream 外层 except 漏发过）
    evt = events_module.interrupt_payload("r", "c", [], 4)
    EVENT_PAYLOAD_MODELS["run.interrupt"].model_validate(evt)


def test_artifact_created_payload_matches_contract():
    """artifact.created 载荷（run 边界与转正端点共用 events.artifact_created_payload）。"""
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
    data = events_module.artifact_created_payload(row, "r_1", "c_1", 7)
    ArtifactCreated.model_validate(data)
    assert data["scope"] == "conversation"
    assert data["task_id"] == "t_1"
    assert data["promotion_proposed"] is True

    formal = {**row, "task_id": "t_1", "conversation_id": None, "promotion_proposed": 0}
    data2 = events_module.artifact_created_payload(formal, "r_1", "c_1", 8)
    ArtifactCreated.model_validate(data2)
    assert data2["scope"] == "task"
    assert data2["promotion_proposed"] is False
