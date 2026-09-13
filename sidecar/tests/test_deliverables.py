"""交付物呈现信号（deliverable.created，契约 additive 2026-09-13）。

覆盖：收集队列机械（note/drain/clear、无 run 跳过）、载荷与 pydantic 契约
互证、与发布短路的语义对齐（没新东西不打扰）、run 正常完成时的终态呈现
（二批改定：run 进行中不发现，completed 分支取最新声明发一次；error/中断
段丢弃；finally 清桶）。
"""

import asyncio

import pytest
from langchain_core.messages import AIMessageChunk

from app import deliverables, events, runctx
from app import publish as publish_mod
from app.contracts.events import EVENT_PAYLOAD_MODELS
from tests.util import init_env

KEY = "tender.directory/tender-response-docs@1"


@pytest.fixture(autouse=True)
def _clean_queue():
    yield
    for rid in list(deliverables._QUEUE):
        deliverables.clear(rid)
    runctx.clear_run()


def test_note_without_run_is_skipped():
    """无 run 上下文（脚本直调工具/单测直调）静默跳过——没有 seq 宿主就没有事件。"""
    runctx.clear_run()
    deliverables.note("file", path="body/整本-x.docx", display_name="整本-x.docx")
    assert deliverables.drain("r_any") == []


def test_note_drain_fifo_and_clear():
    """FIFO、破坏性读、clear 后桶空。"""
    runctx.set_run("c1", "r1")
    try:
        deliverables.note("artifact", artifact_id="a1", display_name="投标目录")
        deliverables.note("file", path="body/整本-x.docx", display_name="整本-x.docx")
        items = deliverables.drain("r1")
        assert [i["kind"] for i in items] == ["artifact", "file"]
        assert deliverables.drain("r1") == []
        deliverables.note("file", path="p")
        deliverables.clear("r1")
        assert deliverables.drain("r1") == []
    finally:
        runctx.clear_run()


def test_deliverable_payload_matches_contract():
    """载荷构造与契约模型互证（test_contract 同款纪律，两种 kind 各一例）。"""
    model = EVENT_PAYLOAD_MODELS["deliverable.created"]
    model.model_validate(
        events.deliverable_created_payload(
            {"kind": "artifact", "artifact_id": "a1", "display_name": "投标目录"}, "r1", "c1", 3
        )
    )
    model.model_validate(
        events.deliverable_created_payload(
            {"kind": "file", "path": "body/整本-x.docx", "display_name": "整本-x.docx"}, "r1", "c1", 4
        )
    )


def test_publish_notes_deliverable_except_shortcircuit(tmp_path, monkeypatch):
    """呈现信号与发布语义对齐：新建/内容有变 → note artifact；内容未变短路 → 不 note
    （与 artifact.created 同款「没新东西不打扰」语义）。"""
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_pub")
    try:
        def _content(name="技术部分"):
            return {
                "response_documents": [
                    {"name": name, "scope": "", "directory": [{"目录名称": "目录", "level": 1, "children": []}]}
                ]
            }

        kw = {"task_id": task["id"], "conversation_id": conv["id"]}
        m1 = publish_mod.publish_artifact(KEY, _content(), **kw)
        items = deliverables.drain("r_pub")
        assert len(items) == 1 and items[0]["kind"] == "artifact"
        assert items[0]["artifact_id"] == m1["artifact_id"]
        assert items[0]["display_name"] == "投标目录"

        # 同内容同名的短路轮：无呈现信号
        publish_mod.publish_artifact(KEY, _content(), **kw)
        assert deliverables.drain("r_pub") == []

        # 内容变化：照常声明
        publish_mod.publish_artifact(KEY, _content("改版"), **kw)
        assert len(deliverables.drain("r_pub")) == 1
    finally:
        runctx.clear_run()
        deliverables.clear("r_pub")


def test_run_stream_presents_latest_deliverable_at_completion(tmp_path, monkeypatch):
    """run 正常完成时呈现本轮声明的**最后一个**交付物（2026-09-13 二批改定：
    首版「产出即开」调整为 run 结束才开）——run 进行中不发现事件（用户看过程
    卡不被打断），completed 分支在终态事件前发一次、取最新声明；finally 清桶。
    声明在假 agent 的流生成器里发——它运行在 worker 线程内，与真实工具线程
    同样能读到 runctx（contextvars 父→子传播）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import agent as agent_mod
    from app import db

    db.init_db()
    tid = db.create_task("任务")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]

    published: list[tuple[str, dict]] = []

    async def _fake_publish(_cid: str, evt: dict) -> None:
        published.append((evt["event"], evt["data"]))

    def _stream(*_args, **_kwargs):
        deliverables.note("artifact", artifact_id="a1", display_name="投标目录")
        yield ("messages", AIMessageChunk(content="正文"))
        # 后声明的整本=最新交付物（先目录后整本的典型 run 形态）
        deliverables.note("artifact", artifact_id="a2", display_name="技术部分")

    class _Agent:
        stream = staticmethod(_stream)

    async def _fake_get_agent(*_a, **_k):
        return _Agent()

    monkeypatch.setattr(agent_mod, "get_agent", _fake_get_agent)
    monkeypatch.setattr(agent_mod, "publish", _fake_publish)
    asyncio.run(agent_mod.run_stream(cid, rid, user_text="hi"))

    assert db.get_run(rid)["status"] == "completed"
    names = [e for e, _d in published]
    # 只发一次、且是最新声明（不是逐个连发——毫秒内连环换页无意义）
    assert names.count("deliverable.created") == 1
    d = next(d for e, d in published if e == "deliverable.created")
    assert d["artifact_id"] == "a2"
    # run 进行中不发现（所有 deliverable 事件都在终态 agent.completed 紧前）
    assert names.index("deliverable.created") == names.index("agent.completed") - 1
    # 全流 seq 严格单调（与普通事件同一计数器）
    seqs = [d["seq"] for _e, d in published if "seq" in d]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # run 结束清桶：不留残留
    assert deliverables.drain(rid) == []
    assert rid not in deliverables._QUEUE


def test_run_stream_error_and_interrupt_drop_deliverables(tmp_path, monkeypatch):
    """error（含取消）与 interrupt（等待输入）段不呈现交付物：那时该看错误卡/
    提问卡；随段丢弃（finally 清桶），续跑完成由续跑段的新声明兜底。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import agent as agent_mod
    from app import db

    db.init_db()
    tid = db.create_task("任务")["id"]
    cid = db.create_conversation(tid, "会话")["id"]

    published: list[tuple[str, dict]] = []

    async def _fake_publish(_cid: str, evt: dict) -> None:
        published.append((evt["event"], evt["data"]))

    def _err_stream(*_args, **_kwargs):
        deliverables.note("artifact", artifact_id="a1", display_name="投标目录")
        yield ("messages", AIMessageChunk(content="写到一半"))
        raise RuntimeError("boom")

    async def _fake_get_agent(*_a, **_k):
        class _Agent:
            stream = staticmethod(_err_stream)

        return _Agent()

    monkeypatch.setattr(agent_mod, "get_agent", _fake_get_agent)
    monkeypatch.setattr(agent_mod, "publish", _fake_publish)

    rid = db.create_run(cid)["id"]
    asyncio.run(agent_mod.run_stream(cid, rid, user_text="hi"))
    assert db.get_run(rid)["status"] == "error"
    assert [e for e, _d in published].count("deliverable.created") == 0
    assert deliverables.drain(rid) == []  # error 段丢弃且清桶
