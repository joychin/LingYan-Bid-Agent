"""产物：out/ 快照 diff、类型推断、db 与 /api/artifacts 端点。"""

import pytest


@pytest.fixture
def art(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import artifacts

    return artifacts, tmp_path


def test_snapshot_and_diff_new_and_changed(art):
    artifacts, tmp = art
    out = tmp / "workspace" / "out"
    out.mkdir(parents=True)
    (out / "a.json").write_text("{}", encoding="utf-8")
    (out / "b.html").write_text("<html></html>", encoding="utf-8")

    snap = artifacts.snapshot_out()
    assert set(snap) == {"a.json", "b.html"}

    # 无变化 → 无产物
    assert artifacts.diff_artifacts(snap) == []

    # 新增
    (out / "c.md").write_text("# hi", encoding="utf-8")
    names = {f["name"] for f in artifacts.diff_artifacts(snap)}
    assert names == {"c.md"}

    # 大小变化命中，未变的不命中
    (out / "b.html").write_text("<html>more</html>", encoding="utf-8")
    names = {f["name"] for f in artifacts.diff_artifacts(snap)}
    assert "b.html" in names
    assert "a.json" not in names


def test_detect_type(art):
    artifacts, _ = art
    assert artifacts.detect_type("tender-directory.html") == "html"
    assert artifacts.detect_type("a.JSON") == "json"  # 大小写不敏感
    assert artifacts.detect_type("notes.md") == "md"
    assert artifacts.detect_type("tender.exe") == "other"


def test_artifacts_api_list_filters_and_content(client):
    from app import db
    from app.config import workspace_dir

    out = workspace_dir() / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "tender-directory.html").write_text("<h1>目录</h1>", encoding="utf-8")

    # 一条磁盘存在的记录 + 一条磁盘已不存在的记录
    db.create_artifact(
        "a_1", "c_conv", "r_run", "tender-directory.html",
        str(out / "tender-directory.html"), "html", 20,
    )
    db.create_artifact("a_2", "c_conv", "r_run", "gone.html", str(out / "gone.html"), "html", 10)

    r = client.get("/api/artifacts")
    assert r.status_code == 200
    names = [a["name"] for a in r.json()["artifacts"]]
    assert names == ["tender-directory.html"]  # gone.html 已从磁盘删除 → 过滤

    r = client.get("/api/artifacts/a_1/content")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.text == "<h1>目录</h1>"

    r = client.get("/api/artifacts/a_2/content")
    assert r.status_code == 410  # 记录在但磁盘缺失

    r = client.get("/api/artifacts/nope/content")
    assert r.status_code == 404


def test_artifacts_api_rejects_out_of_workspace_path(client, tmp_path):
    """脏数据/历史记录的 path 指向工作区外：列表过滤 + content 拒读。"""
    from app import db

    secret = tmp_path / "secret.md"
    secret.write_text("secret", encoding="utf-8")
    db.create_artifact("a_evil", "c_conv", "r_run", "secret.md", str(secret), "md", 6)

    r = client.get("/api/artifacts")
    assert r.status_code == 200
    assert all(a["id"] != "a_evil" for a in r.json()["artifacts"])

    assert client.get("/api/artifacts/a_evil/content").status_code == 410


def test_artifacts_api_rejects_symlink_escape(client):
    """out/ 内指向工作区外的 symlink：resolve 后越界，同样拒读。"""
    from app import db
    from app.config import workspace_dir

    out = workspace_dir() / "out"
    out.mkdir(parents=True, exist_ok=True)
    secret = workspace_dir().parent / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    link = out / "link.md"
    link.symlink_to(secret)
    db.create_artifact("a_link", "c_conv", "r_run", "link.md", str(link), "md", 6)

    assert client.get("/api/artifacts/a_link/content").status_code == 410
    assert all(a["id"] != "a_link" for a in client.get("/api/artifacts").json()["artifacts"])
