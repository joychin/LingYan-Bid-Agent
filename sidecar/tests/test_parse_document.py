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
    # 第三个一级章：完整招标文件的多部分形态（docx-native 顶层 <3 会触发稀疏节选警示）
    doc.add_heading("第三章 评标办法", level=1)
    doc.add_paragraph("本项目采用综合评分法。")
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


def _make_docx_headings(path, n_top: int, subs_per_top: int = 2):
    """n_top 个一级标题 + 每个下设 subs_per_top 个二级标题（照抄真实稀疏档形态：
    戚墅堰所=2 个一级/37 个总标题的节选卷，顶层判据而非总标题判据）。"""
    doc = Document()
    filler = "本项目为测试采购项目，现邀请合格投标人参加投标，详见本章各项条款约定。" * 3
    for i in range(n_top):
        doc.add_heading(f"第{i + 1}部分 标题{i + 1}", level=1)
        doc.add_paragraph(filler)
        for j in range(subs_per_top):
            doc.add_heading(f"{i + 1}.{j + 1} 小节", level=2)
            doc.add_paragraph(filler)
    doc.save(str(path))


def test_docx_native_sparse_toplevel_warning(ws):
    """docx-native 但顶层章节 <3（二级标题丰富也没用）：警示疑似节选/结构不完整
    （2026-08-27 全量测试 T05/T06 真实文件——完整招标文件几乎必有多部分，
    实测语料完整标书顶层全部 ≥4；确认门据此提醒用户补传其他卷册）。"""
    f = ws / "稀疏顶层.docx"
    _make_docx_headings(f, n_top=2, subs_per_top=3)  # 总标题 8 个，顶层仍 2
    r = parse_document.invoke({"path": "稀疏顶层.docx"})
    assert r.startswith("[解析成功]")
    meta = json.loads((_out_parse(ws) / "稀疏顶层.docx" / "稀疏顶层.docx.meta.json").read_text())
    assert meta["conversion"] == "docx-native"
    assert meta["headings"] == 8  # 总标题不触发判据——顶层才触发
    assert any("顶层章节仅 2 个" in w and "结构可能不完整" in w for w in meta["warnings"])
    # 警示拼进返回文案（解析概况确认门复述的来源）
    assert "⚠️" in r and "结构可能不完整" in r


@pytest.mark.parametrize("n_top", [3, 5])
def test_docx_native_normal_toplevel_no_warning(ws, n_top):
    """正常顶层章数（≥3）不触发稀疏警示（3 为最小完整形态，保阈值不误伤）。"""
    f = ws / f"正常顶层{n_top}.docx"
    _make_docx_headings(f, n_top=n_top)
    r = parse_document.invoke({"path": f"正常顶层{n_top}.docx"})
    meta = json.loads((_out_parse(ws) / f"正常顶层{n_top}.docx" / f"正常顶层{n_top}.docx.meta.json").read_text())
    assert meta["conversion"] == "docx-native"
    assert meta["warnings"] == []
    assert "⚠️" not in r


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
    """运行时生成无书签 PDF（标题与正文同字号——结构只能靠文本信号识别）。

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
    page.insert_text((72, 320), "第三章 评标办法", fontsize=18, fontname="china-s")
    page.insert_text((72, 360), "本项目采用综合评分法，评分因素包括技术与商务两部分。", fontsize=12, fontname="china-s")
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

    # 标题（中文编号识别）与正文都进 markdown
    assert "# 第一章 招标公告" in md
    assert "# 第二章 投标人须知" in md
    assert "# 第三章 评标办法" in md
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
    assert meta["conversion"] == "pdf-numbered"  # 无书签无目录 → 中文编号兜底
    assert meta["headings"] >= 3
    assert "<!-- p:1 -->" in md  # 页码锚点
    assert any("中文编号" in w for w in meta["warnings"])


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
    """带书签的多页 PDF：标题与正文同字号，结构只能靠书签。"""
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
    """有书签时结构来自书签（作者声明档），同字号文本下编号兜底不参与。"""
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
    assert not any("警示用词" in w for w in meta["warnings"])  # pdf-toc 无档位警示


def _make_pdf_printed_toc(path):
    """无书签 PDF：结构来自第 2 页印刷目录（真实语料形态——孤立章节号行 +
    引导点线条目；正文标题也拆行）。封面巨字用于验证不再产生伪标题。"""
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), "测试项目采购文件", fontsize=24, fontname="china-s")
    p1.insert_text((72, 130), "（封面巨字在字号判级时代会全部变成伪标题）", fontsize=12, fontname="china-s")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "目 录", fontsize=16, fontname="china-s")
    p2.insert_text((72, 110), "第一章", fontsize=12, fontname="china-s")
    p2.insert_text((72, 128), "招标公告....................................1", fontsize=12, fontname="china-s")
    p2.insert_text((72, 160), "第二章", fontsize=12, fontname="china-s")
    p2.insert_text((72, 178), "投标人须知..................................3", fontsize=12, fontname="china-s")
    p2.insert_text((72, 210), "第三章 评标办法.............................5", fontsize=12, fontname="china-s")
    p3 = doc.new_page()
    p3.insert_text((72, 72), "第一章", fontsize=12, fontname="china-s")
    p3.insert_text((72, 90), "招标公告", fontsize=12, fontname="china-s")
    for j in range(6):
        p3.insert_text((72, 130 + j * 20), f"公告正文第{j}段，本项目为测试采购项目内容填充。", fontsize=12, fontname="china-s")
    p4 = doc.new_page()
    p4.insert_text((72, 72), "第二章", fontsize=12, fontname="china-s")
    p4.insert_text((72, 90), "投标人须知", fontsize=12, fontname="china-s")
    for j in range(6):
        p4.insert_text((72, 130 + j * 20), f"须知正文第{j}段，投标人应遵守各项规定要求。", fontsize=12, fontname="china-s")
    p5 = doc.new_page()
    p5.insert_text((72, 72), "第三章 评标办法", fontsize=12, fontname="china-s")
    for j in range(6):
        p5.insert_text((72, 110 + j * 20), f"评标正文第{j}段，综合评分法满分一百分整。", fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()


def test_pdf_printed_toc(ws):
    """无书签时解析文件自印的目录页，条目回正文定位（pdf-printed-toc 档）。"""
    _make_pdf_printed_toc(ws / "目录文件.pdf")
    r = parse_document.invoke({"path": "目录文件.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "目录文件.pdf"
    md = (out_dir / "目录文件.pdf.md").read_text(encoding="utf-8")
    outline = json.loads((out_dir / "目录文件.pdf.outline.json").read_text(encoding="utf-8"))
    meta = json.loads((out_dir / "目录文件.pdf.meta.json").read_text(encoding="utf-8"))

    assert meta["conversion"] == "pdf-printed-toc"
    assert [n["标题"] for n in outline] == ["第一章 招标公告", "第二章 投标人须知", "第三章 评标办法"]

    lines = md.splitlines()

    def find_line(text):
        return next(i for i, ln in enumerate(lines, 1) if ln.strip() == text)

    # 标题定位在正文页（第 3 页锚点之后），不是目录页
    assert find_line("# 第一章 招标公告") > find_line("<!-- p:3 -->")
    assert find_line("# 第三章 评标办法") > find_line("<!-- p:5 -->")
    # 封面巨字与目录页条目不再是伪标题
    assert "# 测试项目采购文件" not in md
    assert sum(1 for ln in lines if ln.startswith("# ")) == 3
    # 拆行标题被并成一个标题行（章节号行不再单独留在正文）
    assert "招标公告" in md


def _make_pdf_with_enumeration(path):
    """无书签无目录：正文含「本文件包括下述内容」式自枚举清单（连续 L1 编号行）。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "招标文件包括下述内容", fontsize=12, fontname="china-s")
    for i, name in enumerate(["商务文件", "技术文件", "附件"], 1):
        page.insert_text((72, 96 + i * 22), f"第{'一二三'[i - 1]}部分 {name}", fontsize=12, fontname="china-s")
    page.insert_text((72, 170), "以下为各部分正文内容。", fontsize=12, fontname="china-s")
    for cn, title in (("一", "投标邀请"), ("二", "投标人须知"), ("三", "评标办法")):
        y = 190 + "一二三".index(cn) * 90
        page.insert_text((72, y), f"第{cn}章 {title}", fontsize=12, fontname="china-s")
        for j in range(3):
            page.insert_text(
                (72, y + 24 + j * 20),
                f"第{cn}章正文第{j}段，填充足够内容避免扫描页误判。{'x' * 5}",
                fontsize=12,
                fontname="china-s",
            )
    doc.save(str(path))
    doc.close()


def test_pdf_numbered_skips_enumeration_list(ws):
    """自枚举清单（连续「第X部分」行）不识别为标题；真章节照常识别。"""
    _make_pdf_with_enumeration(ws / "清单文件.pdf")
    r = parse_document.invoke({"path": "清单文件.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "清单文件.pdf"
    md = (out_dir / "清单文件.pdf.md").read_text(encoding="utf-8")
    meta = json.loads((out_dir / "清单文件.pdf.meta.json").read_text(encoding="utf-8"))
    outline = json.loads((out_dir / "清单文件.pdf.outline.json").read_text(encoding="utf-8"))

    assert meta["conversion"] == "pdf-numbered"
    assert "# 第一部分" not in md
    assert [n["标题"] for n in outline] == ["第一章 投标邀请", "第二章 投标人须知", "第三章 评标办法"]


def _make_pdf_split_headings(path, chapters=3):
    """无书签无目录：正文标题拆行（孤立章节号一行 + 标题文字一行）。"""
    doc = pymupdf.open()
    titles = [("第一章", "招标公告"), ("第二章", "投标人须知"), ("第三章", "评标办法")]
    for prefix, title in titles[:chapters]:
        p = doc.new_page()
        p.insert_text((72, 72), prefix, fontsize=12, fontname="china-s")
        p.insert_text((72, 90), title, fontsize=12, fontname="china-s")
        for j in range(4):
            p.insert_text((72, 130 + j * 20), f"{title}正文第{j}段，本项目为测试采购项目。", fontsize=12, fontname="china-s")
    doc.save(str(path))
    doc.close()


def test_pdf_numbered_merges_split_heading(ws):
    """孤立章节号行与下一行标题并成一个完整标题（不再只留裸章节号）。"""
    _make_pdf_split_headings(ws / "拆行标题.pdf")
    r = parse_document.invoke({"path": "拆行标题.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "拆行标题.pdf"
    md = (out_dir / "拆行标题.pdf.md").read_text(encoding="utf-8")
    outline = json.loads((out_dir / "拆行标题.pdf.outline.json").read_text(encoding="utf-8"))
    meta = json.loads((out_dir / "拆行标题.pdf.meta.json").read_text(encoding="utf-8"))

    assert meta["conversion"] == "pdf-numbered"
    assert [n["标题"] for n in outline] == ["第一章 招标公告", "第二章 投标人须知", "第三章 评标办法"]
    # 标题行是合并后的完整标题，标题文字不再单独留在正文
    assert "# 第一章 招标公告" in md
    assert md.splitlines().count("招标公告") == 0


def test_pdf_plain_drops_subthreshold_marks(ws):
    """仅 1-2 个编号标题不过 pdf-numbered 门槛：marks 丢弃，md 不留标题行——
    档位声明（大纲不可用）与 outline 保持一致，不自相矛盾。"""
    _make_pdf_split_headings(ws / "两章文件.pdf", chapters=2)
    r = parse_document.invoke({"path": "两章文件.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "两章文件.pdf"
    md = (out_dir / "两章文件.pdf.md").read_text(encoding="utf-8")
    outline = json.loads((out_dir / "两章文件.pdf.outline.json").read_text(encoding="utf-8"))
    meta = json.loads((out_dir / "两章文件.pdf.meta.json").read_text(encoding="utf-8"))

    assert meta["conversion"] == "pdf-plain"
    assert outline == []
    assert not any(ln.startswith("# ") for ln in md.splitlines())
    assert any("未识别出章节结构" in w for w in meta["warnings"])


def _make_pdf_link_toc(path):
    """无书签 PDF：目录页条目带内部跳转链接（Word 导出的常见形态）——
    链接矩形即条目、目标即物理页。正文标题拆行（章节号与标题分两行）。"""
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), "测试项目采购文件", fontsize=24, fontname="china-s")
    p2 = doc.new_page()
    p2.insert_text((72, 60), "目 录", fontsize=16, fontname="china-s")
    entries = [("第一章 招标公告", 3), ("第二章 投标人须知", 4), ("第三章 评标办法", 5)]
    for title, target in entries:
        p2.insert_text((72, 100 + (target - 3) * 26), f"{title}..........{target - 2}", fontsize=12, fontname="china-s")
    # 先建齐全部正文页，再回填目录链接（insert_link 会解析目标页 xref）
    for title, _ in entries:
        page = doc.new_page()
        page.insert_text((72, 72), title.split()[0], fontsize=12, fontname="china-s")
        page.insert_text((72, 90), title.split()[1], fontsize=12, fontname="china-s")
        for j in range(5):
            page.insert_text(
                (72, 130 + j * 20),
                f"{title}正文第{j}段，填充足够内容避免扫描页误判。",
                fontsize=12,
                fontname="china-s",
            )
    # Page 对象在 new_page 后会失效，重新取回再插链接；矩形贴紧行高（真实
    # Word 导出的链接矩形即条目文本范围）
    p2 = doc[1]
    for i, (title, target) in enumerate(entries):
        y = 100 + i * 26
        p2.insert_link(
            {
                "kind": pymupdf.LINK_GOTO,
                "from": pymupdf.Rect(60, y - 2, 520, y + 10),
                "page": target - 1,
                "to": pymupdf.Point(0, 0),
            }
        )
    doc.save(str(path))
    doc.close()


def test_pdf_link_toc(ws):
    """目录条目自带 GOTO 链接 → pdf-link-toc；定位收窄到目标页，标题拆行合并。"""
    _make_pdf_link_toc(ws / "链接目录.pdf")
    r = parse_document.invoke({"path": "链接目录.pdf"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "链接目录.pdf"
    md = (out_dir / "链接目录.pdf.md").read_text(encoding="utf-8")
    outline = json.loads((out_dir / "链接目录.pdf.outline.json").read_text(encoding="utf-8"))
    meta = json.loads((out_dir / "链接目录.pdf.meta.json").read_text(encoding="utf-8"))

    assert meta["conversion"] == "pdf-link-toc"
    assert [n["标题"] for n in outline] == ["第一章 招标公告", "第二章 投标人须知", "第三章 评标办法"]

    lines = md.splitlines()

    def find_line(text):
        return next(i for i, ln in enumerate(lines, 1) if ln.strip() == text)

    # 标题定位在链接目标页（第 3/4/5 物理页锚点之后），不在目录页
    assert find_line("# 第一章 招标公告") > find_line("<!-- p:3 -->")
    assert find_line("# 第三章 评标办法") > find_line("<!-- p:5 -->")
    assert sum(1 for ln in lines if ln.startswith("# ")) == 3


def test_pdf_plain_when_no_structure(ws):
    """无书签/无目录/无编号 → pdf-plain，警示 grep 兜底。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "采购需求说明", fontsize=12, fontname="china-s")
    for j in range(8):
        page.insert_text((72, 100 + j * 20), f"需求{j}：系统应当支持相关功能特性与性能指标。", fontsize=12, fontname="china-s")
    doc.save(str(ws / "无结构.pdf"))
    doc.close()

    r = parse_document.invoke({"path": "无结构.pdf"})
    assert r.startswith("[解析成功]"), r
    meta = json.loads((_out_parse(ws) / "无结构.pdf" / "无结构.pdf.meta.json").read_text(encoding="utf-8"))
    outline = json.loads((_out_parse(ws) / "无结构.pdf" / "无结构.pdf.outline.json").read_text(encoding="utf-8"))
    assert meta["conversion"] == "pdf-plain"
    assert outline == []
    assert any("未识别出章节结构" in w for w in meta["warnings"])


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
    """无样式文档兜底：中文编号识别为标题（编号档，meta 带层级警示）。"""
    _make_unstyled_docx(ws / "无样式.docx")
    r = parse_document.invoke({"path": "无样式.docx"})
    assert r.startswith("[解析成功]"), r

    out_dir = _out_parse(ws) / "无样式.docx"
    md = (out_dir / "无样式.docx.md").read_text(encoding="utf-8")
    meta = json.loads((out_dir / "无样式.docx.meta.json").read_text(encoding="utf-8"))
    outline = json.loads((out_dir / "无样式.docx.outline.json").read_text(encoding="utf-8"))
    assert meta["conversion"] == "docx-numbered"
    assert any("中文编号" in w for w in meta["warnings"])
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
