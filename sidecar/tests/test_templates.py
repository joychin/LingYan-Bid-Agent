"""/api/templates：版式库 CRUD/设默认/预览 + list_templates 只读工具。（「应用
到任务」换装 2026-09-08 用户拍板删除，整链端点/工具/契约随之移除；2026-09-09
「模板库」定名改「版式库」，标识符不动。）"""

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from app.tools import docx_ops, list_templates

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _make_custom_template(path, east="楷体", size=14) -> None:
    """用户自定义模板：Normal=楷体 14pt（无 Tender Body——用户自带模板没做过
    标书正文样式是常态，建节应降级不炸）。"""
    doc = Document()
    fonts = doc.styles["Normal"].element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:eastAsia"), east)
    doc.styles["Normal"].font.size = Pt(size)
    doc.save(path)


def _upload(client, path, name=None):
    r = client.post(
        "/api/templates",
        files={"file": (name or path.name, path.read_bytes(), _DOCX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_template_crud_and_activation(client, tmp_path):
    r = client.get("/api/templates")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["builtin"] and items[0]["active"] and items[0]["key"] == "__builtin__"

    # 非 docx / 损坏 docx 拒收
    assert (
        client.post("/api/templates", files={"file": ("a.txt", b"x", "text/plain")}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/templates", files={"file": ("bad.docx", b"not a docx", "application/octet-stream")}
        ).status_code
        == 400
    )

    tpl = tmp_path / "公司模板.docx"
    _make_custom_template(tpl)
    info = _upload(client, tpl)
    key = info["key"]

    items = client.get("/api/templates").json()
    assert len(items) == 2
    by_key = {t["key"]: t for t in items}
    assert by_key["__builtin__"]["active"]  # 上传=入库，不自动激活（生效=显式动作）
    assert not by_key[key]["active"]

    # 激活
    assert client.post(f"/api/templates/{key}/activate").status_code == 200
    by_key = {t["key"]: t for t in client.get("/api/templates").json()}
    assert by_key[key]["active"] and not by_key["__builtin__"]["active"]

    # 预览字节端点（用户 + 内置）
    assert client.get(f"/api/templates/{key}/raw").status_code == 200
    assert client.get("/api/templates/__builtin__/raw").status_code == 200

    # 内置不可删；显式切回内置 → 内置 active
    assert client.delete("/api/templates/__builtin__").status_code == 400
    assert client.post("/api/templates/__builtin__/activate").status_code == 200
    by_key = {t["key"]: t for t in client.get("/api/templates").json()}
    assert by_key["__builtin__"]["active"] and not by_key[key]["active"]

    # 删除激活中的用户模板 → 回落内置（不留悬空激活位）
    assert client.delete(f"/api/templates/{key}").status_code == 200
    items = client.get("/api/templates").json()
    assert len(items) == 1 and items[0]["builtin"] and items[0]["active"]
    assert client.post("/api/templates/不存在.docx/activate").status_code == 404


def test_activation_affects_new_documents(client, tmp_path):
    """激活即生效（无重启）：_active_template_path 指向用户模板，起建文档吃
    新定义；用户模板无 Tender Body 时降级 Normal 不失败。"""
    tpl = tmp_path / "政务模板.docx"
    _make_custom_template(tpl, east="仿宋", size=16)
    key = _upload(client, tpl)["key"]
    assert client.post(f"/api/templates/{key}/activate").status_code == 200

    assert docx_ops._active_template_path().name == "政务模板.docx"
    doc = docx_ops._new_document()
    fonts = doc.styles["Normal"].element.get_or_add_rPr().get_or_add_rFonts()
    assert fonts.get(qn("w:eastAsia")) == "仿宋"
    assert docx_ops._body_style(doc) is None  # 降级：正文段回落 Normal


def test_list_templates_tool_builtin_only(client):
    """空库：内置恒在且即默认——治实测「有多少模板」被答成 0 的盲区。"""
    r = list_templates.invoke({})
    assert "版式库共 1 个：内置 1 个、用户上传 0 个" in r
    assert "当前默认=内置标书基准版式" in r
    assert "1. 内置标书基准版式 —— 内置 · 当前默认" in r
    assert "界面「版式库」" in r  # 换默认的用户出口（工具只读）


def test_list_templates_tool_user_upload_and_activation(client, tmp_path):
    tpl = tmp_path / "公司模板.docx"
    _make_custom_template(tpl)
    key = _upload(client, tpl)["key"]

    r = list_templates.invoke({})
    assert "版式库共 2 个：内置 1 个、用户上传 1 个" in r
    assert "2. 公司模板 —— 用户上传" in r
    assert "1. 内置标书基准版式 —— 内置 · 当前默认" in r  # 上传不自动激活

    assert client.post(f"/api/templates/{key}/activate").status_code == 200
    r = list_templates.invoke({})
    assert "当前默认=公司模板" in r
    assert "公司模板 —— 用户上传" in r and " · 当前默认" in r
    assert "内置标书基准版式 —— 内置 · 当前默认" not in r


def test_list_templates_tool_error_path(client, monkeypatch):
    def _boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(docx_ops, "list_templates_info", _boom)
    r = list_templates.invoke({})
    assert r.startswith("[查询失败]")
    assert "RuntimeError" in r
