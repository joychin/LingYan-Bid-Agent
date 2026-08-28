"""docx → markdown（python-docx 原生；无样式文档退中文编号启发式）。

自 tools/parse_document.py 迁入，逻辑不变；标题优先 Word 样式/outlineLvl（作者声明）。
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

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
    return ParseResult("\n".join(out), {"conversion": conversion, "tables": tables})
