"""P4 任务层：任务 CRUD、任务归属发布、doc.note 收拢、确认、进度便签、任务上下文注入。"""

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


def test_task_creation_prebuilds_skeleton_dirs(client):
    """新建任务预建 sources/work + 管线子目录：agent 的 ls 不再 path_not_found。"""
    body = create_task(client, "骨架目录任务")
    tid = body["task"]["id"]
    assert artifact_store.sources_dir(tid).is_dir()
    assert artifact_store.work_dir(tid).is_dir()
    for rel in artifact_store._PROCESS_DIRS:
        assert (artifact_store.work_dir(tid) / rel).is_dir(), rel


def test_skeleton_self_heal_for_legacy_task(client):
    """骨架预建之前的旧任务只有库行、没有磁盘目录——run 启动自愈补齐后不再 path_not_found。"""
    import shutil

    body = create_task(client, "自愈任务")
    tid = body["task"]["id"]
    shutil.rmtree(artifact_store.task_dir(tid))
    assert not artifact_store.task_dir(tid).exists()
    # run 启动时的同一入口（幂等 mkdir parents）
    artifact_store.ensure_task_skeleton(tid)
    assert artifact_store.sources_dir(tid).is_dir()
    assert artifact_store.work_dir(tid).is_dir()
    for rel in artifact_store._PROCESS_DIRS:
        assert (artifact_store.work_dir(tid) / rel).is_dir(), rel


# ---------- 任务归属发布与过滤 ----------


def test_task_scoped_publish_and_filtering(env):
    task, conv = _task_env(env)
    m = publish.publish_artifact(
        DIR_KEY, _dir_content(), source={"skill": "t", "thread_id": conv["id"], "run_id": "r1"},
        task_id=task["id"], conversation_id=conv["id"],
    )
    # 文件归任务：task_id 恒为所属任务；conversation_id 是 provenance
    assert m["conversation_id"] == conv["id"]
    assert m["task_id"] == task["id"]

    row = db.get_artifact_index(m["artifact_id"])
    assert row["conversation_id"] == conv["id"]
    assert row["task_id"] == task["id"]

    # 过滤：任务归属可见全部；按会话（provenance）过滤亦命中
    assert len(db.list_artifact_index(task_id=task["id"])) == 1
    assert len(db.list_artifact_index(conversation_id=conv["id"])) == 1


def test_task_single_is_unique_per_task(env):
    """task-single 在任务内唯一：两个会话发布同契约 → 同一份产物（后写覆盖）。"""
    task = db.create_task("t")
    c1, c2 = db.create_conversation(task["id"], "a"), db.create_conversation(task["id"], "b")
    m1 = publish.publish_artifact(DIR_KEY, _dir_content("A"), task_id=task["id"], conversation_id=c1["id"])
    m2 = publish.publish_artifact(DIR_KEY, _dir_content("B"), task_id=task["id"], conversation_id=c2["id"])
    assert m1["artifact_id"] == m2["artifact_id"]

    # 同会话重发布 → 覆盖同 id
    m1b = publish.publish_artifact(DIR_KEY, _dir_content("A2"), task_id=task["id"], conversation_id=c1["id"])
    assert m1b["artifact_id"] == m1["artifact_id"]


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
        draft = artifact_store.staging_dir(task["id"]) / "analysis.json"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(
            json.dumps({"title": "废标项分析", "body_md": "- 投标保证金 3%"}, ensure_ascii=False),
            encoding="utf-8",
        )
        out = publish_tool.invoke(
            {"contract": "tender.disqualify/analysis@1", "draft_path": str(draft),
             "display_name": "废标项分析"}
        )
        assert out.startswith("[发布成功]")
        assert "未注册类型，已按通用笔记保存" in out

        rows = db.list_artifact_index(task_id=task["id"])
        assert len(rows) == 1 and rows[0]["kind"] == "doc.note"
        # 暂存草稿被移动消费，不留残骸
        assert not draft.exists()
    finally:
        runctx.clear_run()


def test_publish_tool_rejects_non_document_unknown_contract(env):
    task, conv = _task_env(env)
    draft = artifact_store.staging_dir(task["id"]) / "bad.json"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    runctx.set_run(conv["id"], "r9", task["id"])
    try:
        out = publish_tool.invoke({"contract": "no.such/contract@1", "draft_path": str(draft)})
    finally:
        runctx.clear_run()
    assert out.startswith("[发布失败]")
    assert "笔记" in out


# ---------- read 语义 ----------


def test_read_returns_single_current(env):
    task, conv = _task_env(env)
    runctx.set_run(conv["id"], "r1", task["id"])
    try:
        publish.publish_artifact(DIR_KEY, _dir_content("第一版"), task_id=task["id"])
        out = read_tool.invoke({"contract": DIR_KEY})
        assert "第一版" in out and out.lstrip().startswith("{")

        # 重发布覆盖 → 读到的即当前内容（单一真源、单一当前版本）
        publish.publish_artifact(DIR_KEY, _dir_content("第二版"), task_id=task["id"])
        out = read_tool.invoke({"contract": DIR_KEY})
        assert "第二版" in out and "第一版" not in out
    finally:
        runctx.clear_run()


def test_read_multi_note_requires_artifact_id(env):
    task, conv = _task_env(env)
    runctx.set_run(conv["id"], "r1", task["id"])
    try:
        publish.publish_artifact(NOTE_KEY, {"title": "a", "body_md": "甲"}, task_id=task["id"])
        out = read_tool.invoke({"contract": NOTE_KEY})
        assert out.startswith("[无成果]") or "甲" in out  # 单份直接给内容

        publish.publish_artifact(NOTE_KEY, {"title": "b", "body_md": "乙"}, task_id=task["id"])
        out = read_tool.invoke({"contract": NOTE_KEY})
        assert out.startswith("[多份成果]")

        rows = db.list_artifact_index(task_id=task["id"])
        out = read_tool.invoke({"contract": NOTE_KEY, "artifact_id": rows[0]["artifact_id"]})
        assert ("甲" in out) or ("乙" in out)
    finally:
        runctx.clear_run()


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


def test_task_context_block_lists_artifacts_with_state(env):
    from app.agent import _task_context_block

    task, conv = _task_env(env)
    db.update_task_progress(task["id"], "- 废标项 已完成")
    publish.publish_artifact(DIR_KEY, _dir_content(), task_id=task["id"])
    publish.publish_artifact(
        NOTE_KEY, {"title": "草稿笔记", "body_md": "x"}, display_name="草稿笔记", task_id=task["id"]
    )

    block = _task_context_block(task["id"], conv["id"])
    assert task["title"] in block
    assert "任务工作目录" in block and task["id"] in block  # 路径前缀注入
    assert "废标项 已完成" in block
    assert "任务产物" in block and "投标目录" in block
    assert "草稿笔记" in block

    assert _task_context_block("t_nope", conv["id"]) == ""


def test_delete_task_archival_failure_keeps_task(client, monkeypatch):
    """归档（mv）失败必须中止且不删库：任务/索引/磁盘目录原样保留，用户可重试。"""
    from tests.util import upload_file

    conv = create_conversation(client, title="会话B")
    tid, cid = conv["task_id"], conv["id"]
    m = publish.publish_artifact(DIR_KEY, _dir_content(), task_id=tid)
    upload_file(client, tid, "招标文件.docx", b"doc")

    real_move = artifact_store.shutil.move
    fail = {"on": True}

    def flaky_move(src, dst):
        if fail["on"]:
            raise OSError("模拟磁盘只读")
        return real_move(src, dst)

    monkeypatch.setattr(artifact_store.shutil, "move", flaky_move)
    r = client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 500
    assert "归档失败" in r.json()["detail"]

    # 现场完整保留
    assert db.get_task(tid) is not None
    assert db.get_conversation(cid) is not None
    assert db.get_artifact_index(m["artifact_id"]) is not None
    assert artifact_store.task_dir(tid).is_dir()
    assert artifact_store.archive_task_dir(tid).exists() is False

    # 恢复磁盘后重试删除成功
    fail["on"] = False
    r = client.delete(f"/api/tasks/{tid}")
    assert r.status_code == 200
    assert db.get_task(tid) is None
    assert artifact_store.task_dir(tid).exists() is False


# ---------- 删任务归档 / 删会话保留文件 ----------


def test_delete_task_archives_whole_dir(client):
    from tests.util import upload_file

    conv = create_conversation(client, title="会话A")
    tid, cid = conv["task_id"], conv["id"]
    m = publish.publish_artifact(DIR_KEY, _dir_content(), task_id=tid)
    note = publish.publish_artifact(NOTE_KEY, {"title": "n", "body_md": "b"}, task_id=tid, conversation_id=cid)
    upload_file(client, tid, "招标文件.docx", b"doc")

    assert client.delete(f"/api/tasks/{tid}").status_code == 200
    # 会话没了
    assert db.get_conversation(cid) is None
    assert db.get_task(tid) is None
    # 整目录软归档：产物/来源都在 archive/<task_id>/ 下，可手工找回
    assert db.get_artifact_index(m["artifact_id"]) is None
    archived = artifact_store.archive_task_dir(tid)
    assert (archived / "work" / "artifacts" / m["artifact_id"] / "meta.json").is_file()
    assert (archived / "sources" / "招标文件.docx").is_file()
    assert not artifact_store.package_ready(m["artifact_id"], m)
    assert not artifact_store.task_dir(tid).exists()  # 原位目录已整体移走
    # 文件归任务：产物统一在 work/artifacts/ 下，随归档保留
    assert (archived / "work" / "artifacts" / note["artifact_id"] / "meta.json").is_file()
    assert db.get_artifact_index(note["artifact_id"]) is None


def test_delete_conversation_keeps_task_files(client):
    """文件归任务：删会话只删转录，任务文件树（产物）保留。"""
    conv = create_conversation(client, title="要删的会话")
    tid, cid = conv["task_id"], conv["id"]
    m = publish.publish_artifact(DIR_KEY, _dir_content(), task_id=tid, conversation_id=cid)

    assert client.delete(f"/api/conversations/{cid}").status_code == 200
    assert db.get_conversation(cid) is None
    # 产物保留（文件归任务）
    row = db.get_artifact_index(m["artifact_id"])
    assert row is not None
    assert artifact_store.package_ready(m["artifact_id"], row)
