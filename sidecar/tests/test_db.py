"""db：崩溃残留 running run 的恢复 + 每会话单 run 守卫 + 任务层级联。"""

import pytest

from app import db
from tests.util import create_conversation


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    return tmp_path


def test_recover_stale_runs(db_env):
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    db.create_run(cid)
    assert db.active_run_exists(cid) is True
    recovered = db.recover_stale_runs()
    assert recovered == 1
    assert db.active_run_exists(cid) is False


def test_finish_run_if_running_terminal_guard(db_env):
    """终态守卫版收尾：仅 running 可写，已终态的 runs 不被覆盖——
    agent 外层异常兜底不得顶掉 worker 已落的原始错误文案、不得翻转 completed。"""
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    run = db.create_run(cid)
    assert db.finish_run_if_running(run["id"], "error", "原始错误", last_seq=9) is True
    # 已是 error：二次兜底不再覆盖（原始文案与 last_seq 保住）
    assert db.finish_run_if_running(run["id"], "error", "内部异常文案", last_seq=10) is False
    row = db.get_run(run["id"])
    assert row["status"] == "error" and row["error"] == "原始错误" and row["last_seq"] == 9
    # completed 不被翻成 error
    run2 = db.create_run(cid)
    db.finish_run(run2["id"], "completed", last_seq=5)
    assert db.finish_run_if_running(run2["id"], "error", "boom") is False
    assert db.get_run(run2["id"])["status"] == "completed"


def test_retire_pause_marker(db_env):
    """暂停消息在 run 终止后的标记改写：末尾精确匹配「（等待你的输入…）」→
    「（任务中断）」；已改写/空 id/不匹配后缀的消息不动。"""
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]
    msg = db.append_assistant_message(cid, "骨架已落盘。\n\n（等待你的输入…）")
    db.interrupt_run(rid, [], 3, pause_msg_id=msg["id"])
    assert db.get_run(rid)["pause_msg_id"] == msg["id"]

    assert db.retire_pause_marker(msg["id"]) is True
    assert [m["content"] for m in db.list_messages(cid)] == ["骨架已落盘。\n\n（任务中断）"]

    # 幂等：后缀已不存在时不重复处理
    assert db.retire_pause_marker(msg["id"]) is False
    assert db.retire_pause_marker(None) is False


def test_recover_only_marks_running(db_env):
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    rid = db.create_run(cid)["id"]
    db.finish_run(rid, "completed")
    assert db.recover_stale_runs() == 0


def test_finished_run_no_longer_blocks(client):
    cid = create_conversation(client)["id"]
    rid = db.create_run(cid)["id"]
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).status_code == 409
    db.finish_run(rid, "completed")
    r2 = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    assert r2.status_code == 202
    assert "run_id" in r2.json()


def test_rename_conversation_endpoint(client):
    cid = create_conversation(client, title="old")["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"title": "新标题"}).json()["title"] == "新标题"
    # 空标题 422
    assert client.patch(f"/api/conversations/{cid}", json={"title": "  "}).status_code == 422
    # 不存在 404
    assert client.patch("/api/conversations/c_nope", json={"title": "x"}).status_code == 404


def test_set_title_if_default(db_env):
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid)["id"]  # 默认「新对话」
    assert db.set_title_if_default(cid, "自动标题") is True
    assert db.get_conversation(cid)["title"] == "自动标题"
    # 已写入后不再覆盖
    assert db.set_title_if_default(cid, "第二次") is False
    assert db.get_conversation(cid)["title"] == "自动标题"


def test_run_trace_reasoning_roundtrip(db_env):
    """run_traces.reasoning：主 agent 思考流落库/回读（历史「深度思考」数据源）。"""
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    msg = db.append_assistant_message(cid, "回复正文")
    db.save_run_trace("r1", cid, msg["id"], [], [], 1200, reasoning="先想一步再想一步")
    traces = db.get_traces_for_messages([msg["id"]])
    assert traces[msg["id"]]["reasoning"] == "先想一步再想一步"
    # 未传 reasoning 的旧调用路径（默认值）落空串，回读不抛
    db.save_run_trace("r2", cid, None, [], [])
    assert db.get_traces_for_messages([msg["id"]])[msg["id"]]["reasoning"] == "先想一步再想一步"


def test_run_traces_reasoning_column_migration(tmp_path, monkeypatch):
    """老库（reasoning 列不存在）经编号迁移补列，旧数据回读 reasoning=''。

    user_version 语义注意：版本化后 init_db 以版本号为权威——已盖版本号的库手动降表
    不会自动修复；旧库迁移只在 user_version==0（无版本号的存量库）时触发。"""
    import sqlite3

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import app_db_path

    app_db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(app_db_path()))
    # 直接造「没有 reasoning 列」的旧库（user_version=0）
    conn.execute(
        "CREATE TABLE run_traces(run_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,"
        " message_id TEXT, tools TEXT NOT NULL, todos TEXT NOT NULL, duration_ms INTEGER,"
        " created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO run_traces(run_id, conversation_id, message_id, tools, todos, duration_ms, created_at)"
        " VALUES ('r_old','c_old',NULL,'[]','[]',100,'2026-01-01')"
    )
    conn.commit()
    conn.close()
    db.init_db()  # 启动迁移：补 reasoning 列
    rows = db.get_traces_for_messages([])  # 不炸即过
    assert rows == {}
    conn = sqlite3.connect(str(app_db_path()))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(run_traces)").fetchall()}
    old = conn.execute("SELECT reasoning FROM run_traces WHERE run_id='r_old'").fetchone()
    conn.close()
    assert "reasoning" in cols
    assert old == ("",)


def test_set_title_if_default_respects_manual_rename(db_env):
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid)["id"]
    db.rename_conversation(cid, "用户手动改的")
    assert db.set_title_if_default(cid, "自动标题") is False
    assert db.get_conversation(cid)["title"] == "用户手动改的"


def test_delete_conversation_cascades(client):
    cid = create_conversation(client)["id"]
    db.create_user_message(cid, "hi")
    rid = db.create_run(cid)["id"]
    db.finish_run(rid, "completed")  # running 会话不可删（409），先完成再删
    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}/messages").status_code == 404
    # 不存在的会话 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 404


def test_get_latest_run(db_env):
    tid = db.create_task("t")["id"]
    cid = db.create_conversation(tid, "会话")["id"]
    assert db.get_latest_run(cid) is None

    r1 = db.create_run(cid)
    db.finish_run(r1["id"], "completed")
    r2 = db.create_run(cid)  # 同秒内两条 run，靠 rowid 分先后
    latest = db.get_latest_run(cid)
    assert latest["id"] == r2["id"]
    assert latest["status"] == "running"

    db.finish_run(r2["id"], "error", "boom")
    latest = db.get_latest_run(cid)
    assert latest["status"] == "error"
    assert latest["error"] == "boom"


def test_latest_run_endpoint(client):
    cid = create_conversation(client)["id"]
    assert client.get(f"/api/conversations/{cid}/runs/latest").json()["run"] is None

    rid = db.create_run(cid)["id"]
    r = client.get(f"/api/conversations/{cid}/runs/latest")
    assert r.status_code == 200
    assert r.json()["run"]["id"] == rid
    assert r.json()["run"]["status"] == "running"

    # 不存在的会话 404
    assert client.get("/api/conversations/c_nope/runs/latest").status_code == 404


def test_delete_conversation_running_returns_409(client):
    cid = create_conversation(client)["id"]
    db.create_run(cid)  # status='running'
    assert client.delete(f"/api/conversations/{cid}").status_code == 409
    # 会话仍在
    assert client.get(f"/api/conversations/{cid}/messages").status_code == 200


def test_delete_conversation_scoped_artifacts(client):
    """删会话级联删其「过程稿」目录与索引行；任务「正式稿」不受影响。"""
    from app import artifact_store

    task = create_conversation(client)
    tid, cid = task["task_id"], task["id"]
    draft_scope = {"task_id": tid, "conversation_id": cid}
    m_draft = artifact_store.new_artifact_id()
    artifact_store.create_package(
        {"artifact_id": m_draft, "task_id": tid, "conversation_id": cid, "kind": "k", "schema": {}},
        "{}",
    )
    db.upsert_artifact_index(
        {
            "artifact_id": m_draft, "task_id": tid, "conversation_id": cid,
            "kind": "doc.note", "schema_id": "note-md", "schema_version": 1,
            "cardinality": "task-multi", "display_name": "笔记",
            "content_path": str(artifact_store.content_path(m_draft, draft_scope)),
            "content_seq": 1, "updated_at": "2026-08-25T00:00:00+00:00",
        }
    )
    m_formal = artifact_store.new_artifact_id()
    formal_scope = {"task_id": tid, "conversation_id": None}
    artifact_store.create_package(
        {"artifact_id": m_formal, "task_id": tid, "conversation_id": None, "kind": "k", "schema": {}},
        "{}",
    )
    db.upsert_artifact_index(
        {
            "artifact_id": m_formal, "task_id": tid, "conversation_id": None,
            "kind": "tender.directory", "schema_id": "tender-response-docs", "schema_version": 1,
            "cardinality": "task-single", "display_name": "投标目录",
            "content_path": str(artifact_store.content_path(m_formal, formal_scope)),
            "content_seq": 1, "updated_at": "2026-08-25T00:00:00+00:00",
        }
    )

    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    # 过程稿目录与索引已删（§16：threads/<cid>/ 整目录）
    assert db.get_artifact_index(m_draft) is None
    assert not artifact_store.package_ready(m_draft, draft_scope)
    assert not artifact_store.thread_dir(tid, cid).exists()
    # 正式稿保留
    assert db.get_artifact_index(m_formal)["artifact_id"] == m_formal
    assert artifact_store.package_ready(m_formal, formal_scope)


def test_scope_columns_migration(tmp_path, monkeypatch):
    """旧库（无新列）经 init_db 探测补齐 conversations.task_id 与 artifact_index 作用域列。"""
    import sqlite3

    legacy_dir = tmp_path / "legacy"  # 独立目录：不复用 db_env 已建好的新库
    legacy_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(legacy_dir))
    conn = sqlite3.connect(str(legacy_dir / "app.db"))
    conn.executescript(
        "CREATE TABLE conversations(id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);"
        "CREATE TABLE artifact_index(artifact_id TEXT PRIMARY KEY, task_id TEXT, kind TEXT NOT NULL,"
        " schema_id TEXT NOT NULL, schema_version INTEGER NOT NULL, cardinality TEXT NOT NULL,"
        " display_name TEXT NOT NULL, content_path TEXT NOT NULL, content_seq INTEGER NOT NULL DEFAULT 1,"
        " updated_at TEXT NOT NULL, last_run_id TEXT, last_thread_id TEXT, emitted INTEGER NOT NULL DEFAULT 0);"
    )
    conn.commit()
    conn.close()
    db.init_db()  # 探测补列，不抛错
    probe = sqlite3.connect(str(legacy_dir / "app.db"))
    cols_c = {r[1] for r in probe.execute("PRAGMA table_info(conversations)")}
    cols_a = {r[1] for r in probe.execute("PRAGMA table_info(artifact_index)")}
    probe.close()
    assert "task_id" in cols_c
    assert {"conversation_id", "promotion_proposed"} <= cols_a
