"""确定性文档解析工具：.docx/.pdf/.txt/.md → Markdown + 带行号区间的标题大纲。

结构识别按可信度分档（meta.conversion 记录，下游引用出处时按档位决定是否署章节名）：
- docx-native / pdf-toc：作者声明的结构（Word 标题样式 / PDF 书签树）——可信；
- docx-numbered / pdf-fontsize：启发式（无样式文档的中文编号识别 / 无书签 PDF 的字号
  判级）——可能有误，产物带警示，出处不署章节名。
pdf 侧另有跨页重复的页眉页脚与纯页码剔除、每页页码锚点 <!-- p:N -->（出处可引页码）。
txt/md 透传（md 保留 ATX 标题进 outline；txt 无结构走 grep 兜底警示）。
outline 记录每个标题的行号区间（大文件按区段精读的定位索引）、meta 记录来源 hash/
顶层章节/质量警示，同 hash 幂等跳过、扫描件质量兜底（不静默产垃圾）。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from docx import Document
from langchain_core.tools import tool

from .. import runctx
from ..artifact_store import task_files_dir, task_out_dir
from ..config import workspace_dir

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

_MIN_TEXT_CHARS = 100  # 低于此值视为转换失败（扫描件/损坏文件）

_HF_BAND = 0.08  # 页眉/页脚条带：页高上下各 8%
_HF_REPEAT_RATIO = 0.25  # 条带文本跨页重复占比阈值（≥ max(3, 页数×比例) 判定页眉页脚）
# 归一化后的纯页码形态：1 / -1- / 第3页 / 3/15 / page3
_PAGE_NUM_RE = re.compile(r"^[-–—·.]*(?:第\d{1,4}页|\d{1,4}(?:/\d{1,4})?|page\d{1,4})[-–—·.]*$")

_CN_NUM = "一二三四五六七八九十百千零〇两"
_HEADING_L1_RE = re.compile(rf"^第[{_CN_NUM}0-9]{{1,8}}[章节篇部分]")
_HEADING_L2_RE = re.compile(rf"^[{_CN_NUM}]{{1,6}}、")
_HEADING_L3_RE = re.compile(rf"^[（(][{_CN_NUM}0-9]{{1,8}}[)）]")


# ---------------------------------------------------------------------------
# docx → markdown（python-docx 原生；无样式文档退中文编号启发式）
# ---------------------------------------------------------------------------
def _heading_level(p) -> int:
    style_name = (p.style.name if p.style else "") or ""
    for prefix in ("Heading ", "标题 ", "heading "):
        if style_name.startswith(prefix):
            try:
                return int(style_name[len(prefix):].strip())
            except ValueError:
                pass
    try:
        pPr = p._p.pPr
        if pPr is not None and pPr.outlineLvl is not None:
            return int(pPr.outlineLvl.val) + 1
    except Exception:
        pass
    return 0


def _is_numbered(p) -> bool:
    try:
        pPr = p._p.pPr
        if pPr is not None and pPr.numPr is not None:
            return True
    except Exception:
        pass
    return False


def _numbered_heading_level(text: str) -> int:
    """中文编号启发式（仅无样式文档兜底）：第X章→L1 / 一、→L2 /（一）→L3。

    行长 ≤60 且不以句读结尾——排除长句与正文段落。"""
    if len(text) > 60 or text.endswith(("。", "；", "，", "：", ",", ";")):
        return 0
    if _HEADING_L1_RE.match(text):
        return 1
    if _HEADING_L2_RE.match(text):
        return 2
    if _HEADING_L3_RE.match(text):
        return 3
    return 0


def _cell_text(cell) -> str:
    txt = cell.text.replace("\n", " ").strip()
    return txt if txt else " "


def _table_to_md(table) -> str:
    rows = table.rows
    if not rows:
        return ""
    out = []
    header = [_cell_text(c) for c in rows[0].cells]
    out.append("| " + " | ".join(header) + " |")
    out.append("| " + " | ".join(["---"] * len(header)) + " |")
    for row in rows[1:]:
        out.append("| " + " | ".join(_cell_text(c) for c in row.cells) + " |")
    return "\n".join(out)


def _docx_to_markdown(path: Path) -> tuple[str, dict]:
    """docx → (markdown, 信息)。标题优先 Word 样式/outlineLvl（作者声明）；
    一个样式标题都没有时对正文段落跑中文编号启发式（conversion=docx-numbered）。"""
    doc = Document(str(path))
    lines: list[str] = []
    plain_at: list[tuple[int, str]] = []  # (行索引, 文本)——兜底二次标记用
    styled = 0
    tables = 0
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph

            p = Paragraph(child, doc)
            text = p.text.strip()
            lvl = _heading_level(p)
            if lvl > 0:
                styled += 1
                lines.append("#" * min(lvl, 6) + " " + text)
            else:
                plain_at.append((len(lines), text))
                lines.append(("- " + text) if _is_numbered(p) else (text if text else ""))
        elif tag == "tbl":
            from docx.table import Table

            t = Table(child, doc)
            lines.append("")
            lines.append(_table_to_md(t))
            lines.append("")
            tables += 1
    conversion = "docx-native"
    if styled == 0:
        for idx, text in plain_at:
            lvl = _numbered_heading_level(text)
            if lvl > 0:
                lines[idx] = "#" * lvl + " " + text
        conversion = "docx-numbered"
    out, blank = [], 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank <= 2:
                out.append(ln)
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out), {"conversion": conversion, "tables": tables}


# ---------------------------------------------------------------------------
# pdf → markdown（PyMuPDF；书签优先，字号启发式兜底，页眉页脚剔除，页码锚点）
# ---------------------------------------------------------------------------
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
    目标页标题也保持正文——书签可信度靠整卷命中率把关（见 _pdf_to_markdown）。"""
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


def _pdf_to_markdown(path: Path) -> tuple[str, dict]:
    """PDF → (markdown, 信息)。每页前插页码锚点 <!-- p:N -->；结构识别书签优先，
    整卷书签命中率 <50% 判书签不可靠、回退字号启发式。"""
    doc = pymupdf.open(str(path))
    try:
        pages = doc.page_count
        body_size = _estimate_body_size(doc)
        drop = _collect_repeated_bands(doc)
        toc = _toc_by_page(doc)
        total_toc = sum(len(v) for v in toc.values())

        def render(use_toc: bool) -> tuple[list[str], int, int]:
            out: list[str] = []
            tables = 0
            matched = 0
            for pno, page in enumerate(doc, 1):
                out.append(f"<!-- p:{pno} -->")
                md, n_tables, n_matched = _page_to_markdown(
                    page, body_size, drop, toc.get(pno, []) if use_toc else []
                )
                tables += n_tables
                matched += n_matched
                out.extend(md)
            return out, tables, matched

        use_toc = total_toc >= 3
        out, tables, matched = render(use_toc)
        if use_toc and matched < total_toc * 0.5:
            out, tables, _ = render(use_toc=False)
            use_toc = False
        conversion = "pdf-toc" if use_toc else "pdf-fontsize"
        return "\n".join(out).strip(), {
            "conversion": conversion,
            "pages": pages,
            "tables": tables,
            "body_size": body_size,
        }
    finally:
        doc.close()


def _read_text_auto(p: Path) -> str:
    """txt/md 读取：utf-8 优先，中文遗留编码（gb18030 超集）兜底。"""
    raw = p.read_bytes()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 带行号区间的标题大纲
# ---------------------------------------------------------------------------
def _outline_with_lines(md_text: str) -> list[dict]:
    """标题树，每个节点带 start_line/end_line（1 起行号，含）。

    节点区段 = 本标题行到下一个 level<=自身 的标题行之前；末节点到文件尾。
    """
    lines = md_text.splitlines()
    headings: list[tuple[int, int, str]] = []  # (行号, level, 标题)
    for i, line in enumerate(lines, 1):
        m = _MD_HEADING_RE.match(line)
        if m and m.group(2).strip():
            headings.append((i, len(m.group(1)), m.group(2).strip()))
    total = len(lines)
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(-1, root)]
    for idx, (ln, lvl, title) in enumerate(headings):
        end = total
        for ln2, lvl2, _ in headings[idx + 1:]:
            if lvl2 <= lvl:
                end = ln2 - 1
                break
        node = {"标题": title, "level": lvl, "start_line": ln, "end_line": end, "children": []}
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((lvl, node["children"]))
    return root


def _count_nodes(tree: list[dict]) -> int:
    return sum(1 + _count_nodes(n.get("children", [])) for n in tree)


# ---------------------------------------------------------------------------
# 工具主体
# ---------------------------------------------------------------------------
def _resolve_ws_path(p: str) -> Path:
    """路径 containment：解析（含符号链接）后必须落在 workspace 内。

    相对路径按 workspace 根解析；根下找不到时回退当前任务的 files/ 按文件名找
    （模型常直接说裸文件名，上传文件住在 <task>/files/）。
    """
    root = workspace_dir().resolve()
    cand = Path(p).expanduser()
    if not cand.is_absolute():
        cand = root / cand
    resolved = cand.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"路径越界：只允许 workspace 内的文件（{root}），收到 {p}")
    if not resolved.exists() and not Path(p).is_absolute():
        ctx = runctx.current_run()
        if ctx and ctx.task_id:
            alt = (task_files_dir(ctx.task_id) / Path(p).name).resolve()
            if alt.is_relative_to(root):
                resolved = alt
    return resolved


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _summary_lines(head: str, name: str, rel: Path, meta: dict, *, usage_hint: bool) -> list[str]:
    """成功/跳过两路共用的返回文案组装；meta 形状即落盘 meta.json（旧文件缺键防御取值）。

    跳过路径也带全量概况，调用方（确认门汇总）无需再读 meta.json。
    """
    pages_part = f" / {meta['pages']} 页" if "pages" in meta else ""
    top = meta.get("top_level") or []
    n_top = meta.get("top_level_titles", len(top))
    top_show = "；".join(top) + ("…" if n_top > len(top) else "")
    parts = [
        head,
        f"Markdown {meta.get('chars', '?')} 字符 / 标题 {meta.get('headings', '?')} 个"
        f" / 顶层章节 {n_top} 个{pages_part} / 表格 {meta.get('tables', '?')} 个；"
        f"解析路径：{meta.get('conversion', '?')}",
        f"顶层章节：{top_show}" if top_show else "顶层章节：（无——启发式未识别出结构）",
    ]
    if usage_hint:
        parts.append(
            f"下游精读时才需要：先读 {rel}/{name}.outline.json 按行号定位章节，"
            "再用 read_file(file_path=…, offset=起始行, limit=行数) 读对应区段"
        )
    parts.extend(f"⚠️ {w}" for w in meta.get("warnings") or [])
    return parts


@tool
def parse_document(path: str) -> str:
    """把文档（.docx/.pdf/.txt/.md）转换为 Markdown，并生成带行号区间的标题大纲与元信息。

    产物写入当前任务工作台的 out/parse/<文件名>/ 下三个文件（文件名=含扩展名的完整
    文件名——任务内同名即同文件，docx/pdf 同名不同扩展的产物互不覆盖）：
    - <文件名>.md：全文 Markdown（标题层级/表格 pipe 化；PDF 每页带 <!-- p:N --> 页码锚点）
    - <文件名>.outline.json：标题树，每个节点带 start_line/end_line 行号区间
    - <文件名>.meta.json：来源文件/sha256/解析路径(conversion)/顶层章节/质量警示

    结构识别分档（meta.conversion）：docx-native/pdf-toc=作者声明的结构（Word 样式/
    PDF 书签），可信；docx-numbered/pdf-fontsize=启发式（编号识别/字号判级），可能有误。
    同一文件内容未变（hash 一致）时重复调用会跳过重转（跳过同样返回全量概况，
    调用方无需读 meta.json 补数字）。下游分析技能精读时才用 outline.json 按行号
    定位区段；document-parse 阶段不需要读它。
    """
    try:
        ctx = runctx.current_run()
        task_id = ctx.task_id if ctx else None
        if not task_id:
            return "[解析失败] 缺少任务上下文：解析产物归属当前任务的 out/ 目录，请在任务会话中执行"
        src = _resolve_ws_path(path)
        if not src.is_file():
            return f"[解析失败] 文件不存在：{path}"
        digest = _sha256(src)
        # 目录与产物文件名都用完整文件名（含扩展名）：同名不同扩展（docx/pdf 双格式）
        # 的解析产物各有各的目录，不互相覆盖
        out_dir = task_out_dir(task_id) / "parse" / src.name
        md_path = out_dir / f"{src.name}.md"
        outline_path = out_dir / f"{src.name}.outline.json"
        meta_path = out_dir / f"{src.name}.meta.json"

        # 幂等：同 hash 且产物齐备则跳过
        if meta_path.is_file() and md_path.is_file() and outline_path.is_file():
            try:
                old = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                old = {}
            if old.get("sha256") == digest:
                rel = out_dir.relative_to(workspace_dir())
                return "\n".join(
                    _summary_lines(
                        f"[解析跳过] {src.name} 内容未变化（sha256 一致），沿用已有产物：{rel}/",
                        src.name,
                        rel,
                        old,
                        usage_hint=False,
                    )
                )

        ext = src.suffix.lower()
        if ext == ".docx":
            md_text, info = _docx_to_markdown(src)
        elif ext == ".pdf":
            md_text, info = _pdf_to_markdown(src)
        elif ext in (".txt", ".md"):
            md_text = _read_text_auto(src)
            info = {"conversion": "txt-passthrough" if ext == ".txt" else "md-passthrough", "tables": 0}
        else:
            raise ValueError(
                f"不支持的输入格式：{ext}（支持 .docx / .pdf / .txt / .md；.doc 请用 Word 另存为 .docx 后再上传）"
            )
        if len(md_text.strip()) < _MIN_TEXT_CHARS:
            raise ValueError(
                f"转换结果为空或极短（{len(md_text.strip())} 字符）。"
                "若输入为 PDF，疑似扫描件（图片型 PDF），当前不支持 OCR；请提供 .docx 或文本型 PDF"
            )
        outline = _outline_with_lines(md_text)
        n_headings = _count_nodes(outline)
        top_titles = [n["标题"] for n in outline]

        warnings: list[str] = []
        if n_headings == 0:
            warnings.append("未识别到任何标题层级，大纲导航不可用（改用 grep 关键词定位）")
        if info["conversion"] in ("docx-numbered", "pdf-fontsize"):
            warnings.append("结构来自启发式识别（无样式/无书签），层级可能不完整或有误")

        out_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")
        outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = {
            "source": src.name,
            "sha256": digest,
            "bytes": src.stat().st_size,
            "conversion": info["conversion"],
            "chars": len(md_text),
            "headings": n_headings,
            "top_level_titles": len(top_titles),
            "top_level": top_titles[:12],
            "tables": info.get("tables", 0),
            "warnings": warnings,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if "pages" in info:
            meta["pages"] = info["pages"]
        if "body_size" in info:
            meta["body_size"] = info["body_size"]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        rel = out_dir.relative_to(workspace_dir())
        return "\n".join(
            _summary_lines(f"[解析成功] {src.name} → {rel}/", src.name, rel, meta, usage_hint=True)
        )
    except ValueError as e:
        return f"[解析失败] {e}"
    except Exception as e:  # 损坏文件等意外
        return f"[解析失败] {type(e).__name__}: {e}"
