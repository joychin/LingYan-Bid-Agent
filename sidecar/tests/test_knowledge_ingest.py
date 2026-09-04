"""知识库入库管线（v3 事实层）：三合一抽取+说明段、失败降级、图片落盘（仅供查看）。
章节拆分/写作素材在独立素材库（test_materials_lib.py），知识库无章节块。"""

import json

from app import db
from app.knowledge import store
from app.knowledge.ingest import run_ingest
from tests.util import init_env


class _FakeResp:
    def __init__(self, content):
        self.content = content


def _extract_json(statement=None, doc_type="qualification_certificate", fields=None):
    return json.dumps(
        {"doc_type": doc_type, "confidence": 0.9, "statement": statement or "",
         "fields": fields or {}},
        ensure_ascii=False,
    )


class _SmartLLM:
    """抽取工序 fake：按文件名判类型（标书类→past_proposal，默认→证书）。"""

    def __init__(self, **kwargs):
        pass

    def invoke(self, messages):
        prompt = messages[-1][1]
        if "文件名：历史标书" in prompt or "文件名：大标书" in prompt or "文件名：范文" in prompt:
            return _FakeResp(_extract_json(
                doc_type="past_proposal",
                statement="技术标共 8 章。",
                fields={"project_name": {"value": "某园区项目", "source": "L1"}},
            ))
        return _FakeResp(_extract_json(
            statement="ISO9001 质量管理体系认证，证书编号 CN-001（第1页），有效期至 2028-06-30（第1页）。",
            fields={"valid_until": {"value": "2028-06-30", "source": "第1页"}},
        ))


class _BoomLLM:
    def __init__(self, **kwargs):
        pass

    def invoke(self, messages):
        raise RuntimeError("llm down")


def _setup(tmp_path, monkeypatch, llm=None):
    init_env(tmp_path, monkeypatch)
    store.ensure_dirs()
    if llm is not None:
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        import langchain_deepseek

        monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", llm)


def _upload(name: str, content: bytes) -> str:
    import hashlib

    src = store.kb_files_dir() / name
    src.write_bytes(content)
    item = db.kb_insert_item(file_name=name, file_hash=hashlib.sha256(content).hexdigest(),
                             title=src.stem, ext=src.suffix)
    return item["id"]


def test_extract_statement_and_doc_type(tmp_path, monkeypatch):
    """三合一抽取：类型+说明+时间字段落库；说明段可检索。"""
    _setup(tmp_path, monkeypatch, llm=_SmartLLM)
    kid = _upload("iso证书.txt", ("# 证书\n\n" + "ISO9001 质量管理体系认证证书正文内容，" * 4).encode())
    item = run_ingest(kid)
    assert item["parse_status"] == "ready"
    assert item["extract_status"] == "done"
    assert item["doc_type"] == "qualification_certificate"
    sug = json.loads(item["suggested_metadata"])
    assert "ISO9001" in sug["statement"] and "第1页" in sug["statement"]

    from app.knowledge import fts

    hits = db.kb_search_segments(fts.build_match_expr("CN-001"), limit=5)
    assert any(h.get("section_path") == "§statement" for h in hits)
    assert item.get("progress") is None


def test_fact_gate_no_blocks(tmp_path, monkeypatch):
    """素材分离闸门：知识库任何类型都不建章节块/不产块行（写作素材在素材库）。"""
    _setup(tmp_path, monkeypatch, llm=_SmartLLM)
    kid = _upload("历史标书.txt", ("# 一、方案\n\n" + "智慧园区总体架构内容文本。" * 30).encode())
    item = run_ingest(kid)
    assert item["doc_type"] == "past_proposal"
    # 知识库侧无块表/无素材端点；materials.json 不产出
    _, _, _, mp = store.kb_parse_paths("历史标书.txt")
    assert not (mp.parent / "blocks.json").exists()
    # 检索段仍就绪（outline 段+说明段）
    from app.knowledge import fts

    assert db.kb_search_segments(fts.build_match_expr("智慧园区"), limit=3)


def test_extract_failure_degrades(tmp_path, monkeypatch):
    """抽取失败：可检索、字段空、extract failed——独立降级。"""
    _setup(tmp_path, monkeypatch, llm=_BoomLLM)
    kid = _upload("资料.txt", ("# 资料\n\n" + "公司拥有信息安全服务资质证书与专业团队，服务过多家大型客户并获得好评。" * 2).encode())
    item = run_ingest(kid)
    assert item["parse_status"] == "ready"
    assert item["extract_status"] == "failed"
    from app.knowledge import fts

    assert db.kb_search_segments(fts.build_match_expr("资质"), limit=3)


def test_no_key_skips_extract(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)  # 无 LLM_API_KEY
    kid = _upload("c.txt", b"# x\n\n" + "内容".encode() * 100)
    item = run_ingest(kid)
    assert item["extract_status"] == "skipped"


def test_docx_image_count_in_meta(tmp_path, monkeypatch):
    """docx 内嵌图片计数进解析概况（不再静默丢弃）。"""
    _setup(tmp_path, monkeypatch)
    from app.parse import convert as parse_convert

    real = parse_convert

    class _FakeResult:
        md = "# 证\n\n内容"
        info = {"conversion": "docx-native", "tables": 0, "image_count": 37}

    monkeypatch.setattr("app.knowledge.ingest.parse_convert", lambda src: _FakeResult())
    _ = real  # 保留引用
    kid = _upload("带图.docx", b"fake-docx-bytes")
    run_ingest(kid)
    _, _, meta_path, _ = store.kb_parse_paths("带图.docx")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["image_count"] == 37


def test_extract_validation(tmp_path, monkeypatch):
    """extract.validate_suggested：类型兜底/锚点键分流/写法类短说明/事实类过短说明无效。"""
    from app.knowledge.extract import validate_suggested

    out = validate_suggested(
        {"doc_type": "bogus", "statement": "x" * 10,
         "fields": {"valid_until": {"value": "2027-01-01", "source": "L1"},
                    "自由键": {"value": "v", "source": "L2"}}},
        "随便.docx",
    )
    assert out["doc_type"] == "other"  # 无 hint 兜底
    assert "valid_until" in out["fields"] and "自由键" not in out["fields"]
    assert "自由键" in out["extra"]
    assert out.get("statement") is None or out["statement"] == ""  # 事实类过短说明无效

    out2 = validate_suggested(
        {"doc_type": "past_proposal", "statement": "技术标共 8 章，重点：园区架构与运维。"},
        "标书.docx",
    )
    assert "共 8 章" in out2["statement"]  # 写法类保留结构概览


# ---------- 图片抽取（确定性零 LLM，仅供内容页查看） ----------

def _make_docx_with_images(tmp_path, n_images=3) -> bytes:
    """构造带嵌入图片的 docx（python-docx add_picture 真实图片）。"""
    import io

    import fitz
    from docx import Document

    doc = Document()
    doc.add_heading("产品介绍", 0)
    doc.add_paragraph("本产品手册介绍公司核心产品线的总体架构与关键能力特性说明。")
    for i in range(40):
        doc.add_paragraph(f"产品能力说明第{i + 1}条：平台核心功能模块的详细能力描述文本，"
                          "覆盖架构分层、部署形态与运维保障等多个维度的内容补充。")
    for i in range(n_images):
        # 每张图不同（docx 对相同图片去重成一个 media part）
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600 + i, 400))
        pix.set_rect(pix.irect, (200 + i * 10, 120, 40))
        doc.add_paragraph(f"图{i + 1}说明：系统架构与部署拓扑的示意说明文本。")
        doc.add_picture(io.BytesIO(pix.tobytes("png")))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_docx_images_land_on_disk_only(tmp_path, monkeypatch):
    """图片抽取降级：落盘供内容页查看（清单可列），与素材彻底无关。"""
    _setup(tmp_path, monkeypatch, llm=_SmartLLM)

    class _ProfileLLM(_SmartLLM):
        def invoke(self, messages):
            prompt = messages[-1][1]
            if "文件名：产品介绍" in prompt:
                return _FakeResp(_extract_json(doc_type="technical_doc", statement="产品手册，含架构图。"))
            return super().invoke(messages)

    import langchain_deepseek

    monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", _ProfileLLM)
    kid = _upload("产品介绍.docx", _make_docx_with_images(tmp_path))
    item = run_ingest(kid)
    assert item["parse_status"] == "ready"
    assert item["doc_type"] == "technical_doc"
    # 图片落盘 + 清单可列（内容页折叠区数据源）
    from app.knowledge import images as images_mod
    from app.knowledge import store as kstore

    img_dir = kstore.kb_images_dir("产品介绍.docx")
    assert sum(1 for p in img_dir.iterdir() if p.is_file()) == 3  # 三张 600×400 图全过过滤
    assert len(images_mod.list_images("产品介绍.docx")) == 3


def test_small_images_filtered(tmp_path, monkeypatch):
    """装饰图过滤：短边 <200px 的图被丢弃。"""
    from app.knowledge import images as images_mod

    _setup(tmp_path, monkeypatch)
    import io

    import fitz
    from docx import Document

    doc = Document()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 40))  # 80×40 小图
    pix.set_rect(pix.irect, (10, 10, 10))
    doc.add_picture(io.BytesIO(pix.tobytes("png")))
    out = io.BytesIO()
    doc.save(out)
    src = store.kb_files_dir() / "装饰.docx"
    src.write_bytes(out.getvalue())
    written, skipped = images_mod.extract_images(src, "装饰.docx")
    assert written == 0 and skipped == 1  # 装饰图计入跳过


def test_unfriendly_image_converted_to_png():
    """TIFF/BMP（浏览器原生不解码）转 PNG；友好格式原样返回。"""
    from app.knowledge import images as images_mod

    # 最小 1×1 24bit BMP（fitz 不能写 BMP/TIFF，手拼字节）
    bmp = (
        b"BM" + (58).to_bytes(4, "little") + b"\x00\x00\x00\x00" + (54).to_bytes(4, "little")
        + (40).to_bytes(4, "little") + (1).to_bytes(4, "little") + (1).to_bytes(4, "little")
        + (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + (0).to_bytes(4, "little")
        + (4).to_bytes(4, "little") + b"\x00" * 16
        + b"\xff\x00\x00\x00"
    )
    data, ext = images_mod.as_browser_friendly(bmp, ".bmp")
    assert ext == ".png" and data.startswith(b"\x89PNG")
    # 转码失败兜底：返回原始字节
    data2, ext2 = images_mod.as_browser_friendly(b"not-an-image", ".tif")
    assert data2 == b"not-an-image" and ext2 == ".tif"
    # 友好格式原样透传
    data3, ext3 = images_mod.as_browser_friendly(b"\x89PNG-rest", ".png")
    assert data3 == b"\x89PNG-rest" and ext3 == ".png"
