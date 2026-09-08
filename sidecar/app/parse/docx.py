"""docx → markdown（python-docx 原生；无样式文档退中文编号启发式）。

自 tools/parse_document.py 迁入，逻辑不变；标题优先 Word 样式/outlineLvl（作者声明）。
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from . import ParseResult, register
from .numbering import numbered_heading_level


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
    """中文编号启发式（仅无样式文档兜底）：实现移至 numbering.py（与 pdf 兜底共用）。"""
    return numbered_heading_level(text)


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


@register([".docx"])
def convert(path: Path) -> ParseResult:
    """docx → (markdown, 信息)。标题优先 Word 样式/outlineLvl（作者声明）；
    一个样式标题都没有时对正文段落跑中文编号启发式（conversion=docx-numbered）。

    meta.element_lines：body 子元素全序索引 → 最终 md 行区间（1-based 闭区间）
    的映射，供 docx 元素级注入按行号区间回找元素（素材块勾选锚定的是 md 行号）。
    空行折叠会删行，故折叠时同步维护原始行 → 输出行换算，映射以最终 md 为准。
    """
    doc = Document(str(path))
    lines: list[str] = []
    plain_at: list[tuple[int, str]] = []  # (行索引, 文本)——兜底二次标记用
    el_lines: list[list[int]] = []  # [元素全序索引, 起行, 止行]（lines 坐标，闭区间）
    styled = 0
    tables = 0
    body = doc.element.body
    for el_idx, child in enumerate(body.iterchildren()):
        tag = child.tag.split("}")[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph

            p = Paragraph(child, doc)
            text = p.text.strip()
            lvl = _heading_level(p)
            start = len(lines) + 1
            if lvl > 0:
                styled += 1
                lines.append("#" * min(lvl, 6) + " " + text)
            else:
                plain_at.append((len(lines), text))
                if text:
                    lines.append(("- " + text) if _is_numbered(p) else text)
                elif child.findall(".//" + qn("a:blip")) or child.findall(
                    ".//{urn:schemas-microsoft-com:vml}imagedata"
                ):
                    # 纯图片段占位行：行非空才不会被空行折叠吃出 element_lines
                    # （否则该图永远无法元素级注入=静默丢图，2026-09-08 实证）；
                    # 勾选界面与 md 预览亦可见此处有图（v:imagedata=VML 老图）
                    lines.append("![](图片)")
                else:
                    lines.append("")
            el_lines.append([el_idx, start, len(lines)])
        elif tag == "tbl":
            from docx.table import Table

            t = Table(child, doc)
            start = len(lines) + 1
            lines.append("")
            lines.append(_table_to_md(t))
            lines.append("")
            tables += 1
            el_lines.append([el_idx, start, len(lines)])
    # 内嵌图片计数（v3：docx 图片不再静默丢弃——计数进解析概况，抽取属增强工序）
    image_count = len(doc.part.package.image_parts) if hasattr(doc.part, "package") else 0
    conversion = "docx-native"
    if styled == 0:
        for idx, text in plain_at:
            lvl = _numbered_heading_level(text)
            if lvl > 0:
                lines[idx] = "#" * lvl + " " + text
        conversion = "docx-numbered"
    out, blank = [], 0
    orig_to_out: dict[int, int] = {}  # 空行折叠后的行号换算（被折叠删除的行无映射）
    for i, ln in enumerate(lines, 1):
        if ln == "":
            blank += 1
            if blank <= 2:
                orig_to_out[i] = len(out) + 1
                out.append(ln)
        else:
            blank = 0
            orig_to_out[i] = len(out) + 1
            out.append(ln)
    element_lines = []
    for el_idx, s, e in el_lines:
        kept = [orig_to_out[i] for i in range(s, e + 1) if i in orig_to_out]
        if kept:
            element_lines.append([el_idx, min(kept), max(kept)])
    return ParseResult(
        "\n".join(out),
        {"conversion": conversion, "tables": tables, "image_count": image_count, "element_lines": element_lines},
    )
