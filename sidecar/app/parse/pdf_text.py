"""文本块结构（PyMuPDF get_text("dict") 的 pdfium 平替，替换批·批 2a）。

行层走 pdfium C 级分段（pdfium_kit.text_rects：count_rects/get_rect 官方缓存
优化路径），同视觉行多矩形（字体/样式切换会拆段）按「垂直重叠 ≥50% 较小行高且
水平间距 ≤20pt」合并；块层纯 Python 聚合：阅读序连续行按「垂直间隙 ≤0.75×当前
行高 + 横向重叠 ≥30% 较窄行」聚块。参考实现：pdfminer.six 的 layout 分组思路
（MIT）——不读 MuPDF 源码。坐标：输出一律视觉左上原点（旋转页经 kit.rect_to_tl
映射）。阈值参数由差分语料回归校准（_BLOCK_GAP_FACTOR 等）。
"""

from __future__ import annotations

from . import pdfium_kit
from .pdf import Block

_LINE_MERGE_OVERLAP = 0.5   # 垂直重叠占较小行高比例下限（同视觉行判定）
_LINE_GAP_MAX = 34.0        # 同行相邻分段水平间距上限（pt；证书类「兹 证 明」宽字距
                            # ~32pt 需并入，分栏栏距通常 ≥40pt 不受影响）
_BLOCK_GAP_FACTOR = 0.75    # 行间垂直间隙超过当前行高的此倍数 → 换块（段落间隙）
_BLOCK_X_OVERLAP = 0.3      # 行横向重叠占较窄行比例下限（列连续性）


def _visual_lines(items: list[tuple[tuple[float, float, float, float], str]]) -> list[tuple[tuple[float, float, float, float], str]]:
    """文本矩形 → 视觉行（同一行的多个分段按 x 序拼接文本）。

    两段式（顺序无关——中文两端对齐会逐字定位，矩形 y 微差使 (y,x) 排序在行内
    乱序，不能依赖处理顺序）：先按 y 排序做**纵向聚行**（与当前行 y 范围重叠
    ≥阈值的矩形传递并入，范围随成员扩张），行内再按 x 序拼接、大水平间隙
    （分栏/表格列）切段。"""
    items.sort(key=lambda it: (it[0][1], it[0][0]))
    rows: list[dict] = []
    for rect, text in items:
        y0, y1 = rect[1], rect[3]
        if rows:
            ry0, ry1 = rows[-1]["y0"], rows[-1]["y1"]
            h_min = min(ry1 - ry0, y1 - y0)
            overlap = min(ry1, y1) - max(ry0, y0)
            if h_min > 0 and overlap >= _LINE_MERGE_OVERLAP * h_min:
                rows[-1]["items"].append((rect, text))
                rows[-1]["y0"] = min(ry0, y0)
                rows[-1]["y1"] = max(ry1, y1)
                continue
        rows.append({"y0": y0, "y1": y1, "items": [(rect, text)]})
    out: list[tuple[tuple[float, float, float, float], str]] = []
    for row in rows:
        parts = sorted(row["items"], key=lambda it: it[0][0])  # x 序
        segs: list[list] = [[parts[0]]]
        for rect, text in parts[1:]:
            gap = rect[0] - segs[-1][-1][0][2]
            if gap > _LINE_GAP_MAX:  # 分栏/表格列断开
                segs.append([(rect, text)])
            else:
                segs[-1].append((rect, text))
        for seg in segs:
            bbox = (
                min(r[0] for r, _ in seg), min(r[1] for r, _ in seg),
                max(r[2] for r, _ in seg), max(r[3] for r, _ in seg),
            )
            # 段间不加空格、段首尾空白剥除（pdfium 分段文本自带边缘空格）——与旧
            # span 拼接口径一致（CJK 主语料无词间空格）
            out.append((bbox, _join_overlapped(seg).strip()))
    out.sort(key=lambda it: (round(it[0][1], 1), it[0][0]))
    return out


def _join_overlapped(seg: list) -> str:
    """拼接行内分段；x 区间重叠的相邻段先做重叠文本裁剪。

    pdfium 的相邻分段可在边界处各含对方的字符（墨迹盒交叠的跑被重复计入，
    实证形态 '…Firefo'+'fox…'→应为 '…Firefox…'）：x 重叠 ≥1pt 时找前段后缀
    与后段前缀的最长重合（≥2 字）裁掉，无重合原样拼接。"""
    texts = [t.strip() for _, t in seg]
    for i in range(1, len(texts)):
        if seg[i][0][0] >= seg[i - 1][0][2] - 1.0:
            continue  # x 无重叠，直接拼
        a, b = texts[i - 1], texts[i]
        best = 0
        for k in range(min(len(a), len(b), 24), 1, -1):
            if a.endswith(b[:k]):
                best = k
                break
        if best:
            texts[i] = b[best:]
    return "".join(texts)


def _blocks(lines: list[tuple[tuple[float, float, float, float], str]]) -> list[Block]:
    """视觉行（阅读序）→ 块（段落近似）。

    阅读序由 (y, x) 排序保证；块边界=段落间隙（垂直跳变）或列切换（横向
    无重叠）。标题与正文往往字号不同→行高突变，间隙判据自然分块。"""
    blocks: list[dict] = []
    for bbox, text in lines:
        x0, y0, x1, y1 = bbox
        cur_h = max(y1 - y0, 1.0)
        if blocks:
            b = blocks[-1]
            bx0, by0, bx1, by1 = b["bbox"]
            gap = y0 - by1
            w_min = min(x1 - x0, bx1 - bx0)
            x_overlap = min(x1, bx1) - max(x0, bx0)
            if gap <= _BLOCK_GAP_FACTOR * cur_h and (w_min <= 0 or x_overlap >= _BLOCK_X_OVERLAP * w_min):
                b["lines"].append(text)
                b["bbox"] = (min(bx0, x0), by0, max(bx1, x1), max(by1, y1))
                continue
        blocks.append({"bbox": (x0, y0, x1, y1), "lines": [text]})
    return [Block(tuple(b["bbox"]), b["lines"]) for b in blocks]


def text_blocks(page) -> list[Block]:
    """单页文本块（视觉左上原点；行内分段已拼接，空行过滤在消费点）。"""
    items = [(pdfium_kit.rect_to_tl(page, r), t) for r, t in pdfium_kit.text_rects(page)]
    return _blocks(_visual_lines(items))


def page_text(page) -> str:
    """整页纯文本（行以 \\n 分隔——印刷目录页扫描用）。"""
    return pdfium_kit.page_full_text(page)
