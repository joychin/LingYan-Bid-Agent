"""HITL（human-in-the-loop）全链路单测。

覆盖：events 捕获 __interrupt__ → run_stream 转 waiting_input（半截消息/trace/
快照/last_seq 落库 + run.interrupt 事件）→ resume 端点（状态校验/决策数校验/
respond 落 user message/续段 seq 续接）→ 旧库 runs 表 CHECK 迁移 →
重启恢复不翻 waiting_input。
"""

import asyncio
import json
import sqlite3
import time

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.types import Command, Interrupt

from app import agent as agent_mod
from app import db, events
from app.api import runs as runs_api
from app.config import app_db_path


def _make_interrupt(question: str = "用哪个方案？") -> Interrupt:
    """构造 HumanInTheLoopMiddleware 会发出的 HITLRequest 中断。"""
    return Interrupt(
        value={
            "action_requests": [
                {"name": "ask_human", "args": {"question": question}, "description": "确认方案"}
            ],
            "review_configs": [
                {"action_name": "ask_human", "allowed_decisions": ["respond"]}
            ],
        }
    )


# ---------- events.iter_stream：__interrupt__ 捕获 ----------


def test_iter_stream_parses_interrupt():
    it = _make_interrupt()
    stream = iter([("updates", {"__interrupt__": (it,)})])
    out = list(events.iter_stream(stream))
    assert out == [
        (
            "interrupt",
            {
                "requests": [
                    {
                        "tool": "ask_human",
                        "args": {"question": "用哪个方案？"},
                        "description": "确认方案",
                        "allowed": ["respond"],
                        # 多中断恢复的分组键（2026-09-06）：归一化逐条挂中断 id
                        "interrupt_id": getattr(it, "id", "") or "",
                    }
                ]
            },
        )
    ]


def test_iter_stream_interrupt_not_dropped_as_update():
    """__interrupt__ 的值是元组：不专门处理会掉进 update 解析被静默丢弃（回归防线）。"""
    stream = iter([("updates", {"__interrupt__": (_make_interrupt(),)})])
    kinds = [k for k, _ in events.iter_stream(stream)]
    assert "interrupt" in kinds and "tool_called" not in kinds


def _template_interrupt(name: str, args: dict) -> Interrupt:
    """langchain HITL 中间件的默认 description（英文模板 + 完整 args repr）。"""
    return Interrupt(
        value={
            "action_requests": [
                {
                    "name": name,
                    "args": args,
                    "description": f"Tool execution requires approval\nTool: {name}\nArgs: {args!r}",
                }
            ],
            "review_configs": [],
        }
    )


def test_hitl_template_description_rewritten_for_task():
    """task 派发审批卡的默认模板 description 重写为人话摘要（args 原样保留）。"""
    out = events._hitl_requests(
        (
            _template_interrupt(
                "task",
                {
                    "description": "为「商务标书」生成目录（R2 初稿 + 三道清理）。\n你是执行单元，请先阅读规则文件。",
                    "subagent_type": "tender-outline-writer",
                },
            ),
        )
    )
    [req] = out["requests"]
    assert req["description"] == "派出子代理（tender-outline-writer）：为「商务标书」生成目录（R2 初稿 + 三道清理）。"
    assert req["args"]["subagent_type"] == "tender-outline-writer"


def test_hitl_template_description_rewritten_for_generic_tool():
    out = events._hitl_requests((_template_interrupt("fetch_url", {"url": "https://x"}),))
    [req] = out["requests"]
    assert req["description"] == "执行工具 fetch_url，需要你的批准"


def test_hitl_custom_description_passthrough():
    """skill 自拟的中文 description（非模板前缀）原样透传，不受重写影响。"""
    out = events._hitl_requests((_make_interrupt(),))
    [req] = out["requests"]
    assert req["description"] == "确认方案"


def test_tool_args_html_entities_unescaped():
    """模型偶发把参数里的换行写成 &#10; 字面量 → 展示层 args 统一反转义。

    SSE tool.called、run.interrupt 问答卡、run_traces 快照三端共用 _tool_args，
    单点反转义全部生效；html.unescape 单遍解码保证 &amp;#10; 只解到 &#10;
    字面量、不会二次展开。
    """
    assert events._tool_args({"question": "确认开始？&#10;&#10;为什么问"}) == {
        "question": "确认开始？\n\n为什么问"
    }
    assert events._tool_args('{"question": "Q&#10;说明"}') == {"question": "Q\n说明"}
    assert events._tool_args({"nested": {"a": ["&amp;"]}}) == {"nested": {"a": ["&"]}}
    assert events._tool_args({"q": "&amp;#10;"}) == {"q": "&#10;"}

    msg = AIMessage(
        content="",
        tool_calls=[{"name": "ask_human", "args": {"question": "确认开始？&#10;&#10;为什么问"}, "id": "t9"}],
    )
    out = list(events.iter_stream(iter([("updates", {"model": {"messages": [msg]}})])))
    [called] = [d for k, d in out if k == "tool_called"]
    assert called["args"]["question"] == "确认开始？\n\n为什么问"

    out = list(
        events.iter_stream(iter([("updates", {"__interrupt__": (_make_interrupt("确认开始？&#10;&#10;为什么问"),)})]))
    )
    [interrupt] = [d for k, d in out if k == "interrupt"]
    assert interrupt["requests"][0]["args"]["question"] == "确认开始？\n\n为什么问"


def test_tool_args_literal_backslash_n_folded():
    """模型偶发把换行过度转义成字面反斜杠n 两个字符 → 展示层折叠为真实换行。

    2026-09-06 实测：ask_human question 里出现字面反斜杠n，问答卡原样上屏
    且首行/副标题分段失效。与 &#10; 修复同点（_deep_unescape），三端共用；
    已是真实换行的字符串不受影响，其余转义序列不折叠。
    """
    assert events._tool_args(
        {"question": "确认解析结果无误、开始提取投标要点？ \\n默认接下来会提取要点"}
    ) == {"question": "确认解析结果无误、开始提取投标要点？ \n默认接下来会提取要点"}
    assert events._tool_args({"q": "A&#10;B\\nC"}) == {"q": "A\nB\nC"}
    assert events._tool_args({"q": "第一行\n第二行"}) == {"q": "第一行\n第二行"}

    msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "ask_human", "args": {"question": "确认开始？\\n说明"}, "id": "t10"}
        ],
    )
    out = list(events.iter_stream(iter([("updates", {"model": {"messages": [msg]}})])))
    [called] = [d for k, d in out if k == "tool_called"]
    assert called["args"]["question"] == "确认开始？\n说明"


# ---------- run_stream：中断边界 ----------


class _StubAgent:
    def __init__(self, items):
        self._items = items
        self.inputs: list = []

    def stream(self, inp, config=None, stream_mode=None, subgraphs=None):
        self.inputs.append(inp)
        return iter(self._items)


def _drive_run_stream(monkeypatch, stub, cid, rid, **kwargs):
    """订阅 bus 队列跑一遍 run_stream，返回产出的事件 [(event, data)]。"""

    async def fake_get_agent(profile_id=None):
        return stub

    monkeypatch.setattr(agent_mod, "get_agent", fake_get_agent)

    from app import bus

    async def scenario():
        q = bus.subscribe(cid)
        await agent_mod.run_stream(cid, rid, **kwargs)
        out = []
        while not q.empty():
            e = q.get_nowait()
            out.append((e["event"], e["data"]))
        bus.unsubscribe(cid, q)
        return out

    return asyncio.run(scenario())


def _setup_conv(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("测试任务")
    conv = db.create_conversation(task["id"], "会话")
    run = db.create_run(conv["id"])
    return conv["id"], run["id"]


def test_run_stream_interrupt_transitions_to_waiting(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    gated = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {"description": "调研 OpenAI"}, "id": "t1"}],
    )
    items = [
        ("messages", (AIMessageChunk(content="我先确认一下"), {})),
        # task 被门禁拦下前 tool.called 已流出（模型节点先于 HITL 节点提交）→ running 步骤入树
        ("updates", {"model": {"messages": [gated]}}),
        ("updates", {"__interrupt__": (_make_interrupt(),)}),
    ]
    stub = _StubAgent(items)
    out = _drive_run_stream(monkeypatch, stub, cid, rid, user_text="hi")

    names = [e for e, _ in out]
    assert names[0] == "agent.started"
    assert "agent.token" in names
    assert "tool.called" in names
    assert names[-1] == "run.interrupt"
    data = out[-1][1]
    assert data["requests"][0]["tool"] == "ask_human"
    assert data["requests"][0]["allowed"] == ["respond"]
    assert isinstance(data["seq"], int) and data["seq"] >= 3

    # runs 行：waiting_input + 快照 + last_seq（= run.interrupt 事件的 seq）
    row = db.get_run(rid)
    assert row["status"] == "waiting_input"
    assert json.loads(row["interrupt"])[0]["tool"] == "ask_human"
    assert row["last_seq"] == data["seq"]

    # 半截回复落库（带等待标记）+ trace 落库；被拦下的 running 步骤改标 paused（不永远转圈）
    msgs = db.list_messages(cid)
    partial = [m for m in msgs if m["role"] == "assistant" and "等待你的输入" in m["content"]]
    assert partial
    trace = db.get_traces_for_messages([partial[0]["id"]])[partial[0]["id"]]
    assert trace["tools"][0]["tool"] == "task"
    assert trace["tools"][0]["status"] == "paused"
    assert trace["tools"][0]["endedAt"] is not None


def test_run_stream_resume_segment_continues_seq(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    db.interrupt_run(rid, [{"tool": "ask_human", "args": {}, "allowed": ["respond"]}], last_seq=3)

    items = [("messages", (AIMessageChunk(content="好的，继续"), {}))]
    stub = _StubAgent(items)
    out = _drive_run_stream(monkeypatch, stub, cid, rid, resume_decisions=[{"type": "respond", "message": "方案A"}], start_seq=3)

    # 续段事件序号从 last_seq+1 接上（前端按 run_id 去重，重置会吞掉续段事件）
    assert out[0][0] == "agent.started" and out[0][1]["seq"] == 4
    assert out[-1][0] == "agent.completed"
    # 输入是 Command(resume=...)，不是新 user 消息
    assert isinstance(stub.inputs[0], Command)
    assert stub.inputs[0].resume == {"decisions": [{"type": "respond", "message": "方案A"}]}
    # 续段正常完成：run 转 completed
    assert db.get_run(rid)["status"] == "completed"


# ---------- 暂停→续跑：run_id 关联 / 旁白去重 / trace 合并 / last_seq 回写 ----------


def _segment_one_items() -> list:
    """首段：已完成步骤 c0 → 旁白 → 被门禁拦下的 t1 → 中断。"""
    return [
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "ls", "args": {}, "id": "c0"}])]}}),
        ("updates", {"tools": {"messages": [ToolMessage(content="[]", name="ls", tool_call_id="c0")]}}),
        ("messages", (AIMessageChunk(content="我先确认一下"), {})),
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "task", "args": {"description": "调研"}, "id": "t1"}])]}}),
        ("updates", {"__interrupt__": (_make_interrupt(),)}),
    ]


def test_pause_message_run_id_and_narration_dedup(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    out = _drive_run_stream(monkeypatch, _StubAgent(_segment_one_items()), cid, rid, user_text="hi")
    assert out[-1][0] == "run.interrupt"

    # 半截消息带 run_id（前端按 run 聚合同一回合的段落）；正文 = 兜底旁白 + 等待标记
    msgs = db.list_messages(cid)
    pause = [m for m in msgs if m["role"] == "assistant"][0]
    assert pause["run_id"] == rid
    assert pause["content"].startswith("我先确认一下")
    assert pause["content"].endswith("（等待你的输入…）")

    # 旁白去重：同一段话不再既当消息正文又在 trace 旁白行重复（t1 步骤 text 已清空）
    trace = db.get_traces_for_messages([pause["id"]])[pause["id"]]
    by_id = {s["id"]: s for s in trace["tools"]}
    assert by_id["c0"]["status"] == "done"
    assert by_id["t1"]["status"] == "paused"
    assert by_id["t1"]["text"] == ""


def test_resume_completion_merges_trace_and_writes_last_seq(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    _drive_run_stream(monkeypatch, _StubAgent(_segment_one_items()), cid, rid, user_text="hi")
    pause = [m for m in db.list_messages(cid) if m["role"] == "assistant"][0]

    # 续段：同 id t1 重发并执行完成 + 新增量步骤 c2 + 最终回复
    items = [
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "task", "args": {"description": "调研"}, "id": "t1"}])]}}),
        ("updates", {"tools": {"messages": [ToolMessage(content="完成", name="task", tool_call_id="t1")]}}),
        ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{"name": "write_file", "args": {}, "id": "c2"}])]}}),
        ("updates", {"tools": {"messages": [ToolMessage(content="ok", name="write_file", tool_call_id="c2")]}}),
        ("messages", (AIMessageChunk(content="检索完成"), {})),
    ]
    out = _drive_run_stream(monkeypatch, _StubAgent(items), cid, rid, resume_decisions=[{"type": "approve"}], start_seq=db.get_run(rid)["last_seq"])
    assert out[-1][0] == "agent.completed"

    # 最终消息带 run_id；trace 合并挂到最终消息（一棵全程树，无重复 id、顺序旧段在前）
    final = [m for m in db.list_messages(cid) if m["role"] == "assistant"][-1]
    assert final["run_id"] == rid
    assert final["content"] == "检索完成"
    trace = db.get_traces_for_messages([final["id"]])[final["id"]]
    assert [s["id"] for s in trace["tools"]] == ["c0", "t1", "c2"]
    assert {s["id"]: s["status"] for s in trace["tools"]}["t1"] == "done"

    # finish_run 回写终态 seq（此前 last_seq 永远停在暂停值）
    assert db.get_run(rid)["last_seq"] == out[-1][1]["seq"]
    # 暂停消息仍在，与最终消息同属一个 run（前端单回合聚合依据）
    assert pause["run_id"] == final["run_id"] == rid


def test_resume_error_without_output_keeps_pause_trace(tmp_path, monkeypatch):
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    _drive_run_stream(monkeypatch, _StubAgent(_segment_one_items()), cid, rid, user_text="hi")
    pause = [m for m in db.list_messages(cid) if m["role"] == "assistant"][0]

    class _BoomAgent:
        def stream(self, *args, **kwargs):
            raise RuntimeError("boom")

    out = _drive_run_stream(monkeypatch, _BoomAgent(), cid, rid, resume_decisions=[{"type": "approve"}], start_seq=db.get_run(rid)["last_seq"])
    assert out[-1][0] == "agent.error"

    # 无产出终止：暂停标记改写为「任务中断」；trace 不丢——message_id 保留暂停消息挂载
    pause_after = [m for m in db.list_messages(cid) if m["id"] == pause["id"]][0]
    assert pause_after["content"].endswith("（任务中断）")
    trace = db.get_traces_for_messages([pause["id"]])[pause["id"]]
    assert [s["id"] for s in trace["tools"]] == ["c0", "t1"]
    assert db.get_run(rid)["status"] == "error"
    assert db.get_run(rid)["last_seq"] == out[-1][1]["seq"]


# ---------- db：迁移与恢复 ----------


def test_runs_table_migration_from_old_check(tmp_path, monkeypatch):
    """旧库（CHECK 无 waiting_input、无新列）→ init_db 整表迁移，数据保留。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    p = app_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE runs(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,"
        " status TEXT NOT NULL CHECK(status IN ('running','completed','error')),"
        " error TEXT, created_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO runs VALUES('r_old','c_1','completed',NULL,'2026-01-01T00:00:00')")
    conn.commit()
    conn.close()

    db.init_db()
    row = db.get_run("r_old")
    assert row is not None and row["status"] == "completed"  # 数据原样带过
    db.interrupt_run("r_old", [{"tool": "ask_human", "args": {}}], 5)  # 新 CHECK 可写
    assert db.get_run("r_old")["status"] == "waiting_input"
    assert db.get_run("r_old")["last_seq"] == 5


def test_recover_stale_runs_keeps_waiting_input(tmp_path, monkeypatch):
    """重启恢复只翻 running；waiting_input 的 interrupt 活在 checkpoint，仍可续跑。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    r_waiting = db.create_run(conv["id"])
    db.interrupt_run(r_waiting["id"], [], 0)
    r_running = db.create_run(conv["id"])

    assert db.recover_stale_runs() == 1
    assert db.get_run(r_running["id"])["status"] == "error"
    assert db.get_run(r_waiting["id"])["status"] == "waiting_input"


def test_active_run_exists_covers_waiting_input(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    run = db.create_run(conv["id"])
    db.interrupt_run(run["id"], [], 0)
    assert db.active_run_exists(conv["id"]) is True
    db.resume_run(run["id"])
    assert db.active_run_exists(conv["id"]) is True
    db.finish_run(run["id"], "completed")
    assert db.active_run_exists(conv["id"]) is False


def test_resume_run_conditional_claim(tmp_path, monkeypatch):
    """resume_run 条件抢占：仅 waiting_input 可转 running，重复调用返回 False
    （幂等抢占点——并发重复 resume 只有一个能成功）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    run = db.create_run(conv["id"])
    assert db.resume_run(run["id"]) is False  # running 状态不可 resume
    db.interrupt_run(run["id"], [], 0)
    assert db.resume_run(run["id"]) is True
    assert db.resume_run(run["id"]) is False  # 已是 running，二次抢占失败


def test_run_stream_outer_exception_saves_partial_output(tmp_path, monkeypatch):
    """外层异常兜底：worker 已流出的正文与 trace 落库（此前只标 error，已流出
    内容全失），终态事件仍发出。"""
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    items = [("messages", (AIMessageChunk(content="已流出的结论正文"), {}))]
    stub = _StubAgent(items)

    def boom(*a, **kw):
        raise RuntimeError("发布阶段崩溃")

    monkeypatch.setattr(agent_mod.db, "pending_emit", boom)
    out = _drive_run_stream(monkeypatch, stub, cid, rid, user_text="hi")

    assert out[-1][0] == "agent.error"
    row = db.get_run(rid)
    assert row["status"] == "error"
    # 已流出的正文落库（带中断标记），不是全失；trace 一并落库
    msgs = db.list_messages(cid)
    partial = [m for m in msgs if m["role"] == "assistant" and "已流出的结论正文" in m["content"]]
    assert partial and partial[0]["content"].endswith("（任务中断）")
    assert db.get_run_trace(rid) is not None


def test_run_stream_saved_segment_not_duplicated_on_late_failure(tmp_path, monkeypatch):
    """completed 分支落库后晚到的异常（trace 落库失败）：兜底不重写消息
    （segment_saved 防双写），run 标 error 并发 error 事件。"""
    cid, rid = _setup_conv(tmp_path, monkeypatch)
    items = [("messages", (AIMessageChunk(content="最终回复"), {}))]
    stub = _StubAgent(items)

    def flaky_save(*a, **kw):
        raise RuntimeError("落库后崩溃")

    monkeypatch.setattr(agent_mod, "_save_merged_trace", flaky_save)
    out = _drive_run_stream(monkeypatch, stub, cid, rid, user_text="hi")

    assert out[-1][0] == "agent.error"
    msgs = db.list_messages(cid)
    finals = [m for m in msgs if m["role"] == "assistant" and "最终回复" in m["content"]]
    assert len(finals) == 1  # 不双写
    assert db.get_run(rid)["status"] == "error"


# ---------- resume 端点 ----------


def _waiting_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    db.init_db()
    task = db.create_task("t")
    conv = db.create_conversation(task["id"])
    run = db.create_run(conv["id"])
    db.interrupt_run(run["id"], [{"tool": "ask_human", "args": {"question": "Q"}, "allowed": ["respond"]}], 3)
    return conv["id"], run["id"]


def _wait_captured(captured, key):
    for _ in range(200):
        if key in captured:
            return
        time.sleep(0.01)


def test_resume_endpoint_flow(client, tmp_path, monkeypatch):
    cid, rid = _waiting_setup(tmp_path, monkeypatch)
    captured: dict = {}

    async def fake_run_stream(cid_, rid_, user_text=None, resume_decisions=None, start_seq=0, thinking="low", model=None, resume_payload=None):
        captured.update(cid=cid_, rid=rid_, resume_decisions=resume_decisions, start_seq=start_seq, resume_payload=resume_payload)

    monkeypatch.setattr(runs_api, "run_stream", fake_run_stream)

    # 404：不存在的 run
    assert client.post("/api/runs/r_none/resume", json={"decisions": [{"type": "approve"}]}).status_code == 404
    # 422：决策数与待确认动作数不一致（快照 1 个，传 2 个）
    resp = client.post(
        f"/api/runs/{rid}/resume",
        json={"decisions": [{"type": "respond", "message": "a"}, {"type": "approve"}]},
    )
    assert resp.status_code == 422
    # 202：respond 决策 → 落 user message、run 转 running、快照清空、续段参数透传
    resp = client.post(
        f"/api/runs/{rid}/resume", json={"decisions": [{"type": "respond", "message": "方案A"}]}
    )
    assert resp.status_code == 202
    _wait_captured(captured, "resume_decisions")
    assert captured["rid"] == rid
    assert captured["resume_decisions"] == [{"type": "respond", "message": "方案A"}]
    assert captured["start_seq"] == 3  # 接 waiting 时的 last_seq
    assert db.get_run(rid)["status"] == "running"
    assert db.get_run(rid)["interrupt"] is None
    assert any(m["role"] == "user" and m["content"] == "方案A" for m in db.list_messages(cid))
    # 409：已转 running，再 resume 拒绝
    assert client.post(f"/api/runs/{rid}/resume", json={"decisions": [{"type": "approve"}]}).status_code == 409


def test_message_post_409_while_waiting(client, tmp_path, monkeypatch):
    cid, rid = _waiting_setup(tmp_path, monkeypatch)
    resp = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    assert resp.status_code == 409
    assert "等待" in resp.json()["detail"]


def test_latest_run_returns_requests_snapshot(client, tmp_path, monkeypatch):
    cid, rid = _waiting_setup(tmp_path, monkeypatch)
    resp = client.get(f"/api/conversations/{cid}/runs/latest").json()["run"]
    assert resp["status"] == "waiting_input"
    assert resp["requests"][0]["tool"] == "ask_human"
