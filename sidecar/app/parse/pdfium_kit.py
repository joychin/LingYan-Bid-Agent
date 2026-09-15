"""pdfium 薄适配层（PyMuPDF 替换批·批 1：渲染/页数/空白页先行，批 2 补文本块）。

设计约束：
- **全局锁纪律**：PDFium 官方声明不可多线程——跨线程并发调用一律禁止，即使各
  线程操作不同文档。全部 pdfium 交互收口本模块，模块级 `_PDFIUM_LOCK` 包住每次
  调用（文本/对象访问按调用粒度，微秒~毫秒级线程可交错；整页渲染单调用持锁较
  久）。与 docx_ops._PATH_LOCKS / fs_guard._WRITE_LOCK 同款「用户不可见的 plumbing
  锁」，不违「跨 run 无锁」铁则。并行 parse_document 的语义随之从「C 层真并行」
  变为「C 层串行、Python/IO 层重叠」。
- **坐标归一**：pdfium 原生 PDF 坐标（左下原点 y 向上）；本层出入参统一翻转为
  左上原点 y 向下——消费方（页眉页脚条带、块排序、链接矩形）全按此约定。旋转页
  （/Rotate≠0）的坐标语义批 2 用夹具钉死，当前按 0 旋转处理。
- 许可：pypdfium2 Apache-2.0（内置 PDFium 二进制 BSD-3）；算法参考仅 MIT 实现
  （pdfminer.six / pdfplumber），不读 MuPDF/PyMuPDF 源码。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

# RLock：允许 kit 函数内部嵌套复用（如 goto_links 内调 page_size）；对外语义=
# 任一时刻至多一个线程在 pdfium 内
_PDFIUM_LOCK = threading.RLock()

_OBJ_TEXT = pdfium_c.FPDF_PAGEOBJ_TEXT
_BOUNDED_EXPAND = 3.0  # bounded 取文垂直外扩（pt）——兜「一」等矮墨迹字形


@contextmanager
def open_document(path: Path | str):
    """打开文档（with 语义，退出时关闭；异常原样上抛——与 pymupdf.open 同口径）。"""
    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(path))
    try:
        yield doc
    finally:
        with _PDFIUM_LOCK:
            doc.close()


def page_count(path: Path | str) -> int:
    with open_document(path) as doc:
        return n_pages(doc)


def n_pages(doc) -> int:
    with _PDFIUM_LOCK:
        return len(doc)


def get_page(doc, idx: int):
    """0 起页句柄（越界 PdfiumError）。"""
    with _PDFIUM_LOCK:
        return doc[idx]


def page_size(page) -> tuple[float, float]:
    """页尺寸 (w, h)，pt。"""
    with _PDFIUM_LOCK:
        return page.get_size()


def page_is_blank(page) -> bool:
    """空白页判定：无文本且无图/路径等非文本对象（纯噪音页无需渲染）。"""
    with _PDFIUM_LOCK:
        tp = page.get_textpage()
        try:
            if tp.get_text_bounded().strip():
                return False
        finally:
            tp.close()
        return all(obj.type == _OBJ_TEXT for obj in page.get_objects(max_depth=15))


def render_page(page, dpi: int = 150):
    """整页渲染 → PIL.Image（RGB）。返回独立副本（bitmap 缓冲可随后回收）。"""
    with _PDFIUM_LOCK:
        bitmap = page.render(scale=dpi / 72.0)
        return bitmap.to_pil().copy()


def render_page_png(path: Path, page_no: int, out_path: Path, dpi: int = 150) -> Path:
    """渲染单页为 png（视觉模型读图输入）。page_no 1 起。"""
    with open_document(path) as doc:
        page = get_page(doc, page_no - 1)
        img = render_page(page, dpi=dpi)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    return out_path


def goto_links(doc, page) -> list[tuple[tuple[float, float, float, float], int]]:
    """枚举页内 GOTO 链接 → [((x0,y0,x1,y1) 左上原点矩形, 目标页 1 起)]。

    链接注解的直挂 Dest 与 GoTo Action 两条路都解析（Word 目录域两种形态都有）；
    URI/外部动作不属 GOTO，跳过。"""
    out: list[tuple[tuple[float, float, float, float], int]] = []
    with _PDFIUM_LOCK:
        n = pdfium_c.FPDFPage_GetAnnotCount(page.raw)
        for i in range(n):
            annot = pdfium_c.FPDFPage_GetAnnot(page.raw, i)
            if not annot:
                continue
            try:
                if pdfium_c.FPDFAnnot_GetSubtype(annot) != pdfium_c.FPDF_ANNOT_LINK:
                    continue
                rect = pdfium_c.FS_RECTF()
                if not pdfium_c.FPDFAnnot_GetRect(annot, rect):
                    continue
                link = pdfium_c.FPDFAnnot_GetLink(annot)
                if not link:
                    continue
                dest = pdfium_c.FPDFLink_GetDest(doc.raw, link)
                if not dest:
                    action = pdfium_c.FPDFLink_GetAction(link)
                    if action:
                        dest = pdfium_c.FPDFAction_GetDest(doc.raw, action)
                if not dest:
                    continue
                idx = pdfium_c.FPDFDest_GetDestPageIndex(doc.raw, dest)
                if idx < 0:
                    continue
                out.append((rect_to_tl(page, (rect.left, rect.bottom, rect.right, rect.top)), idx + 1))
            finally:
                pdfium_c.FPDFPage_CloseAnnot(annot)
    return out


def text_in_rect(page, rect: tuple[float, float, float, float]) -> str:
    """矩形内文本（左上原点矩形 → PDF 坐标换算，含旋转页；垂直外扩兜矮字形）。

    bounded 搜索按字符墨迹盒过滤——矮墨迹字形（「一」的墨迹盒仅 ~1.7pt）会整字
    漏掉，垂直方向外扩 _BOUNDED_EXPAND 兜住（链接矩形本就贴行高，外扩后仍远小
    于行距，不致捞进邻行）。"""
    with _PDFIUM_LOCK:
        tp = page.get_textpage()
        try:
            left, bot, right, top = rect_from_tl(page, rect)
            return tp.get_text_bounded(left=left, bottom=bot - _BOUNDED_EXPAND, right=right, top=top + _BOUNDED_EXPAND)
        finally:
            tp.close()


# ---- 批 2a：结构层原料（文本矩形 / 旋转坐标变换 / 书签 / 页面对象） ----


def new_textpage(page):
    """建文本页（表格批量取文共享一个，避免每格重建）。用毕 close_textpage。"""
    with _PDFIUM_LOCK:
        return page.get_textpage()


def close_textpage(tp) -> None:
    with _PDFIUM_LOCK:
        tp.close()


def bounded_text(tp, rect_pdf: tuple[float, float, float, float]) -> str:
    """(l, b, r, t) PDF 坐标矩形内文本——配合 new_textpage 的批量取文入口。"""
    left, bot, right, top = rect_pdf
    with _PDFIUM_LOCK:
        return tp.get_text_bounded(left=left, bottom=bot, right=right, top=top)


# ---- 批 2a：结构层原料（文本矩形 / 旋转坐标变换 / 书签 / 页面对象） ----


def page_rotation(page) -> int:
    """页 /Rotate（0/90/180/270）。"""
    with _PDFIUM_LOCK:
        return page.get_rotation() % 360


def rect_to_tl(page, rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """PDF 坐标矩形（l,b,r,t，未旋转空间）→ 视觉左上原点 (x0,y0,x1,y1)。

    pdfium 的 textpage/注解坐标恒在未旋转 PDF 空间，而 get_size 给视觉尺寸
    （旋转页已交换宽高）——四级链的条带/排序/重叠数学全按左上原点，故统一在此换算。"""
    left, bot, right, top = rect
    w, h = page_size(page)
    rot = page_rotation(page)
    if rot == 90:
        return (bot, left, top, right)
    if rot == 180:
        return (w - right, bot, w - left, top)
    if rot == 270:
        return (h - top, w - right, h - bot, w - left)
    return (left, h - top, right, h - bot)


def rect_from_tl(page, rect_tl: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """视觉左上原点矩形 → PDF 坐标 (l,b,r,t)（rect_to_tl 的逆变换）。"""
    x0, y0, x1, y1 = rect_tl
    w, h = page_size(page)
    rot = page_rotation(page)
    if rot == 90:
        return (y0, x0, y1, x1)
    if rot == 180:
        return (w - x1, y0, w - x0, y1)
    if rot == 270:
        return (w - y1, h - x1, w - y0, h - x0)
    return (x0, h - y1, x1, h - y0)


def text_rects(page) -> list[tuple[tuple[float, float, float, float], str]]:
    """pdfium C 级文本分段：[(PDF 坐标矩形, 文本)]，仅含非空文本。

    count_rects/get_rect 的分段即「连续同向文本跑」——行层分组的原料
    （官方对该调用模式有缓存优化）。两类伪影在此清洗：跨行粘连跑（文本含
    \\r\\n——只留末段，段位最贴矩形位置）与退化高度空壳（高度 ≤0.5pt，无行
    归属可言）。"""
    with _PDFIUM_LOCK:
        tp = page.get_textpage()
        try:
            n = tp.count_rects(0, tp.count_chars())
            out = []
            for i in range(n):
                rect = tp.get_rect(i)
                text = tp.get_text_bounded(*rect)
                if not text or not text.strip():
                    continue
                if "\r" in text:
                    parts = [p.strip() for p in text.replace("\r\n", "\n").split("\n")]
                    text = next((p for p in reversed(parts) if p), "")
                    if not text:
                        continue
                if rect[3] - rect[1] <= 0.5:
                    continue
                out.append((rect, text))
            return out
        finally:
            tp.close()


def page_full_text(page) -> str:
    """整页文本（pdfium 行 break 为 \\r\\n，归一为 \\n）。"""
    with _PDFIUM_LOCK:
        tp = page.get_textpage()
        try:
            text = tp.get_text_bounded()
        finally:
            tp.close()
    return text.replace("\r\n", "\n").replace("\r", "\n")


def toc(doc) -> list[tuple[int, str, int]]:
    """书签 → [(层级 1 起, 标题, 目标页 1 起)]（层级数=父节点数 +1 对齐旧 get_toc）。"""
    with _PDFIUM_LOCK:
        out = []
        for item in doc.get_toc():
            if item.page_index is None or item.page_index < 0:
                continue
            out.append((item.level + 1, item.title, item.page_index + 1))
        return out


def object_bboxes(page, obj_types: tuple[int, ...]) -> list[tuple[float, float, float, float]]:
    """指定类型页面对象的 bbox（PDF 坐标，深度遍历 Form XObject）——表格边线/空白页判定原料。"""
    with _PDFIUM_LOCK:
        return [tuple(o.get_pos()) for o in page.get_objects(filter=list(obj_types), max_depth=15)]
