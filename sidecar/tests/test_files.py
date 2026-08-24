"""/api/files：上传白名单 / 覆盖 / 列表 / 删除 / 文件名清洗。"""


def test_upload_list_delete(client, tmp_path):
    from app.config import workspace_dir

    ws = workspace_dir()
    ws.mkdir(parents=True, exist_ok=True)

    # 上传
    r = client.post(
        "/api/files",
        files={"file": ("招标文件.docx", b"hello", "application/octet-stream")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "招标文件.docx"
    assert body["size"] == 5
    assert body["overwritten"] is False
    assert (ws / "招标文件.docx").read_bytes() == b"hello"

    # 同名覆盖
    r = client.post(
        "/api/files",
        files={"file": ("招标文件.docx", b"hello2", "application/octet-stream")},
    )
    assert r.status_code == 201
    assert r.json()["overwritten"] is True

    # 列表含该文件
    r = client.get("/api/files")
    assert r.status_code == 200
    names = [f["name"] for f in r.json()["files"]]
    assert "招标文件.docx" in names

    # 删除
    r = client.delete("/api/files/招标文件.docx")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert not (ws / "招标文件.docx").exists()

    # 删除不存在 → 404
    r = client.delete("/api/files/招标文件.docx")
    assert r.status_code == 404


def test_upload_rejects_bad_extension(client):
    r = client.post(
        "/api/files",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_rejects_hidden_name(client):
    r = client.post(
        "/api/files",
        files={"file": (".secret.docx", b"x", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_cleans_path_name(client):
    from app.config import workspace_dir

    ws = workspace_dir()
    ws.mkdir(parents=True, exist_ok=True)
    r = client.post(
        "/api/files",
        files={"file": ("../evil.docx", b"x", "application/octet-stream")},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "evil.docx"
    assert (ws / "evil.docx").exists()


def test_upload_rejects_too_large(client):
    r = client.post(
        "/api/files",
        files={"file": ("big.docx", b"x" * (50 * 1024 * 1024 + 1), "application/octet-stream")},
    )
    assert r.status_code == 413


def test_oversize_overwrite_keeps_original(client):
    """同名上传超限文件时，磁盘上已存在的旧文件不能被破坏（回归：曾直接 unlink 目标）。"""
    from app.config import workspace_dir

    ws = workspace_dir()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "keep.docx").write_bytes(b"original-content")

    r = client.post(
        "/api/files",
        files={"file": ("keep.docx", b"x" * (50 * 1024 * 1024 + 1), "application/octet-stream")},
    )
    assert r.status_code == 413
    # 原文件完好，且没有残留 .part 临时文件
    assert (ws / "keep.docx").read_bytes() == b"original-content"
    assert not list(ws.glob(".*.part"))
