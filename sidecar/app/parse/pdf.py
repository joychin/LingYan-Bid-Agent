"""pdf → markdown（pdfium 引擎；结构识别链：书签 → 印刷目录页 → 中文编号，页眉页脚剔除，页码锚点）。

**PyMuPDF 替换批（2026-09-14 完成）**：运行时依赖已从 PyMuPDF（AGPL）整体迁至
pypdfium2（Apache-2.0 / PDFium BSD-3）——商用许可自由。本文件持有**引擎无关**的
四级结构识别链与扫描页/表格/锚点语义；引擎原语见 pdf_pdfium.py，pdfium 底层收口
在 pdfium_kit.py（全局锁纪律：PDFium 官方禁多线程）。旧 mupdf 引擎已拆除（迁移
期差分门禁：档位/结构/渲染/性能五级对比通过后切换；已知差异=无框表格不识别
〔mupdf stream 策略，内容以文本保留〕与中西文空格合成等风格差异）。
对外 surface 不变：convert / render_page_png / insert_page_text，ParseResult.info
键 conversion/pages/tables/scanned_pages。

结构识别不使用字号（2026-08-28 实测证伪：政采 PDF 由 Word 导出，章标题字号常与
正文相同甚至更小，而封面全是巨字——「按字号判级」抓到的是封面碎片、漏掉的是真实
章节，17 份语料中 3/3 全灭）。兜底链改为：
1. 书签（pdf-toc，作者声明）；
2. 超链接目录（pdf-link-toc）：目录条目自带的内部跳转链接——链接矩形即条目标题、
   链接目标即物理页，Word 目录域生成的硬标记（实测语料 14/17 命中）；
3. 印刷目录页解析（pdf-printed-toc）：解析文件自己印的「目录」页条目，回正文
   逐条定位后标记标题——作者自报的结构，可靠性接近书签；
4. 中文编号正则（pdf-numbered）：「第X章/一、/（一）」印在原文行上，可回原文验证；
5. 都没有 → pdf-plain（无结构，警示下游改用 grep 定位）。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from . import ParseResult, register
from .numbering import LONE_PREFIX_RE, numbered_heading_level


# 引擎无关的文本块/表格形状：bbox 一律左上原点 (x0, y0, x1, y1)；lines 为逐行文本
# （行内 span 已拼接，含空行——过滤在消费点做，与旧 dict 形状语义一致）
class Block(NamedTuple):
    bbox: tuple[float, float, float, float]
    lines: list[str]


class Table(NamedTuple):
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]


_HF_BAND = 0.08  # 页眉/页脚条带：页高上下各 8%
_HF_REPEAT_RATIO = 0.25  # 条带文本跨页重复占比阈值（≥ max(3, 页数×比例) 判定页眉页脚）
# 归一化后的纯页码形态：1 / -1- / 第3页 / 3/15 / page3
_PAGE_NUM_RE = re.compile(r"^[-–—·.]*(?:第\d{1,4}页|\d{1,4}(?:/\d{1,4})?|page\d{1,4})[-–—·.]*$")

# 单页产出文本低于此值判扫描页（页码锚点不计入）——知识库视觉路由的依据
_SCANNED_PAGE_CHARS = 30

_PAGE_ANCHOR_RE = re.compile(r"^<!-- p:(\d+) -->$")

# ---- 印刷目录页解析 ----
# 目录条目：标题 + 3 个以上引导点/空格 + 可选页码（页码常被文本抽取截掉，不能强求）
_TOC_ENTRY_RE = re.compile(r"^(?P<title>.{1,70}?)[\s.·•…⋯*]{3,}(?P<page>\d{1,4})?\s*$")
# 孤立章节号前缀（「第一章」单独成行）见 numbering.LONE_PREFIX_RE（与编号兜底共用）
_TOC_HEADER_RE = re.compile(r"^\s*(目\s*[录次]|contents)\s*$", re.I)
# 单页内部跳转链接 ≥3 判导航页（Word 导出 PDF 的目录条目常自带 GOTO 链接；
# 正文页脚注/交叉引用链接零星——TDS 重建目录文章的密度启发式；与书签/印刷
# 目录通道的 ≥3 门槛一致）
_LINK_TOC_MIN = 3

# 标题候选行排除：表格/已有标题/页码锚点/视觉转写引用
_LINE_SKIP_PREFIXES = ("|", "#", ">", "<!--")


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


def _block_text(block: Block) -> str:
    return "".join(block.lines)


def _collect_repeated_bands(eng, doc) -> set[str]:
    """跨页重复的页眉/页脚文本（顶部/底部条带内，归一化后出现页数占比达标）。"""
    hits: Counter[str] = Counter()
    npages = 0
    for _pno, page in eng.iter_pages(doc):
        npages += 1
        h = eng.page_height(page)
        try:
            blocks = eng.text_blocks(page)
        except Exception:
            continue
        for b in blocks:
            if b.bbox[3] <= h * _HF_BAND or b.bbox[1] >= h * (1 - _HF_BAND):
                text = _norm_text(_block_text(b))
                if text:
                    hits[text] += 1
    if npages == 0:
        return set()
    threshold = max(3, int(npages * _HF_REPEAT_RATIO))
    return {t for t, c in hits.items() if c >= threshold}


def _is_hf_block(block: Block, page_height: float, drop: set[str]) -> bool:
    """页眉/页脚块判定：条带内 + 跨页重复 或 纯页码形态。"""
    if not (block.bbox[3] <= page_height * _HF_BAND or block.bbox[1] >= page_height * (1 - _HF_BAND)):
        return False
    text = _norm_text(_block_text(block))
    if not text:
        return False
    return text in drop or _PAGE_NUM_RE.fullmatch(text) is not None


def _toc_by_page(eng, doc) -> dict[int, list[tuple[int, str]]]:
    """有意义书签按目标页分组：{page: [(level, title), ...]}；不足 3 条返回空。

    匹配只在书签自己的目标页内进行——目录页列出的标题不会误命中。"""
    try:
        toc = eng.toc(doc)
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


def _block_to_md(block: Block) -> str:
    """把一个文本块转为 markdown（不判标题——结构识别全部后置于文本层）。"""
    if not any(ln.strip() for ln in block.lines):
        return ""
    return "\n".join(ln for ln in block.lines if ln.strip())


def _page_to_markdown(
    eng,
    page,
    drop: set[str],
    toc_titles: list[tuple[int, str]],
) -> tuple[list[str], int, int]:
    """单页文本块 + 表格按阅读顺序输出。返回 (行列表, 表格数, 书签命中数)。

    页眉/页脚块剔除；书签模式下标题由书签命中产生，未命中的书签目标页标题也保持
    正文——书签可信度靠整卷命中率把关（见 _convert_with）。"""
    blocks = [
        b
        for b in eng.text_blocks(page)
        if any(ln.strip() for ln in b.lines) and not _is_hf_block(b, eng.page_height(page), drop)
    ]
    blocks.sort(key=lambda b: (round(b.bbox[1], 1), b.bbox[0]))
    tables = eng.find_tables(page)
    table_idx_of_block: dict[int, int] = {}
    for i, b in enumerate(blocks):
        for ti, t in enumerate(tables):
            if _bboxes_overlap(b.bbox, t.bbox):
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
                md = _pipe_table(tables[ti].rows)
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
        text = _block_to_md(b)
        if text:
            out.append(text)
            out.append("")
    return out, len(tables), matched


def _clean_toc_title(raw: str) -> str:
    """链接矩形/目录行里的条目标题：压平换行，在第一段引导点线处截断。

    截断（而非仅去尾）是防渗漏：链接矩形偏高时会捞进下一行条目
    （「本章标题....12 下一章标题」），双栏目录同理——条目标题不会
    自带成串点线，第一段点线之后必然是页码或别的内容。"""
    text = " ".join(raw.split())
    m = re.search(r"[\s.·•…⋯*]{2,}\d{0,4}", text)
    if m:
        text = text[: m.start()]
    return text.strip()


def _link_toc_entries(eng, doc) -> tuple[list[tuple[str, int]], set[int]]:
    """从内链密集页提取目录条目：([(标题, 物理目标页 1 起)], 目录页集合)。

    目录页判定：单页 GOTO 链接 ≥ _LINK_TOC_MIN。条目标题取链接矩形覆盖的文本
    ——链接是作者（Word 目录域）生成的硬标记，不靠点线正则猜；链接目标直接
    给出条目所在物理页，回正文定位收窄到目标页内，正文里的自枚举清单
    （无链接、页面不符）天然不会误配。"""
    entries: list[tuple[str, int]] = []
    toc_pages: set[int] = set()
    for pno, page in eng.iter_pages(doc):
        try:
            links = eng.goto_links(doc, page)
        except Exception:
            continue
        if len(links) < _LINK_TOC_MIN:
            continue
        toc_pages.add(pno)
        items: list[tuple[float, str, int]] = []
        for rect, target in links:
            try:
                raw = eng.text_in_rect(page, rect)
            except Exception:
                continue
            title = _clean_toc_title(raw)
            # 纯数字/符号「标题」= 链接矩形盖住页码列的渗漏，不是条目
            if len(_norm_text(title)) >= 3 and re.search(r"[\u4e00-\u9fffA-Za-z]", title):
                items.append((rect[1], title, target))
        items.sort(key=lambda t: t[0])
        entries.extend((t, pg) for _, t, pg in items)
    return entries, toc_pages


def _locate_link_toc(
    lines: list[str],
    entries: list[tuple[str, int]],
    page_ranges: dict[int, tuple[int, int]],
    toc_pages: set[int],
) -> dict[int, tuple[int, str]]:
    """链接条目回正文定位：只在链接目标页的行区间内找标题（1~3 行合并窗口）。

    Word 目录域生成的链接指向精确；找不到的条目计入 miss，命中数不足
    （<max(3, 一半)）交印刷目录文本兜底。"""
    entry_norms = {_norm_text(t) for t, _ in entries if len(_norm_text(t)) >= 3}
    marks: dict[int, tuple[int, str]] = {}
    pos = 0
    for title, target in entries:
        tn = _norm_text(title)
        if len(tn) < 3 or target in toc_pages:
            continue
        rng = page_ranges.get(target)
        if not rng:
            continue
        for i in range(max(pos, rng[0] - 1), rng[1]):
            if not _joinable(lines[i]) or _enumeration_context(lines, i, entry_norms):
                continue
            joins = _join_windows(lines, i)
            hit_w = next((w for w, j in enumerate(joins, 1) if j == tn), None)
            if hit_w is None:
                hit_w = next((w for w, j in enumerate(joins, 1) if _prefix_ok(tn, j)), None)
            if hit_w is not None:
                lvl = numbered_heading_level(title) or 1
                marks[i] = (hit_w, f"{'#' * lvl} {title}")
                pos = i + hit_w
                break
    return marks


# ---- 印刷目录页解析与标题标记（后置于最终文本行）----


def _printed_toc_entries(eng, doc) -> dict[int, list[str]]:
    """扫描各页，识别「印刷目录页」并抽取条目标题：{页码: [标题...]}。

    目录页判定：有「目录/目次/CONTENTS」抬头且 ≥3 条目，或无抬头但 ≥5 条目
    （抬头本身常被拆行/拆字，条目数是更稳的信号）。条目 = 标题 + 引导点线 +
    可选页码；孤立章节号前缀行（「第一章」单独成行）与下一条目拼接。"""
    result: dict[int, list[str]] = {}
    for pno, page in eng.iter_pages(doc):
        try:
            raw_lines = [ln.strip() for ln in eng.page_text(page).splitlines() if ln.strip()]
        except Exception:
            continue
        entries: list[str] = []
        for i, ln in enumerate(raw_lines):
            m = _TOC_ENTRY_RE.match(ln)
            if not m:
                continue
            title = m.group("title").strip()
            if i > 0 and LONE_PREFIX_RE.fullmatch(raw_lines[i - 1]):
                title = f"{raw_lines[i - 1]} {title}"
            if len(_norm_text(title)) >= 3:
                entries.append(title)
        has_header = any(_TOC_HEADER_RE.match(ln) for ln in raw_lines)
        if (has_header and len(entries) >= 3) or len(entries) >= 5:
            result[pno] = entries
    return result


def _page_line_ranges(lines: list[str]) -> dict[int, tuple[int, int]]:
    """页码锚点 → 该页覆盖的 1 起行号区间。"""
    ranges: dict[int, tuple[int, int]] = {}
    cur, start = None, None
    for i, ln in enumerate(lines, 1):
        m = _PAGE_ANCHOR_RE.match(ln.strip())
        if m:
            if cur is not None:
                ranges[cur] = (start, i - 1)
            cur, start = int(m.group(1)), i
    if cur is not None:
        ranges[cur] = (start, len(lines))
    return ranges


def _joinable(ln: str) -> bool:
    return bool(ln.strip()) and not ln.strip().startswith(_LINE_SKIP_PREFIXES)


def _apply_marks(lines: list[str], marks: dict[int, tuple[int, str]]) -> list[str]:
    """按 {起始行号(0起): (窗口行数, 标题行)} 就地重写——窗口内原行并成一个标题行。"""
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = marks.get(i)
        if m:
            w, text = m
            out.append(text)
            i += w
        else:
            out.append(lines[i])
            i += 1
    return out


def _join_windows(lines: list[str], i: int, max_w: int = 3) -> list[str]:
    """从 i 起的 1~3 行合并视图（后行不可并入即停，防止跨段乱拼）。"""
    joins = [_norm_text(lines[i])]
    joined = joins[0]
    for w in range(2, max_w + 1):
        if i + w - 1 >= len(lines) or not _joinable(lines[i + w - 1]) or len(joined) > 80:
            break
        joined += _norm_text(lines[i + w - 1])
        joins.append(joined)
    return joins


def _locate_printed_toc(
    lines: list[str], entries: list[str], toc_lines: set[int]
) -> dict[int, tuple[int, str]]:
    """把目录条目回正文定位：单调向前、1~3 行合并窗口（标题常拆行）。

    候选行的紧邻行也是某条目标题（或孤立章节号）→ 判为「本文件包括下述内容」
    式自枚举清单，跳过——真实章节起点后跟的是正文不是一串标题。
    命中数不足（<max(3, 一半)）视为目录不可信，交编号兜底。"""
    entry_norms = {_norm_text(t) for t in entries if len(_norm_text(t)) >= 3}
    marks: dict[int, tuple[int, str]] = {}
    pos = 0
    for title in entries:
        tn = _norm_text(title)
        if len(tn) < 3:
            continue
        for i in range(pos, len(lines)):
            if (i + 1) in toc_lines or not _joinable(lines[i]):
                continue
            if _enumeration_context(lines, i, entry_norms):
                continue
            joins = _join_windows(lines, i)
            # 精确匹配优先（「第一部分」+「商务部分」拆行须并满才算），前缀包含兜底
            hit_w = next((w for w, j in enumerate(joins, 1) if j == tn), None)
            if hit_w is None:
                hit_w = next(
                    (w for w, j in enumerate(joins, 1) if _prefix_ok(tn, j)), None
                )
            if hit_w is not None:
                lvl = numbered_heading_level(title) or 1
                marks[i] = (hit_w, f"{'#' * lvl} {title}")
                pos = i + hit_w
                break
    return marks


def _enumeration_context(lines: list[str], i: int, entry_norms: set[str]) -> bool:
    """候选行最近的非空后行也是条目标题/孤立章节号 → 疑似自枚举清单。"""
    for k in (1, 2):
        if i + k >= len(lines):
            return False
        nxt = lines[i + k].strip()
        if not nxt:
            continue
        nn = _norm_text(nxt)
        return nn in entry_norms or bool(LONE_PREFIX_RE.fullmatch(nn))
    return False


def _prefix_ok(tn: str, joined: str) -> bool:
    # 标题在正文里可能更长（带副题）或更短（目录缩写）；≥4 字的前缀包含才认
    return (len(tn) >= 4 and joined.startswith(tn)) or (len(joined) >= 4 and tn.startswith(joined))


def _l1_run(lines: list[str], i: int) -> bool:
    """前后最近非空行（1~2 行内，空行可跨）也是 L1 编号 → 连续编号行
    （「招标文件包括下述内容」式自枚举清单）。

    真实章节之间必有正文，L1 直接相邻（仅隔空行）几乎必是清单；L2/L3
    （一、/（一））短节相邻常见，不做此守卫。由近及远查，隔一行正文的
    短章节不受影响。"""
    def near(idxs) -> bool:
        for k in idxs:
            if 0 <= k < len(lines):
                t = lines[k].strip()
                if t:
                    return numbered_heading_level(t) == 1
        return False

    return near((i - 1, i - 2)) or near((i + 1, i + 2))


def _apply_numbered(lines: list[str], skip_lines: set[int]) -> dict[int, tuple[int, str]]:
    """中文编号兜底：对文本行（跳过目录页行）识别「第X章/一、/（一）」标题。

    两种拆行形态都合并：孤立章节号行（「第一章」单独成行）并入下一行标题——
    它本身已匹配 L1，须在判定后补并（下一行是正文段落时并入结果不过约束、
    退回单行章节号）；单行不成编号时并入后 1~2 行（提取碎片「第」+「一章 …」）。
    合并结果仍受行长 ≤60 与句读排除约束（见 numbering.py）。"""
    marks: dict[int, tuple[int, str]] = {}
    i = 0
    while i < len(lines):
        if (i + 1) in skip_lines or not _joinable(lines[i]):
            i += 1
            continue
        raw = lines[i].strip()
        lvl = numbered_heading_level(raw)
        w = 1
        joined = raw
        if lvl == 1 and LONE_PREFIX_RE.fullmatch(raw):
            if i + 1 < len(lines) and _joinable(lines[i + 1]):
                cand = f"{raw} {lines[i + 1].strip()}"
                if numbered_heading_level(cand):
                    joined, w = cand, 2
        else:
            while not lvl and w < 3 and i + w < len(lines):
                nxt = lines[i + w]
                if not _joinable(nxt):
                    break
                joined += nxt.strip()
                w += 1
                lvl = numbered_heading_level(joined)
                if lvl:
                    break
        if lvl:
            if lvl == 1 and _l1_run(lines, i):
                i += 1
                continue
            marks[i] = (w, f"{'#' * lvl} {joined}")
            i += w
            continue
        i += 1
    return marks


def _convert_with(eng, path: Path) -> ParseResult:
    """PDF → (markdown, 信息)。每页前插页码锚点 <!-- p:N -->；结构识别链
    书签 → 印刷目录页 → 中文编号 → 无结构（详见模块 docstring）。

    info.scanned_pages 记录产出文本过少的页码（知识库视觉路由依据；纯文本 PDF 为空）。"""
    with eng.open(path) as doc:
        pages = eng.n_pages(doc)
        drop = _collect_repeated_bands(eng, doc)
        toc = _toc_by_page(eng, doc)
        total_toc = sum(len(v) for v in toc.values())

        def render(use_toc: bool) -> tuple[list[str], int, int, list[int]]:
            out: list[str] = []
            tables = 0
            matched = 0
            scanned_pages: list[int] = []
            for pno, page in eng.iter_pages(doc):
                out.append(f"<!-- p:{pno} -->")
                md, n_tables, n_matched = _page_to_markdown(
                    eng, page, drop, toc.get(pno, []) if use_toc else []
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
        conversion = "pdf-toc"
        if use_toc and matched < total_toc * 0.5:
            out, tables, _, scanned_pages = render(use_toc=False)
            use_toc = False
        if not use_toc:
            # 后置于最终文本行的结构识别：超链接目录 → 印刷目录页 → 中文编号
            lines = [ln for el in out for ln in el.splitlines()]
            ranges = _page_line_ranges(lines)
            link_entries, link_toc_pages = _link_toc_entries(eng, doc)
            marks = _locate_link_toc(lines, link_entries, ranges, link_toc_pages)
            if len(marks) >= max(3, math.ceil(len(link_entries) * 0.5)):
                conversion = "pdf-link-toc"
            else:
                printed = _printed_toc_entries(eng, doc)
                toc_lines: set[int] = set()
                for pno in link_toc_pages | set(printed):
                    if pno in ranges:
                        toc_lines.update(range(ranges[pno][0], ranges[pno][1] + 1))
                all_entries = [t for pno in sorted(printed) for t in printed[pno]]
                marks = _locate_printed_toc(lines, all_entries, toc_lines)
                if len(marks) >= max(3, math.ceil(len(all_entries) * 0.5)):
                    conversion = "pdf-printed-toc"
                else:
                    marks = _apply_numbered(lines, toc_lines)
                    if len(marks) >= 3:
                        conversion = "pdf-numbered"
                    else:
                        # 零星编号行多为误配，丢弃——保持不变式「pdf-plain ⟹ md
                        # 无标题行」：一边警示大纲不可用一边留标题，档位声明与
                        # outline 会自相矛盾
                        marks = {}
                        conversion = "pdf-plain"
            lines = _apply_marks(lines, marks)
            out = lines
        return ParseResult(
            "\n".join(out).strip(),
            {
                "conversion": conversion,
                "pages": pages,
                "tables": tables,
                "scanned_pages": scanned_pages,
            },
        )


@register([".pdf"])
def convert(path: Path) -> ParseResult:
    from . import pdf_pdfium

    return _convert_with(pdf_pdfium.ENGINE, path)


def render_page_png(path: Path, page_no: int, out_path: Path, dpi: int = 150) -> Path:
    """渲染单页为 png（视觉模型读图输入）。page_no 1 起。"""
    from . import pdfium_kit

    return pdfium_kit.render_page_png(path, page_no, out_path, dpi)


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
