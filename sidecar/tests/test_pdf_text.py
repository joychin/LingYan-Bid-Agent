"""pdf_text 结构层单测（PyMuPDF 替换批·批 2a）：视觉行合并 / 块聚合 / 旋转页坐标 / 整页文本。"""

from __future__ import annotations

from app.parse import pdf_text
from app.parse.pdf_pdfium import ENGINE
from tests import pdfgen


def _blocks_of(path, page_no=1):
    with ENGINE.open(path) as doc:
        _pno, page = next(p for p in ENGINE.iter_pages(doc) if p[0] == page_no)
        return pdf_text.text_blocks(page), ENGINE.page_height(page)


def test_same_line_segments_merge(tmp_path):
    """同行近邻分段（字体/样式切换拆段形态）并成一个视觉行。"""
    p = pdfgen.Pdf(tmp_path / "a.pdf", width=595, height=842)
    p.text(50, 80, "左半", size=12)
    p.text(90, 80, "右半", size=12)  # 间距 ~15pt < _LINE_GAP_MAX
    f = p.save()
    blocks, _h = _blocks_of(f)
    assert len(blocks) == 1
    assert blocks[0].lines == ["左半右半"]


def test_distant_columns_not_merged(tmp_path):
    """同 y 远距（分栏形态）不并成一行。"""
    p = pdfgen.Pdf(tmp_path / "cols.pdf", width=595, height=842)
    p.text(50, 80, "左栏内容", size=12)
    p.text(350, 80, "右栏内容", size=12)
    blocks, _h = _blocks_of(p.save())
    assert [ln for b in blocks for ln in b.lines] == ["左栏内容", "右栏内容"]


def test_paragraph_groups_and_gap_splits(tmp_path):
    """近行距聚一段、大间隙分段。"""
    p = pdfgen.Pdf(tmp_path / "para.pdf", width=595, height=842)
    for i in range(3):
        p.text(50, 80 + i * 18, f"段落第{i}行内容", size=12)
    p.text(50, 200, "隔了一段的新内容", size=12)
    blocks, _h = _blocks_of(p.save())
    assert len(blocks) == 2
    assert blocks[0].lines == [f"段落第{i}行内容" for i in range(3)]
    assert blocks[1].lines == ["隔了一段的新内容"]


def test_rotated_page_visual_coords(tmp_path):
    """/Rotate 90：块坐标落在视觉页（600×400）内、页高=视觉高、文本可抽取。"""
    f = pdfgen.hand_pdf(tmp_path / "rot.pdf", page_extra="/Rotate 90")
    blocks, h = _blocks_of(f)
    assert h == 400.0  # 视觉高（mediabox 600 已交换）
    assert blocks and any("ROTATED PAGE TEXT" in ln for b in blocks for ln in b.lines)
    for b in blocks:
        x0, y0, x1, y1 = b.bbox
        assert 0 <= x0 < x1 <= 600 and 0 <= y0 < y1 <= 400


def test_page_text_lines(tmp_path):
    """整页文本按 \\n 分行、无 \\r 残留。"""
    p = pdfgen.Pdf(tmp_path / "pt.pdf", width=595, height=842)
    p.text(50, 80, "第一行", size=12)
    p.text(50, 110, "第二行", size=12)
    f = p.save()
    with ENGINE.open(f) as doc:
        _pno, page = next(ENGINE.iter_pages(doc))
        text = pdf_text.page_text(page)
    assert "\r" not in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines == ["第一行", "第二行"]
