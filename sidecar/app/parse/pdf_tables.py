"""有框表格识别（PyMuPDF find_tables 的 pdfium 平替，替换批·批 2a）。

pdfplumber（MIT）同款算法路线：路径对象 bbox → 横竖边线（退化维判定）→ 容差
合并共线段 → 网格交点 → 闭合格 → 连通簇（≥2×2 格）判表 → 网格 extract
（get_text_bounded 内缩取文）。只识别有框线表格（政采招标文件的表格形态）；
漏检降级为正文文本块（非灾难）。明确不做无框表格策略。不读 MuPDF 源码。

边线只用 bbox 近似（细高≈0→横边、细宽≈0→竖边、实心矩形→四边）：斜线/曲线
路径的 bbox 会产生幻影边——潜在误检由「实心矩形四边」占比与语料差分回归把关，
误检显著时再上 raw 路径段精确端点。
"""

from __future__ import annotations

import pypdfium2.raw as pdfium_c

from . import pdfium_kit
from .pdf import Table

_EDGE_TOL = 3.5        # 退化维判定 + 共线聚簇 + 覆盖容差（pt；Word 双线边框两线
                        # 相距 ~3.4pt 须并簇，否则出幽灵列）
_MAX_GRID_LINES = 80   # 单方向边线簇数上限——装饰性矢量页（证书底纹）直接放弃
_MAX_CELLS = 2500      # 闭合格总数上限——建筑图纸类细网格（80×80）会让簇合并
                        # 的 O(n²) 比对拖到秒级且全程持 pdfium 全局锁，直接放弃
_MIN_TABLE_CELLS = 4   # 最少闭合格数（2×2 起）
_CELL_INSET = 1.0      # 单元格取文内缩（pt，避免捞到边框邻格字符）
_TABLE_GAP_MERGE = 40.0  # 垂直相邻簇间隙上限（pt）——同一张表隔空行带的形态


def _edges_from_bbox(pos: tuple[float, float, float, float]) -> tuple[list, list]:
    """路径 bbox (l,b,r,t) → (横边 [(y, x0, x1)], 竖边 [(x, y0, y1)])，PDF 坐标。"""
    left, bot, right, top = pos
    w, h = right - left, top - bot
    thin_w, thin_h = w <= _EDGE_TOL, h <= _EDGE_TOL
    if thin_w and thin_h:
        return [], []  # 点
    if thin_h:
        return [((bot + top) / 2, left, right)], []
    if thin_w:
        return [], [((left + right) / 2, bot, top)]
    # 实心矩形（含填充底色块）：四条边都算——表格边框常以矩形路径绘制
    return [(bot, left, right), (top, left, right)], [(left, bot, top), (right, bot, top)]


def _merge_collinear(edges: list[tuple[float, float, float]]) -> dict[float, list[tuple[float, float]]]:
    """同向边 → {代表坐标: [合并后的线段 (s0, s1)]}。

    坐标聚簇（相邻差 ≤_EDGE_TOL）后段合并（重叠/相邻 ≤_EDGE_TOL 并接）——
    Word 表格每格单独画边时由此拼成整线。代表坐标取簇内均值。"""
    edges.sort()
    clusters: list[dict] = []
    for coord, s0, s1 in edges:
        if s1 - s0 <= _EDGE_TOL:
            continue  # 零长边
        if clusters and coord - clusters[-1]["coords"][-1] <= _EDGE_TOL:
            clusters[-1]["coords"].append(coord)
            clusters[-1]["segs"].append((s0, s1))
        else:
            clusters.append({"coords": [coord], "segs": [(s0, s1)]})
    out: dict[float, list[tuple[float, float]]] = {}
    for c in clusters:
        segs = sorted(c["segs"])
        merged: list[list[float]] = []
        for s0, s1 in segs:
            if merged and s0 - merged[-1][1] <= _EDGE_TOL:
                merged[-1][1] = max(merged[-1][1], s1)
            else:
                merged.append([s0, s1])
        out[sum(c["coords"]) / len(c["coords"])] = [(a, b) for a, b in merged]
    return out


def _covered(segs: list[tuple[float, float]], a: float, b: float) -> bool:
    """线段集合是否完整覆盖 [a, b]（容差内，单段或并接段均可）。"""
    return any(s0 - _EDGE_TOL <= a and b <= s1 + _EDGE_TOL for s0, s1 in segs)


def _cells(h_lines: dict[float, list], v_lines: dict[float, list]) -> list[tuple[float, float, float, float]]:
    """网格闭合格：相邻横线对 × 相邻竖线对，四边均有边线覆盖。"""
    ys = sorted(h_lines)
    xs = sorted(v_lines)
    cells = []
    for yi in range(len(ys) - 1):
        for xi in range(len(xs) - 1):
            y0, y1 = ys[yi], ys[yi + 1]
            x0, x1 = xs[xi], xs[xi + 1]
            if x1 - x0 <= _EDGE_TOL or y1 - y0 <= _EDGE_TOL:
                continue
            if not (_covered(h_lines[y0], x0, x1) and _covered(h_lines[y1], x0, x1)):
                continue
            if not (_covered(v_lines[x0], y0, y1) and _covered(v_lines[x1], y0, y1)):
                continue
            cells.append((x0, y0, x1, y1))
    return cells


def _clusters(cells: list[tuple[float, float, float, float]]) -> list[list[tuple[float, float, float, float]]]:
    """共边的格 → 连通簇（同一条格线上的格属于同一表）。"""
    parent = list(range(len(cells)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            a, b = cells[i], cells[j]
            touch_x = abs(a[0] - b[2]) <= _EDGE_TOL or abs(b[0] - a[2]) <= _EDGE_TOL
            touch_y = abs(a[1] - b[3]) <= _EDGE_TOL or abs(b[1] - a[3]) <= _EDGE_TOL
            share_v = touch_x and not (a[3] <= b[1] - _EDGE_TOL or b[3] <= a[1] - _EDGE_TOL)
            share_h = touch_y and not (a[2] <= b[0] - _EDGE_TOL or b[2] <= a[0] - _EDGE_TOL)
            if share_v or share_h:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list] = {}
    for i, c in enumerate(cells):
        groups.setdefault(find(i), []).append(c)
    return list(groups.values())


def _cell_text(page, tp, cell: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = cell  # PDF 坐标（行带/列界本就在 PDF 空间算出）
    left, bot, right, top = (x0 + _CELL_INSET, y0 + _CELL_INSET, x1 - _CELL_INSET, y1 - _CELL_INSET)
    if right - left <= 0 or top - bot <= 0:
        return ""
    text = pdfium_kit.bounded_text(tp, (left, bot, right, top))
    return " ".join(text.split())


def _merge_overlapping(groups: list[list[tuple[float, float, float, float]]]) -> list[list[tuple[float, float, float, float]]]:
    """bbox 高度重叠的簇合并（同一张表被断裂边线拆成多簇的形态——extract 按簇
    边界扫线，分开会重复出表）。重叠面积 ≥ 较小簇面积一半即并。"""
    def bbox(g):
        return (min(c[0] for c in g), min(c[1] for c in g), max(c[2] for c in g), max(c[3] for c in g))

    def area(b):
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    merged: list[list] = []
    for g in groups:
        gb = bbox(g)
        target = None
        for k, h in enumerate(merged):
            hb = bbox(h)
            ox = min(gb[2], hb[2]) - max(gb[0], hb[0])
            oy = min(gb[3], hb[3]) - max(gb[1], hb[1])
            ov = max(0.0, ox) * max(0.0, oy)
            # 垂直相邻（隔空行带的同一张表）：横向重叠 ≥ 较窄簇一半且间隙 ≤ 上限
            v_gap = max(gb[1] - hb[3], hb[1] - gb[3])
            x_overlap_ratio = (max(0.0, ox) / max(1e-6, min(gb[2] - gb[0], hb[2] - hb[0])))
            adjacent = v_gap <= _TABLE_GAP_MERGE and x_overlap_ratio >= 0.5
            if ov >= 0.5 * min(area(gb), area(hb)) or adjacent:
                target = k
                break
        if target is None:
            merged.append(g)
        else:
            merged[target] = merged[target] + g
    return merged


def find_tables(page) -> list[Table]:
    """页内有框表格 → [Table(bbox 视觉左上原点, rows 二维文本)]。

    检测：1×1 闭合格连通簇（≥4 格）定表位；extract 按「穿过行带的竖边」定列界
    ——合并格（跨列无边）在宽格上自然闭合，缺边格补 ""。行/列数各行可不等宽，
    下游 _pipe_table 统一补齐矩形。"""
    bboxes = pdfium_kit.object_bboxes(page, (pdfium_c.FPDF_PAGEOBJ_PATH,))
    h_edges: list[tuple[float, float, float]] = []
    v_edges: list[tuple[float, float, float]] = []
    for pos in bboxes:
        hs, vs = _edges_from_bbox(pos)
        h_edges.extend(hs)
        v_edges.extend(vs)
    if not h_edges or not v_edges:
        return []
    h_lines = _merge_collinear(h_edges)
    v_lines = _merge_collinear(v_edges)
    if len(h_lines) > _MAX_GRID_LINES or len(v_lines) > _MAX_GRID_LINES:
        return []  # 装饰性矢量页（证书底纹），不是表格
    tables: list[Table] = []
    cells = _cells(h_lines, v_lines)
    if len(cells) > _MAX_CELLS:
        return []  # 细网格图纸形态（非表格），且簇合并 O(n²) 不可接受
    tp = None  # 单元格批量取文共享文本页（每格重建 textpage 是性能大项）
    try:
        for group in _merge_overlapping(_clusters(cells)):
            if len(group) < _MIN_TABLE_CELLS:
                continue
            # 簇边界（1×1 闭合格并集），行带/列界扫描限制在此范围
            cy0 = min(c[1] for c in group) - _EDGE_TOL
            cy1 = max(c[3] for c in group) + _EDGE_TOL
            cx0 = min(c[0] for c in group) - _EDGE_TOL
            cx1 = max(c[2] for c in group) + _EDGE_TOL
            # 簇内行线/列线：坐标须落在簇范围内且线段与簇正交范围相交
            # （只查正交方向会把同 x 范围的另一张表的线捞进来）
            ys = sorted(y for y, segs in h_lines.items()
                        if cy0 <= y <= cy1 and any(s0 < cx1 and cx0 < s1 for s0, s1 in segs))
            xs = sorted(x for x, segs in v_lines.items()
                        if cx0 <= x <= cx1 and any(s0 < cy1 and cy0 < s1 for s0, s1 in segs))
            rows: list[list[str]] = []
            cell_rects: list[tuple[float, float, float, float]] = []
            # 表级列网格（穿过任一行带的竖边并集）；各行按此对齐——合并格占多列位
            # （首列置值、跨占位列补 ""），_pipe_table 直接得对齐的管道表
            bands = [(ys[i], ys[i + 1]) for i in range(len(ys) - 1) if ys[i + 1] - ys[i] > _EDGE_TOL]
            xs_index = {x: i for i, x in enumerate(xs)}
            ncols = max(len(xs) - 1, 0)
            for y0, y1 in reversed(bands):
                boundaries = [x for x in xs if _covered(v_lines[x], y0, y1)]
                row = [""] * ncols
                closed_any = False
                for bi in range(len(boundaries) - 1):
                    x0, x1 = boundaries[bi], boundaries[bi + 1]
                    if x1 - x0 <= _EDGE_TOL or not (cx0 - _EDGE_TOL <= x0 and x1 <= cx1 + _EDGE_TOL):
                        continue
                    if (
                        _covered(h_lines[y0], x0, x1)
                        and _covered(h_lines[y1], x0, x1)
                        and _covered(v_lines[x0], y0, y1)
                        and _covered(v_lines[x1], y0, y1)
                    ):
                        if tp is None:
                            tp = pdfium_kit.new_textpage(page)
                        row[xs_index[x0]] = _cell_text(page, tp, (x0, y0, x1, y1))
                        cell_rects.append((x0, y0, x1, y1))
                        closed_any = True
                    # 缺边开区（真缺格）：列位保持 ""
                if closed_any:
                    rows.append(row)
            if len(cell_rects) < _MIN_TABLE_CELLS:
                continue
            bbox_pdf = (
                min(c[0] for c in cell_rects), min(c[1] for c in cell_rects),
                max(c[2] for c in cell_rects), max(c[3] for c in cell_rects),
            )
            tables.append(Table(pdfium_kit.rect_to_tl(page, bbox_pdf), rows))
    finally:
        if tp is not None:
            pdfium_kit.close_textpage(tp)
    # 提取后去重：同一张表的交错列可分裂成多个簇且 bbox 互相重叠（行/列共享边线
    # 各自闭合）——保留非空格最多的一张，其余丢弃（重复表比缺表更糟）
    out: list[Table] = []
    for t in tables:
        dup = None
        for k, u in enumerate(out):
            ox = min(t.bbox[2], u.bbox[2]) - max(t.bbox[0], u.bbox[0])
            oy = min(t.bbox[3], u.bbox[3]) - max(t.bbox[1], u.bbox[1])
            ov = max(0.0, ox) * max(0.0, oy)
            area_t = max(1e-6, (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
            area_u = max(1e-6, (u.bbox[2] - u.bbox[0]) * (u.bbox[3] - u.bbox[1]))
            if ov >= 0.5 * min(area_t, area_u):
                dup = k
                break
        if dup is None:
            out.append(t)
        else:
            filled = lambda tb: sum(1 for row in tb.rows for c in row if c)  # noqa: E731
            if filled(t) > filled(out[dup]):
                out[dup] = t
    return out
