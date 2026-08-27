"""检索切段：按 outline 节点切段（一段一行进 FTS）。

切法：level<=2 的标题节点各成一段（顶层章 + 二级节，粒度适合 agent 拿行号区间
read_file）；无结构文档按固定行窗口兜底。page_start 取段内第一个 <!-- p:N --> 锚点。
段内容存 jieba 预分词文本（写入侧）；原文摘要由调用方按行号区间回 md 提取。
"""

from __future__ import annotations

import re

_PAGE_ANCHOR = re.compile(r"<!-- p:(\d+) -->")

_LEVEL_MAX = 2  # 切段的最大标题层级（1=顶层章、2=二级节）
_WINDOW_LINES = 80  # 无结构文档的窗口行数


def _page_of(lines: list[str]) -> int | None:
    for ln in lines:
        m = _PAGE_ANCHOR.search(ln)
        if m:
            return int(m.group(1))
    return None


def segments_from(md_text: str, outline: list[dict]) -> list[dict]:
    """md 全文 + outline 树 → 检索段列表。

    段 = 节点自身行区间（start_line..end_line，含子节点——嵌套重复换取上下文完整，
    FTS 段不是精读边界，行号区间才是）。每个段带 section_path（标题链）。
    """
    lines = md_text.splitlines()
    flat: list[tuple[int, int, int, list[str]]] = []  # (level, start, end, 标题链)

    def walk(nodes: list[dict], path: list[str]) -> None:
        for n in nodes:
            title = n.get("标题", "")
            chain = [*path, title]
            if n.get("level", 99) <= _LEVEL_MAX:
                flat.append((n["level"], n["start_line"], n["end_line"], chain))
            walk(n.get("children", []), chain)

    walk(outline, [])

    segs: list[dict] = []
    if flat:
        for _lvl, start, end, chain in flat:
            body = "\n".join(lines[start - 1 : end])
            if not body.strip():
                continue
            segs.append({
                "section_path": " / ".join(chain),
                "line_start": start,
                "line_end": end,
                "page_start": _page_of(lines[start - 1 : end]),
                "raw": body,
            })
        return segs

    # 无结构兜底：固定行窗口
    for i in range(0, len(lines), _WINDOW_LINES):
        chunk = lines[i : i + _WINDOW_LINES]
        if not any(ln.strip() for ln in chunk):
            continue
        segs.append({
            "section_path": None,
            "line_start": i + 1,
            "line_end": i + len(chunk),
            "page_start": _page_of(chunk),
            "raw": "\n".join(chunk),
        })
    return segs
