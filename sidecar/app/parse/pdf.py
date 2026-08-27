"""pdf → markdown（PyMuPDF；书签优先，字号启发式兜底，页眉页脚剔除，页码锚点）。

自 tools/parse_document.py 迁入，文本管线逻辑不变；知识库场景新增三个原子能力：
- meta.scanned_pages：每页产出文本量分类（混合/扫描 PDF 的视觉路由依据）
- render_page_png：单页渲染为 png（喂视觉模型）
- insert_page_text：把视觉转写插回对应页码锚点后（混合 PDF 拼接）
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from . import ParseResult, register

_HF_BAND = 0.08  # 页眉/页脚条带：页高上下各 8%
_HF_REPEAT_RATIO = 0.25  # 条带文本跨页重复占比阈值（≥ max(3, 页数×比例) 判定页眉页脚）
# 归一化后的纯页码形态：1 / -1- / 第3页 / 3/15 / page3
_PAGE_NUM_RE = re.compile(r"^[-–—·.]*(?:第\d{1,4}页|\d{1,4}(?:/\d{1,4})?|page\d{1,4})[-–—·.]*$")

# 单页产出文本低于此值判扫描页（页码锚点不计入）——知识库视觉路由的依据
_SCANNED_PAGE_CHARS = 30

_PAGE_ANCHOR_RE = re.compile(r"^<!-- p:(\d+) -->$")


def _estimate_body_size(doc: pymupdf.Document) -> float:
    """统计全文字号（按字符数加权），返回出现最多的字号作为正文基准。"""
    sizes: Counter[float] = Counter()
    for page in doc:
        try:
            d = page.get_text("dict")
        except Exception:
            continue
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "") or ""
                    if t.strip():
                        sizes[round(span.get("size", 0) or 0, 1)] += len(t)
    if not sizes:
        return 12.0
    return max(sizes, key=sizes.get)


def _bboxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], tol: float = 1.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 - tol and bx0 < ax1 - tol and ay0 < by1 - tol and by0 < ay1 - tol


def _pipe_table(rows: list[list[str]]) -> str:
    """把 find_tables 的 extract() 结果（二维单元格列表）pipe 化为 markdown 表格。"""
    rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in rows]
    if not rows or not any(r for r in rows):
        return ""
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * ncols) + " |"]
    out.extend("| " + " | ".join(r) + " |" for r in rows[1:])
    return "\n".join(out)


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _block_text(block: dict) -> str:
    parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            t = span.get("text", "") or ""
            if t:
                parts.append(t)
    return "".join(parts)


def _collect_repeated_bands(doc: pymupdf.Document) -> set[str]:
    """跨页重复的页眉/页脚文本（顶部/底部条带内，归一化后出现页数占比达标）。"""
    hits: Counter[str] = Counter()
    npages = 0
    for page in doc:
        npages += 1
        h = page.rect.height
        try:
            blocks = page.get_text("dict").get("blocks", [])
        except Exception:
            continue
        for b in blocks:
            if b.get("type") != 0:
                continue
            if b["bbox"][3] <= h * _HF_BAND or b["bbox"][1] >= h * (1 - _HF_BAND):
                text = _norm_text(_block_text(b))
                if text:
                    hits[text] += 1
    if npages == 0:
        return set()
    threshold = max(3, int(npages * _HF_REPEAT_RATIO))
    return {t for t, c in hits.items() if c >= threshold}


def _is_hf_block(block: dict, page: pymupdf.Page, drop: set[str]) -> bool:
    """页眉/页脚块判定：条带内 + 跨页重复 或 纯页码形态。"""
    h = page.rect.height
    if not (block["bbox"][3] <= h * _HF_BAND or block["bbox"][1] >= h * (1 - _HF_BAND)):
        return False
    text = _norm_text(_block_text(block))
    if not text:
        return False
    return text in drop or _PAGE_NUM_RE.fullmatch(text) is not None


def _toc_by_page(doc: pymupdf.Document) -> dict[int, list[tuple[int, str]]]:
    """有意义书签按目标页分组：{page: [(level, title), ...]}；不足 3 条返回空。

    匹配只在书签自己的目标页内进行——目录页列出的标题不会误命中。"""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        return {}
    entries = [
        (min(lvl, 6), title.strip(), page)
        for lvl, title, page in toc
        if title.strip() and len(title.strip()) >= 2 and page >= 1
    ]
    if len(entries) < 3:
        return {}
    by_page: dict[int, list[tuple[int, str]]] = {}
    for lvl, title, page in entries:
        by_page.setdefault(page, []).append((lvl, title))
    return by_page


def _match_toc(block_norm: str, titles: list[tuple[int, str]], consumed: set[str]) -> tuple[int, str] | None:
    if not block_norm or len(block_norm) > 80:
        return None
    for lvl, title in titles:
        tn = _norm_text(title)
        if not tn or tn in consumed:
            continue
        if block_norm == tn or block_norm.startswith(tn):
            return lvl, title
    return None


def _block_to_md(block: dict, body_size: float, allow_heading: bool = True) -> str:
    """把一个文本块转为 markdown；单行/两行且字号显著大于正文基准时按标题分级。"""
    lines = block.get("lines", [])
    if not lines:
        return ""
    line_texts: list[str] = []
    max_size = 0.0
    for line in lines:
        parts = []
        for span in line.get("spans", []):
            t = span.get("text", "") or ""
            if t:
                parts.append(t)
                max_size = max(max_size, span.get("size", 0) or 0)
        line_texts.append("".join(parts))
    if not any(lt.strip() for lt in line_texts):
        return ""
    if allow_heading and len(lines) <= 2 and max_size >= body_size * 1.15:
        if max_size >= body_size * 1.5:
            prefix = "#"
        elif max_size >= body_size * 1.3:
            prefix = "##"
        else:
            prefix = "###"
        title = " ".join(lt.strip() for lt in line_texts if lt.strip())
        return f"{prefix} {title}"
    return "\n".join(lt for lt in line_texts if lt.strip())


def _page_to_markdown(
    page: pymupdf.Page,
    body_size: float,
    drop: set[str],
    toc_titles: list[tuple[int, str]],
) -> tuple[list[str], int, int]:
    """单页文本块 + 表格按阅读顺序输出。返回 (行列表, 表格数, 书签命中数)。

    页眉/页脚块剔除；书签模式下标题由书签命中产生（字号判级关闭），未命中的书签
    目标页标题也保持正文——书签可信度靠整卷命中率把关（见 convert）。"""
    blocks = page.get_text("dict").get("blocks", [])
    blocks = [
        b
        for b in blocks
        if b.get("type") == 0
        and any(s.get("text", "").strip() for line in b.get("lines", []) for s in line.get("spans", []))
        and not _is_hf_block(b, page, drop)
    ]
    blocks.sort(key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    table_idx_of_block: dict[int, int] = {}
    for i, b in enumerate(blocks):
        for ti, t in enumerate(tables):
            if _bboxes_overlap(b["bbox"], t.bbox):
                table_idx_of_block[i] = ti
                break
    out: list[str] = []
    emitted_tables: set[int] = set()
    consumed_titles: set[str] = set()
    matched = 0
    for i, b in enumerate(blocks):
        ti = table_idx_of_block.get(i)
        if ti is not None:
            if ti not in emitted_tables:
                emitted_tables.add(ti)
                md = _pipe_table(tables[ti].extract())
                if md:
                    out.append(md)
                    out.append("")
            continue
        if toc_titles:
            hit = _match_toc(_norm_text(_block_text(b)), toc_titles, consumed_titles)
            if hit is not None:
                lvl, title = hit
                consumed_titles.add(_norm_text(title))
                matched += 1
                out.append("#" * lvl + " " + title)
                out.append("")
                continue
            text = _block_to_md(b, body_size, allow_heading=False)
        else:
            text = _block_to_md(b, body_size)
        if text:
            out.append(text)
            out.append("")
    return out, len(tables), matched


@register([".pdf"])
def convert(path: Path) -> ParseResult:
    """PDF → (markdown, 信息)。每页前插页码锚点 <!-- p:N -->；结构识别书签优先，
    整卷书签命中率 <50% 判书签不可靠、回退字号启发式。

    info.scanned_pages 记录产出文本过少的页码（知识库视觉路由依据；纯文本 PDF 为空）。"""
    doc = pymupdf.open(str(path))
    try:
        pages = doc.page_count
        body_size = _estimate_body_size(doc)
        drop = _collect_repeated_bands(doc)
        toc = _toc_by_page(doc)
        total_toc = sum(len(v) for v in toc.values())

        def render(use_toc: bool) -> tuple[list[str], int, int, list[int]]:
            out: list[str] = []
            tables = 0
            matched = 0
            scanned_pages: list[int] = []
            for pno, page in enumerate(doc, 1):
                out.append(f"<!-- p:{pno} -->")
                md, n_tables, n_matched = _page_to_markdown(
                    page, body_size, drop, toc.get(pno, []) if use_toc else []
                )
                # 该页实际产出字符（剔除锚点与空白）——扫描页判定
                page_chars = len("".join(x.strip() for x in md))
                if page_chars < _SCANNED_PAGE_CHARS:
                    scanned_pages.append(pno)
                tables += n_tables
                matched += n_matched
                out.extend(md)
            return out, tables, matched, scanned_pages

        use_toc = total_toc >= 3
        out, tables, matched, scanned_pages = render(use_toc)
        if use_toc and matched < total_toc * 0.5:
            out, tables, _, scanned_pages = render(use_toc=False)
            use_toc = False
        conversion = "pdf-toc" if use_toc else "pdf-fontsize"
        return ParseResult(
            "\n".join(out).strip(),
            {
                "conversion": conversion,
                "pages": pages,
                "tables": tables,
                "body_size": body_size,
                "scanned_pages": scanned_pages,
            },
        )
    finally:
        doc.close()


def render_page_png(path: Path, page_no: int, out_path: Path, dpi: int = 150) -> Path:
    """渲染单页为 png（视觉模型读图输入）。page_no 1 起。"""
    doc = pymupdf.open(str(path))
    try:
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=dpi)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
        return out_path
    finally:
        doc.close()


def insert_page_text(md: str, page_no: int, text: str) -> str:
    """把文本插到 `<!-- p:N -->` 锚点行之后（混合 PDF 把视觉转写拼回原位）。

    无该页锚点时追加到文末。插入块首行标记来源，下游引用可识别转写档位。
    """
    lines = md.splitlines()
    anchor = f"<!-- p:{page_no} -->"
    block = [f"> [视觉模型转写 p:{page_no}]", *[ln for ln in text.strip().splitlines() if ln.strip()], ""]
    for i, ln in enumerate(lines):
        if _PAGE_ANCHOR_RE.match(ln.strip()) and int(_PAGE_ANCHOR_RE.match(ln.strip()).group(1)) == page_no:
            return "\n".join([*lines[: i + 1], *block, *lines[i + 1 :]])
    return "\n".join([*lines, anchor, *block])
