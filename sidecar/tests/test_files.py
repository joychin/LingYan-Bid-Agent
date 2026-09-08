"""/api/files（§16 任务级文件区）：任务必填 / 白名单 / 覆盖 / 列表 / 删除 / 文件名清洗。"""

from app import artifact_store
from tests.util import create_task, upload_file


def test_upload_list_delete(client):
    task = create_task(client)
    tid = task["task"]["id"]
    files_dir = artifact_store.sources_dir(tid)

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
    entries = r.json()["files"]
    names = [f["name"] for f in entries]
    assert names == ["招标文件.docx"]
    # abs_path：面板右键「打开文件夹」用（绝对路径，落在任务 sources/ 下）
    assert entries[0]["abs_path"].endswith(f"workspace/{tid}/sources/招标文件.docx")

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

    assert (artifact_store.sources_dir(ta["id"]) / "招标文件.docx").read_bytes() == b"from-task-a"
    assert (artifact_store.sources_dir(tb["id"]) / "招标文件.docx").read_bytes() == b"from-task-b"

    names_a = [f["name"] for f in client.get("/api/files", params={"task_id": ta["id"]}).json()["files"]]
    assert names_a == ["招标文件.docx"]


def test_upload_accepts_any_extension(client):
    """2026-08-28 放开白名单：上传不再按扩展名拒绝，类型是否可解析由 parse_document
    工具层裁决（.doc/图片未配文档解析时在解析时报人话，不挡上传）。"""
    task = create_task(client)
    tid = task["task"]["id"]
    r = client.post(
        "/api/files",
        params={"task_id": tid},
        files={"file": ("data.bin", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 201


def test_upload_accepts_doc(client):
    """.doc 可上传：解析层有云端文档解析路径（parse_document 未配置时报配置提示）。"""
    task = create_task(client)
    r = client.post(
        "/api/files",
        params={"task_id": task["task"]["id"]},
        files={"file": ("招标文件.doc", b"dummy", "application/octet-stream")},
    )
    assert r.status_code == 201


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
    assert (artifact_store.sources_dir(tid) / "evil.docx").exists()


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
    files_dir = artifact_store.sources_dir(tid)
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


def test_raw_roundtrip(client):
    """来源原件字节端点（面板预览）：上传→取字节 roundtrip + content-type；
    不存在 404；路径清洗与 containment 与 delete 同款。"""
    from urllib.parse import quote

    task = create_task(client)
    tid = task["task"]["id"]
    payload = b"%PDF-1.7 fake body"
    upload_file(client, tid, "招标文件.pdf", payload)

    r = client.get(f"/api/files/{quote('招标文件.pdf')}/raw", params={"task_id": tid})
    assert r.status_code == 200
    assert r.content == payload
    assert r.headers["content-type"].startswith("application/pdf")

    # 未知扩展名兜底 octet-stream；不存在/越界 404
    upload_file(client, tid, "附件.dat", b"zz")
    assert client.get(f"/api/files/{quote('附件.dat')}/raw", params={"task_id": tid}).headers[
        "content-type"
    ].startswith("application/octet-stream")
    assert client.get("/api/files/nope.pdf/raw", params={"task_id": tid}).status_code == 404
    assert client.get("/api/files/..%2Fsecret/raw", params={"task_id": tid}).status_code == 404
