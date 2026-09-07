"""多中断恢复（2026-09-06 修复）：同一轮多个 ask_human 各产生一个 pending
Interrupt——归一化须合并全部并挂 interrupt_id；resume 按 id 分组映射恢复
（langgraph 对多 pending 的硬要求，此前只取第一个导致第二个悬空报错）。"""

from types import SimpleNamespace

from app.api.runs import _resume_map
from app.events import _hitl_requests


def _interrupt(iid: str, questions: list[str]):
    return SimpleNamespace(
        id=iid,
        value={
            "review_configs": [{"action_name": "ask_human", "allowed_decisions": ["respond"]}],
            "action_requests": [
                {"name": "ask_human", "args": {"question": q}, "description": ""}
                for q in questions
            ],
        },
    )


def test_two_interrupts_merged_with_ids():
    r = _hitl_requests(
        (_interrupt("id_aaa", ["指引已生成，确认？"]), _interrupt("id_bbb", ["工期承诺多少天？"]))
    )["requests"]
    assert len(r) == 2
    assert r[0]["args"]["question"].startswith("指引已生成")
    assert r[0]["interrupt_id"] == "id_aaa"
    assert r[1]["interrupt_id"] == "id_bbb"
    assert r[1]["allowed"] == ["respond"]


def test_single_interrupt_batch_multiple_actions():
    """单个 Interrupt 的 batch 模式（一个 HITLRequest 多个 action）仍合并，id 一致。"""
    r = _hitl_requests(_interrupt("id_solo", ["问一", "问二"]))["requests"]
    assert len(r) == 2
    assert all(x["interrupt_id"] == "id_solo" for x in r)


def test_resume_map_groups_by_interrupt_id():
    requests = [
        {"tool": "ask_human", "interrupt_id": "id_a"},
        {"tool": "ask_human", "interrupt_id": "id_b"},
        {"tool": "ask_human", "interrupt_id": "id_a"},
    ]
    decisions = [{"type": "respond", "message": "1"}, {"type": "respond", "message": "2"}, {"type": "respond", "message": "3"}]
    m = _resume_map(requests, decisions)
    assert m == {
        "id_a": {"decisions": [{"type": "respond", "message": "1"}, {"type": "respond", "message": "3"}]},
        "id_b": {"decisions": [{"type": "respond", "message": "2"}]},
    }


def test_resume_map_legacy_snapshot_without_ids():
    """旧快照（无 interrupt_id）返回 None，走单中断兼容的旧格式。"""
    requests = [{"tool": "ask_human"}]
    assert _resume_map(requests, [{"type": "respond", "message": "x"}]) is None
    assert _resume_map([], []) is None
    # 混合（部分有 id）也走旧格式——不完整映射比没有更糟
    mixed = [{"tool": "ask_human", "interrupt_id": "id_a"}, {"tool": "ask_human"}]
    assert _resume_map(mixed, [{"type": "respond", "message": "1"}, {"type": "respond", "message": "2"}]) is None
