"""pdfium_kit 单测 + 并发确定性哨兵（PyMuPDF 替换批·批 1）。

哨兵背景：PDFium 官方声明不可多线程（跨文档也不允许并发调用）——kit 用全局锁
串行化全部调用；哨兵钉住的是「锁保护下并发 = 串行结果逐字节一致」，不只是不崩
（对齐 fs_guard 并发编辑哨兵的证伪式写法）。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PIL import Image

from app.parse import pdfium_kit
from tests import pdfgen


def _make_two_page(path) -> Path:
    """第 1 页带 GOTO 链接（指向第 2 页），第 2 页纯文本。"""
    p = pdfgen.Pdf(path, width=400, height=600)
    p.text(60, 80, "PAGE1 目录", size=12)
    p.link(60, 76, 380, 92, "dst2")
    p.show_page()
    p.text(60, 80, "PAGE2 正文", size=12)
    p.dest("dst2")
    return p.save()


def test_open_page_count_size(tmp_path):
    f = _make_two_page(tmp_path / "a.pdf")
    assert pdfium_kit.page_count(f) == 2
    with pdfium_kit.open_document(f) as doc:
        page = pdfium_kit.get_page(doc, 0)
        assert pdfium_kit.page_size(page) == (400.0, 600.0)


def test_missing_file_raises(tmp_path):
    with pytest.raises(Exception):
        pdfium_kit.page_count(tmp_path / "不存在.pdf")


def test_blank_page_detection(tmp_path):
    p = pdfgen.Pdf(tmp_path / "blank.pdf", width=400, height=600)
    p.text(60, 80, "有字", size=12)
    p.show_page()
    p.show_page()  # 第 2 页空白（reportlab 末尾未关闭的页会在 save 时丢弃，须显式翻页）
    f = p.save()
    with pdfium_kit.open_document(f) as doc:
        assert not pdfium_kit.page_is_blank(pdfium_kit.get_page(doc, 0))
        assert pdfium_kit.page_is_blank(pdfium_kit.get_page(doc, 1))


def test_render_png_dimensions(tmp_path):
    f = _make_two_page(tmp_path / "a.pdf")
    out = tmp_path / "p1.png"
    assert pdfium_kit.render_page_png(f, 1, out, dpi=150) == out
    with Image.open(out) as im:
        assert abs(im.size[0] - 400 * 150 / 72) <= 2
        assert abs(im.size[1] - 600 * 150 / 72) <= 2


def test_render_page_out_of_range(tmp_path):
    f = _make_two_page(tmp_path / "a.pdf")
    with pytest.raises(Exception):
        pdfium_kit.render_page_png(f, 3, tmp_path / "x.png")


def test_goto_links_coordinates_and_target(tmp_path):
    """链接矩形翻转为左上原点、目标页 1 起。"""
    f = _make_two_page(tmp_path / "a.pdf")
    with pdfium_kit.open_document(f) as doc:
        links = pdfium_kit.goto_links(doc, pdfium_kit.get_page(doc, 0))
        assert links == [((60.0, 76.0, 380.0, 92.0), 2)]
        # 非链接页为零
        assert pdfium_kit.goto_links(doc, pdfium_kit.get_page(doc, 1)) == []


def test_text_in_rect(tmp_path):
    f = _make_two_page(tmp_path / "a.pdf")
    with pdfium_kit.open_document(f) as doc:
        text = pdfium_kit.text_in_rect(pdfium_kit.get_page(doc, 1), (40, 60, 380, 110))
    assert "PAGE2" in text


def test_concurrent_render_and_count_deterministic(tmp_path):
    """全局锁下 8 线程×不同文档 + 4 线程×同文档并发渲染/计数：结果与串行逐字节一致。"""
    files = []
    for i in range(6):
        p = pdfgen.Pdf(tmp_path / f"doc{i}.pdf", width=300 + i * 10, height=400)
        for pg in range(3):
            p.text(50, 60, f"DOC{i} PAGE{pg}", size=12)
            p.text(50, 90, "并发确定性内容行，用于并发渲染比对。" * 2, size=10)
            p.show_page()
        files.append(p.save())

    def render_bytes(f: Path, page: int, tag: str) -> bytes:
        out = tmp_path / f"{tag}.png"
        pdfium_kit.render_page_png(f, page, out, dpi=96)
        return out.read_bytes()

    # 串行基线（渲染字节 + 页数）
    base_render = {i: render_bytes(f, 2, f"base{i}") for i, f in enumerate(files)}
    base_count = [pdfium_kit.page_count(f) for f in files]

    # 12 个任务：8 个不同 (文档,页) 渲染 + 4 个同文档渲染，Barrier 同时起跑
    jobs = [(i % 6, 2) for i in range(8)] + [(0, 1)] * 4
    results: list[bytes | None] = [None] * len(jobs)
    counts: list[int | None] = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def run(k: int):
        barrier.wait()
        i, page = jobs[k]
        results[k] = render_bytes(files[i], page, f"w{k}")
        counts[k] = pdfium_kit.page_count(files[i])

    threads = [threading.Thread(target=run, args=(k,)) for k in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for k, (i, page) in enumerate(jobs):
        expect = base_render[i] if page == 2 else render_bytes(files[i], 1, f"chk{k}")
        assert results[k] == expect, f"job{k} 并发渲染与串行结果不一致"
        assert counts[k] == base_count[i]
    assert not list(tmp_path.glob("*.tmp"))  # 无残件


def test_no_pymupdf_imports_in_app():
    """许可守卫（PyMuPDF 替换批·批 3）：app/ 生产代码零 pymupdf/fitz 导入。

    AGPL 依赖不得静默回流（tests/ 的 reportlab 夹具不受此限）。"""
    import re as _re

    import app as app_pkg

    root = Path(app_pkg.__file__).parent
    pat = _re.compile(
        r"^\s*import\s+(?:[A-Za-z_][\w.]*\s*,\s*)*(?:pymupdf|fitz)\b"
        r"|^\s*from\s+(?:pymupdf|fitz)\b"
    )
    hits = [
        f"{p.relative_to(root)}:{i}"
        for p in root.rglob("*.py")
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pat.match(ln)
    ]
    assert not hits, f"pymupdf/fitz 回流: {hits}"
