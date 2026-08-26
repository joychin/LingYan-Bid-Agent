"""P4 任务层：任务 CRUD、双作用域发布、doc.note 收拢、转正、进度便签、任务上下文注入。"""

import json

import pytest

from app import artifact_store, contracts, db, publish, runctx
from app.tools.publish import publish_artifact as publish_tool
from app.tools.read import read_artifact as read_tool
from app.tools.task_progress import update_task_progress as progress_tool
from tests.util import create_conversation, create_task

DIR_KEY = "tender.directory/tender-response-docs@1"
NOTE_KEY = "doc.note/note-md@1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    return tmp_path


def _dir_content(name="技术部分"):
    return {
        "response_documents": [
            {"name": name, "scope": "", "directory": [{"目录名称": "目录", "level": 1, "children": []}]}
        ]
    }


def _task_env(env):
    task = db.create_task("市政项目投标")
    conv = db.create_conversation(task["id"], "解析目录")
    return task, conv


# ---------- 任务 CRUD ----------


def test_task_crud_and_progress(env):
    task = db.create_task("  ")
    assert task["title"] == "新任务"  # 空名兜底

    got = db.get_task(task["id"])
    assert got["progress_note"] == ""
    db.update_task_progress(task["id"], "- 废标项解析 已完成")
    assert db.get_task(task["id"])["progress_note"] == "- 废标项解析 已完成"

    with pytest.raises(ValueError):
        db.rename_task(task["id"], "  ")


def test_task_api_creates_first_conversation(client):
    body = create_task(client, "路灯采购项目")
    assert body["task"]["title"] == "路灯采购项目"
    assert body["conversation"]["task_id"] == body["task"]["id"]

    # PATCH：改任务名与进度便签
    tid = body["task"]["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"title": "新名", "progress_note": "进行中"})
    assert r.json()["title"] == "新名"
    assert r.json()["progress_note"] == "进行中"
    assert client.patch("/api/tasks/t_nope", json={"title": "x"}).status_code == 404


def test_conversation_requires_task(client):
    assert client.post("/api/conversations", json={}).status_code == 422
    assert client.post("/api/conversations", json={"task_id": "t_nope"}).status_code == 404


# ---------- 双作用域发布与过滤 ----------


def test_scoped_publish_and_filtering(env):
    task, conv = _task_env(env)
    m = publish.publish_artifact(
        DIR_KEY, _dir_content(), source={"skill": "t", "thread_id": conv["id"], "run_id": "r1"},
        conversation_id=conv["id"], propose_promotion=True,
    )
    # §16：conversation 作用域的 task_id 恒为所属任务（包位置派生依据）
    assert m["conversation_id"] == conv["id"]
    assert m["task_id"] == task["id"]

    row = db.get_artifact_index(m["artifact_id"])
    assert row["conversation_id"] == conv["id"]
    assert row["task_id"] == task["id"]
    assert row["promotion_proposed"] == 1

    # 过滤：会话作用域可见；任务（正式稿）过滤不含过程稿行
    assert len(db.list_artifact_index(conversation_id=conv["id"])) == 1
    assert db.list_artifact_index(task_id=task["id"]) == []


def test_conversation_scope_task_single_is_per_conversation(env):
    """task-single 在会话作用域内按会话唯一：两个会话各有一份自己的过程稿。"""
    task = db.create_task("t")
    c1, c2 = db.create_conversation(task["id"], "a"), db.create_conversation(task["id"], "b")
    m1 = publish.publish_artifact(DIR_KEY, _dir_content("A"), conversation_id=c1["id"])
    m2 = publish.publish_artifact(DIR_KEY, _dir_content("B"), conversation_id=c2["id"])
    assert m1["artifact_id"] != m2["artifact_id"]

    # 同会话重发布 → 覆盖同 id
    m1b = publish.publish_artifact(DIR_KEY, _dir_content("A2"), conversation_id=c1["id"])
    assert m1b["artifact_id"] == m1["artifact_id"]


def test_scope_mutex(env):
    with pytest.raises(publish.PublishError, match="互斥"):
        publish.publish_artifact(DIR_KEY, _dir_content(), task_id="t_1", conversation_id="c_1")


# ---------- doc.note 收拢 ----------


def test_note_contract_registered():
    c = contracts.get_contract(NOTE_KEY)
    assert c is not None
    assert c.cardinality == "task-multi"
    assert c.editable is True


def test_publish_tool_funnels_unknown_contract_to_note(env):
    task, conv = _task_env(env)
    runctx.set_run(conv["id"], "r9", task["id"])
    try:
        draft = artifact_store.task_drafts_dir(task["id"]) / "analysis.json"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(
            json.dumps({"title": "废标项分析", "body_md": "- 投标保证金 3%"}, ensure_ascii=False),
            encoding="utf-8",
        )
        out = publish_tool.invoke(
            {"contract": "tender.disqualify/analysis@1", "draft_path": str(draft),
             "display_name": "废标项分析", "propose_promotion": True}
        )
        assert out.startswith("[发布成功]")
        assert "未注册类型，已按通用笔记保存" in out
        assert "建议转正" in out

        rows = db.list_artifact_index(conversation_id=conv["id"])
        assert len(rows) == 1 and rows[0]["kind"] == "doc.note"
        assert rows[0]["promotion_proposed"] == 1
    finally:
        runctx.clear_run()


def test_publish_tool_rejects_non_document_unknown_contract(env):
    task, conv = _task_env(env)
    draft = artifact_store.task_drafts_dir(task["id"]) / "bad.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    runctx.set_run(conv["id"], "r9", task["id"])
    try:
        out = publish_tool.invoke({"contract": "no.such/contract@1", "draft_path": str(draft)})
    finally:
        runctx.clear_run()
    assert out.startswith("[发布失败]")
    assert "笔记" in out


# ---------- read 作用域 ----------


def test_read_prefers_formal_then_draft(env):
    task, conv = _task_env(env)
    runctx.set_run(conv["id"], "r1", task["id"])
    try:
        # 只有过程稿：读过程稿
        publish.publish_artifact(DIR_KEY, _dir_content("草稿"), conversation_id=conv["id"])
        assert "草稿" in read_tool.invoke({"contract": DIR_KEY})

        # 出现正式稿：优先读正式稿
        publish.publish_artifact(DIR_KEY, _dir_content("正式"), task_id=task["id"])
        out = read_tool.invoke({"contract": DIR_KEY})
        assert "正式" in out and "[来源：任务正式稿]" in out
    finally:
        runctx.clear_run()


def test_read_multi_note_requires_artifact_id(env):
    task, conv = _task_env(env)
    runctx.set_run(conv["id"], "r1", task["id"])
    try:
        publish.publish_artifact(NOTE_KEY, {"title": "a", "body_md": "甲"}, conversation_id=conv["id"])
        out = read_tool.invoke({"contract": NOTE_KEY})
        assert out.startswith("[无成果]") or "甲" in out  # 单份直接给内容

        publish.publish_artifact(NOTE_KEY, {"title": "b", "body_md": "乙"}, conversation_id=conv["id"])
        out = read_tool.invoke({"contract": NOTE_KEY})
        assert out.startswith("[多份成果]")

        rows = db.list_artifact_index(conversation_id=conv["id"])
        out = read_tool.invoke({"contract": NOTE_KEY, "artifact_id": rows[0]["artifact_id"]})
        assert ("甲" in out) or ("乙" in out)
    finally:
        runctx.clear_run()


# ---------- 转正 ----------


def test_promote_copies_draft_to_formal(env):
    task, conv = _task_env(env)
    m = publish.publish_artifact(
        DIR_KEY, _dir_content("初稿"), conversation_id=conv["id"], propose_promotion=True
    )
    aid = m["artifact_id"]

    # 转正 = 发布到任务作用域的复制件（首次：新 manifest 记 derived_from 谱系）
    promoted = publish.publish_artifact(
        DIR_KEY, _dir_content("初稿"), display_name="投标目录",
        source={"skill": "promote", "thread_id": conv["id"]},
        task_id=task["id"], derived_from=aid,
    )
    assert promoted["derived_from"] == aid
    assert promoted["task_id"] == task["id"]
    assert promoted["conversation_id"] is None
    assert json.loads(
        artifact_store.read_content(promoted["artifact_id"], promoted)
    )["response_documents"][0]["name"] == "初稿"
    # 正式稿包落在 formal/ 下（§16）
    assert artifact_store.artifact_dir(promoted["artifact_id"], promoted) == (
        artifact_store.formal_dir(task["id"]) / promoted["artifact_id"]
    )

    # 过程稿原件仍在，且内容未动
    assert artifact_store.package_ready(aid, m)
    assert json.loads(artifact_store.read_content(aid, m))["response_documents"][0]["name"] == "初稿"

    # 第二次转正（task-single 覆盖）：复用稳定 id，旧正式稿留恢复点
    first_formal_aid = promoted["artifact_id"]
    again = publish.publish_artifact(
        DIR_KEY, _dir_content("二稿"), task_id=task["id"], derived_from=aid,
    )
    assert again["artifact_id"] == first_formal_aid
    rp = artifact_store.latest_restore_point(first_formal_aid, promoted)
    assert json.loads(rp.read_text(encoding="utf-8"))["response_documents"][0]["name"] == "初稿"


def test_promote_endpoint_flow(client):
    conv = create_conversation(client)
    tid, cid = conv["task_id"], conv["id"]
    m = publish.publish_artifact(
        DIR_KEY, _dir_content("待转正"), conversation_id=cid, propose_promotion=True
    )
    r = client.post(f"/api/artifacts/{m['artifact_id']}/promote")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    formal = body["artifact"]
    assert formal["scope"] == "task"
    assert formal["task_id"] == tid
    assert formal["promotion_proposed"] is False

    # 来源过程稿：仍在、建议标记已清
    row = db.get_artifact_index(m["artifact_id"])
    assert row["conversation_id"] == cid
    assert row["promotion_proposed"] == 0

    # 列表过滤
    assert client.get("/api/artifacts", params={"task_id": tid}).json()["artifacts"][0]["artifact_id"] == formal["artifact_id"]
    drafts = client.get("/api/artifacts", params={"conversation_id": cid}).json()["artifacts"]
    assert [a["artifact_id"] for a in drafts] == [m["artifact_id"]]

    # 非过程稿转正 422
    assert client.post(f"/api/artifacts/{formal['artifact_id']}/promote").status_code == 422


# ---------- 进度便签工具 ----------


def test_update_task_progress_tool(env):
    task, conv = _task_env(env)
    runctx.set_run(conv["id"], "r1", task["id"])
    try:
        out = progress_tool.invoke({"progress_note": "- 解析 已完成\n- 目录 进行中"})
        assert out.startswith("[已更新]")
        assert "解析" in db.get_task(task["id"])["progress_note"]
    finally:
        runctx.clear_run()

    # 不在 run 中
    assert progress_tool.invoke({"progress_note": "x"}).startswith("[更新失败]")


# ---------- 任务上下文注入块 ----------


def test_task_context_block_lists_both_layers(env):
    from app.agent import _task_context_block

    task, conv = _task_env(env)
    db.update_task_progress(task["id"], "- 废标项 已完成")
    publish.publish_artifact(DIR_KEY, _dir_content(), task_id=task["id"])
    publish.publish_artifact(
        NOTE_KEY, {"title": "草稿笔记", "body_md": "x"}, display_name="草稿笔记", conversation_id=conv["id"]
    )

    block = _task_context_block(task["id"], conv["id"])
    assert task["title"] in block
    assert "任务工作目录" in block and task["id"] in block  # §16 路径前缀注入
    assert "废标项 已完成" in block
    assert "任务正式稿" in block and "投标目录" in block
    assert "本会话过程稿" in block and "草稿笔记" in block

    assert _task_context_block("t_nope", conv["id"]) == ""


# ---------- 删任务归档 ----------


def test_delete_task_archives_formal_and_removes_conversations(client):
    from tests.util import upload_file

    conv = create_conversation(client, title="会话A")
    tid, cid = conv["task_id"], conv["id"]
    m_formal = publish.publish_artifact(DIR_KEY, _dir_content(), task_id=tid)
    m_draft = publish.publish_artifact(NOTE_KEY, {"title": "n", "body_md": "b"}, conversation_id=cid)
    upload_file(client, tid, "招标文件.docx", b"doc")

    assert client.delete(f"/api/tasks/{tid}").status_code == 200
    # 会话没了
    assert db.get_conversation(cid) is None
    assert db.get_task(tid) is None
    # §16 整目录软归档：正式稿/上传文件都在 archive/<task_id>/ 下，可手工找回
    assert db.get_artifact_index(m_formal["artifact_id"]) is None
    archived = artifact_store.archive_task_dir(tid)
    assert (archived / "formal" / m_formal["artifact_id"] / "manifest.json").is_file()
    assert (archived / "files" / "招标文件.docx").is_file()
    assert not artifact_store.package_ready(m_formal["artifact_id"], m_formal)
    assert not artifact_store.task_dir(tid).exists()  # 原位目录已整体移走
    # 过程稿硬删（threads/ 先清，不进归档）
    assert "threads" not in [p.name for p in archived.iterdir()]
    assert not artifact_store.package_ready(m_draft["artifact_id"], m_draft)
    assert db.get_artifact_index(m_draft["artifact_id"]) is None
