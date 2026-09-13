"""文档图片抽取（确定性零 LLM；2026-09-04 降级重构，2026-09-13 PDF 改整页渲染）：

把文档里可贴进标书的图抽出来**仅供内容页「本文档图片」折叠区查看**——与素材库
彻底脱钩（不写 materials.json、不进检索）。这个功能的用途是「贴资料」：贴的单位
永远是**那一页的复印件**（边框/红章/文字都在），所以：
- PDF：**逐页整页渲染**（不再提取嵌入图）——电子版证书的边框/水印是底层大图、
  文字是浮在上面的文字层，按嵌入图抽只会拿到一张空底框；矢量证书（无嵌入图）
  也会被漏成 0 张。渲染看到的才是页面真实视觉；文件名即页码（img_007.png=第 7 页）。
- docx：解包 word/media/*（word 没有「页」的概念，内嵌图本身就是贴进去的资料原件）。
- docx 过滤装饰图：短边 <200px 丢弃；PDF 无需此过滤（整页渲染天然无装饰图）。
- 浏览器/Word 不认的格式：docx 侧 TIFF/BMP 落盘前转 PNG，EMF/WMF 跳过。
- 限额 _MAX_IMAGES：长文档超限截断（要贴的证书包远不到 60 页）。
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from . import store

logger = logging.getLogger(__name__)

_MIN_EDGE = 200      # docx 短边下限（px）——过滤 icon/分割线
_MAX_IMAGES = 60     # 单文件抽取上限
_RENDER_DPI = 150    # PDF 整页渲染 DPI（与 docx_image_insert 现场渲染、扫描页 VLM 同档）
# Word 里常见的矢量图格式（EMF/WMF）——浏览器不认且无转码器，落盘即裂图，跳过
_VECTOR_UNSUPPORTED = {".emf", ".wmf"}
_CONSEC_SCAN = 6     # 连续 N 张图无正文间隔 → 附件扫描区，跳过
# zip 解压护栏（声明值，读前检查——KB 上传白名单收 docx、文件天然来自对手方，
# 高压缩比 media 条目可在几 KB 压缩包里声明数 GB 解压量，不设限即 OOM 打死 sidecar）
_MAX_MEMBER_BYTES = 50 * 1024 * 1024    # 单条目解压上限
_MAX_TOTAL_BYTES = 200 * 1024 * 1024   # 单文件累计解压上限

_MAGIC = [
    (b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"),
    (b"BM", ".bmp"), (b"II*\x00", ".tif"), (b"MM\x00*", ".tif"),
]

# 浏览器原生不解码的格式（TIFF 常见于扫描 docx 附件）——落盘/读取两端都转 PNG
_BROWSER_UNFRIENDLY = {".tif", ".bmp"}


def _sniff_ext(data: bytes, fallback: str) -> str:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    return fallback


def to_png(data: bytes) -> bytes | None:
    """TIFF/BMP → PNG（MuPDF 解码转码；CMYK 先转 RGB；失败返回 None）。"""
    try:
        import pymupdf

        pix = pymupdf.Pixmap(data)
        if pix.colorspace and pix.colorspace.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        out = pix.tobytes("png")
        pix = None  # noqa: F841  释放
        return out
    except Exception:
        return None


def as_browser_friendly(data: bytes, ext: str) -> tuple[bytes, str]:
    """非浏览器友好格式（TIFF/BMP）转 PNG；已是友好格式或转码失败原样返回。"""
    if ext.lower() in _BROWSER_UNFRIENDLY:
        png = to_png(data)
        if png is not None:
            return png, ".png"
    return data, ext


def _image_size(data: bytes) -> tuple[int, int] | None:
    """读图片宽高（PyMuPDF Pixmap 解码；失败返回 None）。"""
    try:
        import pymupdf

        pix = pymupdf.Pixmap(data)
        w, h = pix.width, pix.height
        pix = None  # noqa: F841  释放
        return w, h
    except Exception:
        return None


def _extract_docx(src: Path) -> list[tuple[bytes, str]]:
    """docx → [(图数据, 扩展名)]。

    扫描附件区识别：证书扫描在 docx 里的形态是「连续多图无正文间隔」（一页一图
    连排）。按 body 顺序统计图片引用密度，连续 _CONSEC_SCAN 张以上的区段视为
    附件扫描，跳过——查看场景下证书扫描连排图信息量低且量大，过滤之。
    """
    from docx import Document

    doc = Document(str(src))
    # body 顺序里的图片 target 序列 + 是否夹有正文段
    seq: list[tuple[str, bool]] = []  # (media 文件名, 是图片引用?)
    for p in doc.paragraphs:
        blips = p._element.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        if blips:
            for b in blips:
                rid = b.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                part = doc.part.related_parts.get(rid) if rid else None
                if part is not None and hasattr(part, "partname"):
                    seq.append((str(part.partname).lstrip("/"), True))
        elif p.text.strip():
            seq.append(("", False))
    # 连续图片段落区（>=_CONSEC_SCAN 无正文）标记跳过
    media_skip: set[str] = set()
    run_imgs: list[str] = []
    for name, is_img in [*seq, ("", False)]:
        if is_img:
            run_imgs.append(name)
        else:
            if len(run_imgs) >= _CONSEC_SCAN:
                media_skip.update(run_imgs)
            run_imgs = []
    out: list[tuple[bytes, str]] = []
    total_declared = 0
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            name = info.filename
            if not name.startswith("word/media/") or name in media_skip:
                continue
            if info.is_dir():
                continue  # zip 目录占位条目（0 字节）——不是图
            if Path(name).suffix.lower() in _VECTOR_UNSUPPORTED:
                logger.info("图片抽取跳过矢量图（浏览器不认）：%s（%s）", name, src.name)
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                logger.warning(
                    "图片抽取跳过超大条目 %s（声明解压 %.0fMB > 上限）：%s",
                    name, info.file_size / 1024 / 1024, src.name,
                )
                continue
            total_declared += info.file_size
            if total_declared > _MAX_TOTAL_BYTES:
                logger.warning(
                    "图片抽取提前停止：media 累计声明解压超 %.0fMB（%s）",
                    _MAX_TOTAL_BYTES / 1024 / 1024, src.name,
                )
                break
            # 张数上限提前到读阶段（每条已解压在内存，读满即停不再白读）
            if len(out) >= _MAX_IMAGES:
                break
            data = z.read(info)
            out.append(as_browser_friendly(data, _sniff_ext(data, Path(name).suffix or ".png")))
    return out


def _blank_page(page) -> bool:
    """空白页判定：无文字、无图、无矢量绘制——纯噪音，无需渲染。"""
    if page.get_text().strip():
        return False
    if page.get_images():
        return False
    return not page.get_drawings()


def _render_pdf_pages(src: Path, img_dir: Path) -> tuple[int, int]:
    """PDF → 逐页整页渲染 PNG 落盘（→ (写入张数, 跳过张数)）。

    贴资料的单位是「那一页的复印件」，不是 PDF 内嵌的某张图——整页渲染才能拿到
    边框/红章/文字俱全的页面视觉（电子版证书的文字是浮在底图上的文字层，抽嵌入图
    只剩空底框）。文件名即页码（img_007.png=第 7 页），空白页跳过、编号留空洞，
    模型据转录 md 的 <!-- p:N --> 页锚点即可推回页图。
    """
    import pymupdf

    written = 0
    skipped = 0
    doc = pymupdf.open(src)
    try:
        for pno in range(len(doc)):
            if written >= _MAX_IMAGES:
                break
            page = doc[pno]
            if _blank_page(page):
                skipped += 1
                continue
            pix = page.get_pixmap(dpi=_RENDER_DPI)
            pix.save(str(img_dir / f"img_{pno + 1:03d}.png"))
            pix = None  # noqa: F841  释放
            written += 1
    finally:
        doc.close()
    return written, skipped


def extract_images(src: Path, file_name: str) -> tuple[int, int]:
    """源文件 → 抽图落盘 parse/<stem>/images/（幂等：每次全量重抽覆盖）。

    → (写入张数, 跳过张数)。与素材/检索零关系，仅供内容页查看。
    PDF 走整页渲染（文件名即页码），docx 走内嵌图抽取。
    """
    img_dir = store.kb_images_dir(file_name)
    img_dir.mkdir(parents=True, exist_ok=True)
    # 幂等重抽：清掉旧文件（含历史遗留的 .tif——转码后已改存 .png）
    for old in img_dir.iterdir():
        if old.is_file():
            old.unlink(missing_ok=True)

    ext = src.suffix.lower()
    if ext == ".pdf":
        try:
            return _render_pdf_pages(src, img_dir)
        except Exception:
            logger.exception("PDF 整页渲染失败（%s）", file_name)
            return 0, 0

    try:
        raw = _extract_docx(src) if ext == ".docx" else []
    except Exception:
        logger.exception("图片抽取失败（%s）", file_name)
        return 0, 0

    written = 0
    passed = 0
    for data, iext in raw:
        size = _image_size(data)
        if size and min(size) < _MIN_EDGE:
            continue
        if not size and len(data) < 8 * 1024:
            continue  # 判不出尺寸的小对象大概率是装饰
        passed += 1
        if passed > _MAX_IMAGES:
            break
        written += 1
        (img_dir / f"img_{written:03d}{iext}").write_bytes(data)
    return written, len(raw) - written


def list_images(file_name: str) -> list[dict]:
    """内容页折叠区清单：图片文件名 + 字节数（按名升序）。"""
    img_dir = store.kb_images_dir(file_name)
    if not img_dir.is_dir():
        return []
    return [
        {"name": p.name, "size": p.stat().st_size}
        for p in sorted(img_dir.iterdir())
        if p.is_file()
    ]
