"""tender_toc 工具路径 containment：只允许 workspace 内的文件。"""

import pytest


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.tools import tender_toc

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return tender_toc, workspace


def test_resolve_path_inside_workspace(ws):
    tender_toc, workspace = ws
    f = workspace / "招标文件.docx"
    f.write_text("x", encoding="utf-8")
    assert tender_toc._resolve_path("招标文件.docx") == f.resolve()
    assert tender_toc._resolve_path(str(f)) == f.resolve()


def test_resolve_path_rejects_outside(ws, tmp_path):
    tender_toc, workspace = ws
    # 绝对路径逃逸
    with pytest.raises(ValueError):
        tender_toc._resolve_path("/etc/passwd")
    # 相对路径 .. 穿越
    with pytest.raises(ValueError):
        tender_toc._resolve_path("../outside.docx")
    # workspace 之外已存在的文件
    outside = tmp_path / "outside.docx"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        tender_toc._resolve_path(str(outside))
