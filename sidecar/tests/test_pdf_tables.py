"""pdf_tables 有框表格识别单测（PyMuPDF 替换批·批 2a）。"""

from __future__ import annotations

from app.parse import pdf_tables
from app.parse.pdf import _convert_with
from app.parse.pdf_pdfium import ENGINE
from tests import pdfgen


def _grid(p: pdfgen.Pdf, x: float, y_top: float, cols: float, rows: float, tw=300, th=120,
          skip_v: int | None = None):
    """画网格表（左上原点定位；skip_v=列序 → 该竖线只缺顶行段，制造行内缺格）。"""
    c = p.c
    H = p.h
    c.setLineWidth(0.75)
    c.rect(x, H - y_top - th, tw, th)
    for i in range(1, int(cols)):
        vx = x + tw * i / cols
        if skip_v == i:
            c.line(vx, H - y_top - th, vx, H - y_top - th / rows)  # 只画下段（顶行缺）
        else:
            c.line(vx, H - y_top - th, vx, H - y_top)
    for j in range(1, int(rows)):
        c.line(x, H - y_top - th * j / rows, x + tw, H - y_top - th * j / rows)


def _tables_of(path):
    with ENGINE.open(path) as doc:
        _pno, page = next(ENGINE.iter_pages(doc))
        return pdf_tables.find_tables(page)


def test_grid_3x3_extract(tmp_path):
    """3×3 网格：1 张表、行序自上而下、格文本正确。"""
    p = pdfgen.Pdf(tmp_path / "grid.pdf")
    _grid(p, 72, 200, cols=3, rows=3)
    for r in range(3):
        for col in range(3):
            p.text(72 + 300 * col / 3 + 10, 200 + 120 * r / 3 + 14, f"行{r}列{col}", size=10)
    tables = _tables_of(p.save())
    assert len(tables) == 1
    rows = tables[0].rows
    assert ["".join(r) for r in rows] == ["".join(f"行{r}列{c}" for c in range(3)) for r in range(3)]
    x0, y0, x1, y1 = tables[0].bbox
    assert x0 < 72.5 and x1 > 370 and y0 < 200.5 and y1 > 318  # 覆盖表格区域（左上原点）


def test_two_tables_detected_separately(tmp_path):
    """两个不相邻网格 → 两张表。"""
    p = pdfgen.Pdf(tmp_path / "two.pdf")
    _grid(p, 72, 600, cols=2, rows=2, tw=200, th=80)
    _grid(p, 72, 200, cols=2, rows=2, tw=200, th=80)
    assert len(_tables_of(p.save())) == 2


def test_text_only_no_table(tmp_path):
    """纯文本页零表格。"""
    p = pdfgen.Pdf(tmp_path / "plain.pdf")
    p.text(50, 80, "没有边框线的正文内容若干行。", size=12)
    p.text(50, 110, "第二行正文内容。", size=12)
    assert _tables_of(p.save()) == []


def test_missing_edge_makes_colspan(tmp_path):
    """缺一段竖线 → 左侧成跨列合并格（宽格闭合、并取两格文本）、原格位补 ""。"""
    p = pdfgen.Pdf(tmp_path / "hole.pdf")
    _grid(p, 72, 200, cols=3, rows=3, skip_v=1)
    for r in range(3):
        for col in range(3):
            p.text(72 + 300 * col / 3 + 10, 200 + 120 * r / 3 + 14, f"C{r}{col}", size=10)
    tables = _tables_of(p.save())
    assert len(tables) == 1
    rows = tables[0].rows
    # 顶行：左两列并成宽格（取 C00 C01 文本）、中列位补 ""、右列原样；其余行完整
    assert rows[0][0].split() == ["C00", "C01"] and rows[0][1] == "" and rows[0][2] == "C02"
    assert ["".join(r) for r in rows[1:]] == ["C10C11C12", "C20C21C22"]


def test_decorative_vector_page_guard(tmp_path):
    """装饰性矢量页（>80 簇边线，证书底纹形态）不判表。"""
    p = pdfgen.Pdf(tmp_path / "deco.pdf")
    c = p.c
    c.setLineWidth(0.5)
    for i in range(90):  # 横竖各 90 条稀疏线
        c.line(20, 20 + i * 8, 575, 20 + i * 8)
        c.line(20 + i * 6, 20, 20 + i * 6, 820)
    assert _tables_of(p.save()) == []


def test_table_reaches_convert_md(tmp_path):
    """端到端：表格页经 pdfium 引擎 convert 落成 markdown 管道表。"""
    p = pdfgen.Pdf(tmp_path / "conv.pdf")
    _grid(p, 72, 200, cols=2, rows=2, tw=240, th=80)
    p.text(80, 214, "包号", size=10)
    p.text(200, 214, "内容", size=10)
    p.text(80, 254, "包1", size=10)
    p.text(200, 254, "软件开发", size=10)
    res = _convert_with(ENGINE, p.save())
    assert res.info["tables"] == 1
    assert "| 包号 | 内容 |" in res.md
    assert "| 包1 | 软件开发 |" in res.md
