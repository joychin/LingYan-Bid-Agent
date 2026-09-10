"""文档图片抽取（确定性零 LLM；2026-09-04 降级重构）：

把文档里的嵌入图抽出来**仅供内容页「本文档图片」折叠区查看**——与素材库彻底
脱钩（不写 materials.json、不进检索），证书扫描件在此核实红章/签名等视觉证据。
- docx：解包 word/media/*；PDF：逐页提取嵌入图（记出处页）。
- 程序过滤装饰图：短边 <200px 丢弃；PDF 图面积占页面 <10% 丢弃（icon/背景/分割线）。
- 浏览器原生不解码 TIFF/BMP——落盘前转 PNG。
- 限额 _MAX_IMAGES：证书扫描类文档可能几百张，超限截断（查看场景够用）。
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from . import store

logger = logging.getLogger(__name__)

_MIN_EDGE = 200      # 短边下限（px）——过滤 icon/分割线
_MIN_PAGE_RATIO = 0.10  # PDF 图面积/页面积下限——过滤装饰图
_MAX_IMAGES = 60     # 单文件抽取上限
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
        import fitz

        pix = fitz.Pixmap(data)
        if pix.colorspace and pix.colorspace.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
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
        import fitz

        pix = fitz.Pixmap(data)
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


def _extract_pdf(src: Path) -> list[tuple[bytes, str]]:
    """PDF → [(图数据, 扩展名)]；按页面积占比过滤装饰图。"""
    import fitz

    out: list[tuple[bytes, str]] = []
    doc = fitz.open(src)
    try:
        for pno in range(len(doc)):
            page = doc[pno]
            page_area = page.rect.width * page.rect.height
            seen_xrefs: set[int] = set()
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width * pix.height < page_area * _MIN_PAGE_RATIO:
                        continue
                    if pix.colorspace and pix.colorspace.n > 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    data = pix.tobytes("png")
                    out.append((data, ".png"))
                    pix = None  # noqa: F841
                except Exception:
                    continue
    finally:
        doc.close()
    return out


def extract_images(src: Path, file_name: str) -> tuple[int, int]:
    """源文件 → 抽图落盘 parse/<stem>/images/（幂等：每次全量重抽覆盖）。

    → (写入张数, 跳过张数)。与素材/检索零关系，仅供内容页查看。
    """
    ext = src.suffix.lower()
    try:
        raw = _extract_pdf(src) if ext == ".pdf" else (_extract_docx(src) if ext == ".docx" else [])
    except Exception:
        logger.exception("图片抽取失败（%s）", file_name)
        return 0, 0

    img_dir = store.kb_images_dir(file_name)
    img_dir.mkdir(parents=True, exist_ok=True)
    # 幂等重抽：清掉旧文件（含历史遗留的 .tif——转码后已改存 .png）
    for old in img_dir.iterdir():
        if old.is_file():
            old.unlink(missing_ok=True)
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
