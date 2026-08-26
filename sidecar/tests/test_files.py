"""/api/files（§16 任务级文件区）：任务必填 / 白名单 / 覆盖 / 列表 / 删除 / 文件名清洗。"""

from app import artifact_store
from tests.util import create_task, upload_file


def test_upload_list_delete(client):
    task = create_task(client)
    tid = task["task"]["id"]
    files_dir = artifact_store.task_files_dir(tid)

    # 上传（落任务 files/，不再落 workspace 根）
    body = upload_file(client, tid, "招标文件.docx", b"hello")
    assert body == {"name": "招标文件.docx", "size": 5, "overwritten": False}
    assert (files_dir / "招标文件.docx").read_bytes() == b"hello"

    # 同名覆盖（任务内语义）
    body = upload_file(client, tid, "招标文件.docx", b"hello2")
    assert body["overwritten"] is True

    # 列表只列该任务
    r = client.get("/api/files", params={"task_id": tid})
    assert r.status_code == 200
    names = [f["name"] for f in r.json()["files"]]
    assert names == ["招标文件.docx"]

    # 删除
    r = client.delete("/api/files/招标文件.docx", params={"task_id": tid})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert not (files_dir / "招标文件.docx").exists()

    # 删除不存在 → 404
    assert client.delete("/api/files/招标文件.docx", params={"task_id": tid}).status_code == 404


def test_upload_requires_task(client):
    """§16：无任务上下文上传被拒（422）；任务不存在 404。"""
    r = client.post("/api/files", files={"file": ("a.docx", b"x", "application/octet-stream")})
    assert r.status_code == 422
    r = client.post(
        "/api/files",
        params={"task_id": "t_nope00000000"},
        files={"file": ("a.docx", b"x", "application/octet-stream")},
    )
    assert r.status_code == 404
    assert client.get("/api/files").status_code == 422


def test_same_name_files_isolated_between_tasks(client):
    """§16 回归：两任务同名文件互不覆盖（旧全局平铺时的已知限制）。"""
    ta = create_task(client, "任务A")["task"]
    tb = create_task(client, "任务B")["task"]
    upload_file(client, ta["id"], "招标文件.docx", b"from-task-a")
    upload_file(client, tb["id"], "招标文件.docx", b"from-task-b")

    assert (artifact_store.task_files_dir(ta["id"]) / "招标文件.docx").read_bytes() == b"from-task-a"
    assert (artifact_store.task_files_dir(tb["id"]) / "招标文件.docx").read_bytes() == b"from-task-b"

    names_a = [f["name"] for f in client.get("/api/files", params={"task_id": ta["id"]}).json()["files"]]
    assert names_a == ["招标文件.docx"]


def test_upload_rejects_bad_extension(client):
    task = create_task(client)
    tid = task["task"]["id"]
    r = client.post(
        "/api/files",
        params={"task_id": tid},
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_rejects_doc(client):
    """.doc 移出白名单：上传即拒并提示另存为 .docx（仅支持 .docx/.pdf/.txt/.md）。"""
    task = create_task(client)
    r = client.post(
        "/api/files",
        params={"task_id": task["task"]["id"]},
        files={"file": ("招标文件.doc", b"dummy", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "另存为 .docx" in r.json()["detail"]


def test_upload_rejects_hidden_name(client):
    task = create_task(client)
    r = client.post(
        "/api/files",
        params={"task_id": task["task"]["id"]},
        files={"file": (".secret.docx", b"x", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_cleans_path_name(client):
    task = create_task(client)
    tid = task["task"]["id"]
    r = client.post(
        "/api/files",
        params={"task_id": tid},
        files={"file": ("../evil.docx", b"x", "application/octet-stream")},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "evil.docx"
    assert (artifact_store.task_files_dir(tid) / "evil.docx").exists()


def test_upload_rejects_too_large(client, monkeypatch):
    """上限 100MB（常量）；monkeypatch 小阈值即可验证同一增量检查路径。"""
    import app.api.files as files_mod

    monkeypatch.setattr(files_mod, "MAX_SIZE_BYTES", 6)
    task = create_task(client)
    r = client.post(
        "/api/files",
        params={"task_id": task["task"]["id"]},
        files={"file": ("big.docx", b"x" * 7, "application/octet-stream")},
    )
    assert r.status_code == 413


def test_oversize_overwrite_keeps_original(client, monkeypatch):
    """同名上传超限文件时，磁盘上已存在的旧文件不能被破坏（回归：曾直接 unlink 目标）。"""
    import app.api.files as files_mod

    monkeypatch.setattr(files_mod, "MAX_SIZE_BYTES", 6)
    task = create_task(client)
    tid = task["task"]["id"]
    files_dir = artifact_store.task_files_dir(tid)
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / "keep.docx").write_bytes(b"original-content")

    r = client.post(
        "/api/files",
        params={"task_id": tid},
        files={"file": ("keep.docx", b"x" * 7, "application/octet-stream")},
    )
    assert r.status_code == 413
    # 原文件完好，且没有残留 .part 临时文件
    assert (files_dir / "keep.docx").read_bytes() == b"original-content"
    assert not list(files_dir.glob(".*.part"))
