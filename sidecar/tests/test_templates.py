"""/api/templates：模板库 CRUD/激活/预览 + 任务换装（重建式+恢复点+409 守卫）。"""

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from app import artifact_store, runctx
from app.tools import docx_ops
from tests.util import create_task

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


def _mk_section(path, title, paragraphs=""):
    r = docx_ops.docx_section_create.invoke({"path": path, "title": title, "paragraphs": paragraphs})
    assert r.startswith("[已创建]"), r


def test_apply_restyle_to_task(client, tmp_path):
    """换装=重建式：生效模板重建节文件，内置样式段吃新定义、内容/修订保留、
    旧版入恢复点；「整本-」派生物跳过。"""
    body = create_task(client)
    tid = body["task"]["id"]
    conv = client.post("/api/conversations", json={"task_id": tid, "title": "c"}).json()
    runctx.set_run(conv["id"], "r_tpl", tid)
    _mk_section("body/技术部分/3.1 方案.docx", "3.1 方案", "正文内容一。")
    _mk_section("body/投标函.docx", "投标函")
    vol = artifact_store.work_dir(tid) / "body" / "整本-技术部分.docx"
    vol.parent.mkdir(parents=True, exist_ok=True)
    Document().save(vol)

    tpl = tmp_path / "新版模板.docx"
    _make_custom_template(tpl, east="楷体", size=15)
    key = _upload(client, tpl)["key"]
    assert client.post(f"/api/templates/{key}/activate").status_code == 200
    runctx.clear_run()

    r = client.post("/api/templates/apply", json={"task_id": tid})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["applied"] == 2 and rep["skipped_volumes"] == 1 and rep["failed"] == 0
    assert all(x["ok"] for x in rep["results"])

    sec = artifact_store.work_dir(tid) / "body" / "技术部分" / "3.1 方案.docx"
    doc = Document(str(sec))
    fonts = doc.styles["Normal"].element.get_or_add_rPr().get_or_add_rFonts()
    assert fonts.get(qn("w:eastAsia")) == "楷体"  # 新模板定义生效
    texts = [p.text for p in doc.paragraphs]
    assert "3.1 方案" in texts and "正文内容一。" in texts  # 内容原样
    rp_dir = sec.parent / (sec.name + ".restorepoints")
    assert rp_dir.is_dir() and any(rp_dir.glob("*.bak"))  # 恢复点兜底
    assert not list((sec.parent).glob("*.restyle.tmp"))  # 原子落盘无临时残留

    # 404 任务不存在 / 409 活跃 run 守卫
    assert client.post("/api/templates/apply", json={"task_id": "t_nope"}).status_code == 404
    from app import db

    db.create_run(conv["id"])
    assert client.post("/api/templates/apply", json={"task_id": tid}).status_code == 409
