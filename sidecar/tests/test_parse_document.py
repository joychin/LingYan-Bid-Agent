"""parse_document 工具：containment / 转换 / 行号 outline / 幂等 / 失败语义（§16 任务级 out/）。"""

import json

import pymupdf  # 测试用：运行时生成 PDF，仿 _make_docx 做法
import pytest
from docx import Document

from app.config import workspace_dir
from app.tools.parse_document import parse_document
from tests.util import init_env


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """§16：解析产物落当前任务 out/，夹具内预置 run 上下文（任务+会话）。"""
    from app import runctx

    task, conv = init_env(tmp_path, monkeypatch)
    w = workspace_dir()
    w.mkdir(parents=True, exist_ok=True)
    runctx.set_run(conv["id"], "r_test", task["id"])
    yield w
    runctx.clear_run()


def _out_parse(ws):
    """当前任务的 out/parse/ 根（§16：产物在 <task>/out/ 下）。"""
    from app import db

    tid = db.list_tasks()[0]["id"]
    return ws / tid / "out" / "parse"


def _make_docx(path, with_table=True):
    doc = Document()
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_paragraph("本项目为测试采购项目，现邀请合格投标人参加投标。")
    doc.add_heading("第二章 投标人须知", level=1)
    doc.add_paragraph("前附表：本须知前附表是对投标人须知的具体补充。")
    doc.add_heading("递交要求", level=2)
    doc.add_paragraph("投标人应在截止时间前递交密封的投标文件。")
    if with_table:
        t = doc.add_table(rows=2, cols=2)
        t.rows[0].cells[0].text = "包号"
        t.rows[0].cells[1].text = "内容"
        t.rows[1].cells[0].text = "包1"
        t.rows[1].cells[1].text = "软件开发服务"
    doc.save(str(path))


def test_path_containment(ws, tmp_path):
    outside = tmp_path / "outside.docx"
    _make_docx(outside)
    r = parse_document.invoke({"path": str(outside)})
    assert r.startswith("[解析失败]")
    assert "越界" in r


def test_missing_file(ws):
    r = parse_document.invoke({"path": "不存在.docx"})
    assert r.startswith("[解析失败]")
    assert "不存在" in r


def test_unsupported_ext(ws):
    f = ws / "readme.html"
    f.write_text("hello", encoding="utf-8")
    r = parse_document.invoke({"path": "readme.html"})
    assert r.startswith("[解析失败]")
    assert "不支持的输入格式" in r


def test_doc_rejected(ws):
    """.doc 明确拒绝并提示另存为 .docx（仅支持 .docx/.pdf）。"""
    f = ws / "招标文件.doc"
    f.write_bytes(b"dummy")
    r = parse_document.invoke({"path": "招标文件.doc"})
    assert r.startswith("[解析失败]")
    assert "另存为 .docx" in r


def test_requires_task_context(ws):
    """§16：解析产物归属任务 out/，无任务上下文直接失败。"""
    from app import runctx

    runctx.clear_run()
    try:
        r = parse_document.invoke({"path": "招标文件.docx"})
    finally:
        pass  # 夹具 teardown 会再 clear 一次，无需恢复
    assert r.startswith("[解析失败]")
    assert "任务上下文" in r


def test_bare_name_resolves_from_task_files(ws):
    """模型只说裸文件名：workspace 根没有时回退当前任务 files/ 找（上传区）。"""
    from app import artifact_store, db

    tid = db.list_tasks()[0]["id"]
    fdir = artifact_store.task_files_dir(tid)
    fdir.mkdir(parents=True, exist_ok=True)
    _make_docx(fdir / "招标文件.docx")
    r = parse_document.invoke({"path": "招标文件.docx"})  # 根下无此文件
    assert r.startswith("[解析成功]"), r


def _make_pdf(path):
    """运行时生成带字号层级的 PDF（标题 18pt / 正文 12pt），验证 PyMuPDF 提取。

    注意 insert_text 不自动换行，正文每行需控制在单行宽度内；总字符 > 100 过 _MIN_TEXT_CHARS。
    默认 Helvetica 无 CJK 字形，中文须用内置中文字体 china-s，否则渲染为占位符。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "第一章 招标公告", fontsize=18, fontname="china-s")
    page.insert_text((72, 110), "本项目为测试采购项目，现邀请合格投标人参加投标。", fontsize=12, fontname="china-s")
    page.insert_text((72, 140), "招标范围包括软件开发、系统集成与三年运维服务。", fontsize=12, fontname="china-s")
    page.insert_text((72, 170), "投标人应具备相应资质，并在截止时间前提交投标文件。", fontsize=12, fontname="china-s")
    page.insert_text((72, 220), "第二章 投标人须知", fontsize=18, fontname="china-s")
    page.insert_text((72, 260), "投标人应在截止时间前递交密封投标文件，逾期不予受理。", fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()


def test_pdf_convert_and_outline(ws):
    _make_pdf(ws / "招标文件.pdf")
    r = parse_document.invoke({"path": "招标文件.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "招标文件.pdf"
    md = (out_dir / "招标文件.pdf.md").read_text(encoding="utf-8")
    outline = json.loads((out_dir / "招标文件.pdf.outline.json").read_text(encoding="utf-8"))
    meta = json.loads((out_dir / "招标文件.pdf.meta.json").read_text(encoding="utf-8"))

    # 标题（字号启发式）与正文都进 markdown
    assert "# 第一章 招标公告" in md
    assert "# 第二章 投标人须知" in md
    assert "本项目为测试采购项目" in md

    # 行号区间与 md 中标题实际位置一致
    lines = md.splitlines()

    def find_line(text):
        return next(i for i, ln in enumerate(lines, 1) if ln.strip() == text)

    top = [n for n in outline if n["标题"] == "第一章 招标公告"][0]
    assert top["level"] == 1
    assert top["start_line"] == find_line("# 第一章 招标公告")
    assert top["end_line"] == find_line("# 第二章 投标人须知") - 1

    assert meta["source"] == "招标文件.pdf"
    assert meta["conversion"] == "pdf-fontsize"  # 无书签 → 字号启发式档
    assert meta["headings"] >= 2
    assert "<!-- p:1 -->" in md  # 页码锚点


def test_convert_and_outline_line_ranges(ws):
    _make_docx(ws / "招标文件.docx")
    r = parse_document.invoke({"path": "招标文件.docx"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "招标文件.docx"
    md = (out_dir / "招标文件.docx.md").read_text(encoding="utf-8")
    outline = json.loads((out_dir / "招标文件.docx.outline.json").read_text(encoding="utf-8"))
    meta = json.loads((out_dir / "招标文件.docx.meta.json").read_text(encoding="utf-8"))

    # markdown：标题层级 + 表格 pipe 化
    assert "# 第一章 招标公告" in md
    assert "## 递交要求" in md
    assert "| 包号 | 内容 |" in md

    # outline：行号区间必须与 md 中标题实际位置一致
    lines = md.splitlines()

    def find_line(text):
        return next(i for i, ln in enumerate(lines, 1) if ln.strip() == text)

    top = [n for n in outline if n["标题"] == "第一章 招标公告"][0]
    assert top["level"] == 1
    assert top["start_line"] == find_line("# 第一章 招标公告")
    assert top["end_line"] == find_line("# 第二章 投标人须知") - 1

    ch2 = [n for n in outline if n["标题"] == "第二章 投标人须知"][0]
    child = [n for n in ch2["children"] if n["标题"] == "递交要求"][0]
    assert child["level"] == 2
    assert child["start_line"] == find_line("## 递交要求")
    assert child["end_line"] >= find_line("| 包号 | 内容 |")  # 表格落在其区段内（末节点到文件尾）

    assert meta["source"] == "招标文件.docx"
    assert len(meta["sha256"]) == 64
    assert meta["headings"] >= 3
    assert meta["warnings"] == []


def test_idempotent_same_hash(ws):
    _make_docx(ws / "招标文件.docx")
    first = parse_document.invoke({"path": "招标文件.docx"})
    assert first.startswith("[解析成功]")
    second = parse_document.invoke({"path": "招标文件.docx"})
    assert second.startswith("[解析跳过]")
    assert "sha256 一致" in second
    # 跳过同样带全量概况（确认门汇总无需再读 meta.json），但不放用法提示
    meta = json.loads(
        (_out_parse(ws) / "招标文件.docx" / "招标文件.docx.meta.json").read_text(encoding="utf-8")
    )
    assert meta["conversion"] in second
    assert "第一章 招标公告" in second  # 顶层章节清单
    assert "⚠️" not in second  # docx-native 无警示
    assert "下游精读" not in second
    assert "下游精读" in first


def test_changed_file_reconverts(ws):
    _make_docx(ws / "招标文件.docx")
    parse_document.invoke({"path": "招标文件.docx"})
    _make_docx(ws / "招标文件.docx", with_table=False)  # 内容变化 → hash 变
    r = parse_document.invoke({"path": "招标文件.docx"})
    assert r.startswith("[解析成功]")
    md = (_out_parse(ws) / "招标文件.docx" / "招标文件.docx.md").read_text(encoding="utf-8")
    assert "| 包号 |" not in md


def _make_pdf_with_toc(path):
    """带书签的多页 PDF：标题与正文同字号（字号启发式必然失效），结构只能靠书签。"""
    doc = pymupdf.open()
    for i, cn in enumerate("一二三", 1):
        page = doc.new_page()
        page.insert_text((72, 72), f"第{cn}章 测试章节{i}", fontsize=12, fontname="china-s")
        for j in range(6):
            page.insert_text(
                (72, 110 + j * 20),
                f"第{cn}章的正文内容第{j}段，写入足够内容以通过扫描件阈值校验。",
                fontsize=12,
                fontname="china-s",
            )
    doc.set_toc([[1, "第一章 测试章节1", 1], [1, "第二章 测试章节2", 2], [1, "第三章 测试章节3", 3]])
    doc.save(str(path))
    doc.close()


def test_pdf_bookmark_toc_preferred(ws):
    """有书签时结构来自书签（作者声明档），同字号下字号启发式本会全军覆没。"""
    _make_pdf_with_toc(ws / "书签文件.pdf")
    r = parse_document.invoke({"path": "书签文件.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "书签文件.pdf"
    md = (out_dir / "书签文件.pdf.md").read_text(encoding="utf-8")
    meta = json.loads((out_dir / "书签文件.pdf.meta.json").read_text(encoding="utf-8"))
    outline = json.loads((out_dir / "书签文件.pdf.outline.json").read_text(encoding="utf-8"))
    assert meta["conversion"] == "pdf-toc"
    assert meta["pages"] == 3
    assert [n["标题"] for n in outline] == ["第一章 测试章节1", "第二章 测试章节2", "第三章 测试章节3"]
    assert "# 第一章 测试章节1" in md
    assert not any("启发式" in w for w in meta["warnings"])


def _make_pdf_with_header_footer(path, npages=4):
    """每页带重复页眉（大字号，不剔除会成为伪标题）与页码的 PDF。"""
    doc = pymupdf.open()
    for i in range(1, npages + 1):
        page = doc.new_page()
        h = page.rect.height
        page.insert_text((72, 30), "第三章 投标人须知", fontsize=15, fontname="china-s")
        page.insert_text((72, h - 30), f"{i}/{npages}", fontsize=12, fontname="china-s")
        for j in range(5):
            page.insert_text(
                (72, 100 + j * 20),
                f"正文段落第{j}行，写入足够内容以通过扫描件阈值校验，内容编号{i}-{j}。",
                fontsize=12,
                fontname="china-s",
            )
    doc.save(str(path))
    doc.close()


def test_pdf_header_footer_stripped(ws):
    """跨页重复页眉与纯页码剔除：不出现在 markdown，也不产生每页伪标题。"""
    _make_pdf_with_header_footer(ws / "页眉文件.pdf")
    r = parse_document.invoke({"path": "页眉文件.pdf"})
    assert r.startswith("[解析成功]"), r

    md = (_out_parse(ws) / "页眉文件.pdf" / "页眉文件.pdf.md").read_text(encoding="utf-8")
    assert "投标人须知" not in md  # 页眉整行剔除
    assert "1/4" not in md and "2/4" not in md  # 页码剔除
    assert "正文段落第0行" in md  # 正文完好


def _make_unstyled_docx(path):
    """无 Word 样式、中文手打编号的 docx（真实标书常见形态）。"""
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("本项目为测试采购项目，现邀请合格投标人参加投标，项目编号TEST-2026-001。")
    doc.add_paragraph("一、投标须知")
    doc.add_paragraph("前附表是对投标人须知的具体补充，投标人应仔细阅读全部条款。")
    doc.add_paragraph("（一）递交要求")
    doc.add_paragraph("投标人应在截止时间前递交密封的投标文件，逾期不予受理，特此说明。")
    doc.save(str(path))


def test_docx_numbered_fallback(ws):
    """无样式文档兜底：中文编号识别为标题（启发式档，meta 带警示）。"""
    _make_unstyled_docx(ws / "无样式.docx")
    r = parse_document.invoke({"path": "无样式.docx"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "无样式.docx"
    md = (out_dir / "无样式.docx.md").read_text(encoding="utf-8")
    meta = json.loads((out_dir / "无样式.docx.meta.json").read_text(encoding="utf-8"))
    outline = json.loads((out_dir / "无样式.docx.outline.json").read_text(encoding="utf-8"))
    assert meta["conversion"] == "docx-numbered"
    assert any("启发式" in w for w in meta["warnings"])
    assert md.count("#") >= 3
    assert [n["标题"] for n in outline] == ["第一章 招标公告"]
    assert outline[0]["children"][0]["标题"] == "一、投标须知"
    assert outline[0]["children"][0]["children"][0]["标题"] == "（一）递交要求"


def test_txt_and_md_passthrough(ws):
    """txt/md 同规则解析：透传 + outline（md 的 ATX 标题进树；txt 无结构走 grep 警示）。"""
    (ws / "说明.txt").write_text("第一行内容。\n" + "正文内容若干。" * 30, encoding="utf-8")
    r = parse_document.invoke({"path": "说明.txt"})
    assert r.startswith("[解析成功]"), r
    meta = json.loads((_out_parse(ws) / "说明.txt" / "说明.txt.meta.json").read_text(encoding="utf-8"))
    assert meta["conversion"] == "txt-passthrough"
    assert meta["headings"] == 0
    assert any("grep" in w for w in meta["warnings"])

    (ws / "笔记.md").write_text("# 标题甲\n\n正文段落。\n\n## 子标题\n\n" + "内容行若干。\n" * 30, encoding="utf-8")
    r = parse_document.invoke({"path": "笔记.md"})
    assert r.startswith("[解析成功]"), r
    outline = json.loads((_out_parse(ws) / "笔记.md" / "笔记.md.outline.json").read_text(encoding="utf-8"))
    assert [n["标题"] for n in outline] == ["标题甲"]
    assert outline[0]["children"][0]["标题"] == "子标题"


def test_same_stem_docx_and_pdf_do_not_collide(ws):
    """回归：同名不同扩展（docx/pdf 双格式）的解析产物各有目录，互不覆盖。"""
    _make_docx(ws / "招标文件.docx")
    _make_pdf(ws / "招标文件.pdf")
    assert parse_document.invoke({"path": "招标文件.docx"}).startswith("[解析成功]")
    assert parse_document.invoke({"path": "招标文件.pdf"}).startswith("[解析成功]")

    base = _out_parse(ws)
    docx_md = (base / "招标文件.docx" / "招标文件.docx.md").read_text(encoding="utf-8")
    pdf_md = (base / "招标文件.pdf" / "招标文件.pdf.md").read_text(encoding="utf-8")
    assert "| 包号 |" in docx_md  # docx 产物完好，未被 pdf 版覆盖
    assert "| 包号 |" not in pdf_md
    meta_docx = json.loads((base / "招标文件.docx" / "招标文件.docx.meta.json").read_text(encoding="utf-8"))
    assert meta_docx["source"] == "招标文件.docx"
