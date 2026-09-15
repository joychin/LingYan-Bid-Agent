"""测试 PDF/PNG 夹具工厂（reportlab + Pillow）——PyMuPDF 替换批的宽松许可生成器。

对外坐标习惯沿用旧 pymupdf 夹具：text(x, y_top)（左上原点 y 向下），内部换算
reportlab 的左下原点；各夹具的版式参数（字号/行距/位置）与旧实现逐行一致，保证
档位识别断言（pdf-toc/pdf-link-toc/pdf-printed-toc/pdf-numbered/pdf-plain）不变。
中文用非嵌入 CID 字体 STSong-Light（ToUnicode 齐全，文本抽取可还原）。
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

_FONT = "STSong-Light"
PAGE_W, PAGE_H = 595.0, 842.0  # 与 pymupdf new_page 默认一致

pdfmetrics.registerFont(UnicodeCIDFont(_FONT))


class Pdf:
    """薄封装：左上原点写文本/铺图、书签、GOTO 链接、翻页。"""

    def __init__(self, path: Path | str, width: float = PAGE_W, height: float = PAGE_H):
        self.path = Path(path)
        self.w, self.h = width, height
        self.c = canvas.Canvas(str(self.path), pagesize=(width, height))

    def text(self, x: float, y: float, s: str, size: float = 12) -> "Pdf":
        """左上原点写一行（y 向下，同旧 pymupdf insert_text 习惯）。"""
        self.c.setFont(_FONT, size)
        self.c.drawString(x, self.h - y, s)
        return self

    def image(self, x: float, y: float, w: float, h: float, data: bytes) -> "Pdf":
        """左上原点矩形铺图（drawImage 缩放到矩形——小底图铺满整页的证书形态）。"""
        self.c.drawImage(ImageReader(io.BytesIO(data)), x, self.h - y - h, width=w, height=h)
        return self

    def bookmark(self, title: str, key: str | None = None, level: int = 0) -> "Pdf":
        """当前页打书签目标 + 登记大纲条目（对齐旧 set_toc 用法，level 0=一级）。"""
        key = key or f"bm-{title}"
        self.c.bookmarkPage(key)
        self.c.addOutlineEntry(title, key, level=level, closed=False)
        return self

    def dest(self, key: str) -> "Pdf":
        """当前页只打链接目标（不进大纲——纯链接夹具用）。"""
        self.c.bookmarkPage(key)
        return self

    def link(self, x0: float, y0: float, x1: float, y1: float, target_key: str) -> "Pdf":
        """GOTO 链接矩形（左上原点；target_key 可前向引用后文页面）。"""
        self.c.linkRect("", target_key, (x0, self.h - y1, x1, self.h - y0), thickness=0)
        return self

    def show_page(self) -> "Pdf":
        self.c.showPage()
        return self

    def save(self) -> Path:
        self.c.save()
        return self.path


def solid_png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    """纯色 PNG（替代旧 fitz.Pixmap 造图）。"""
    buf = io.BytesIO()
    Image.new("RGB", (w, h), rgb).save(buf, "PNG")
    return buf.getvalue()


def hand_pdf(path, page_extra: str = "", content: bytes = b"BT /F1 24 Tf 72 500 Td (ROTATED PAGE TEXT) Tj ET") -> Path:
    """手工拼装最小单页 PDF（xref 偏移精确计算）。

    reportlab 不直接支持 /Rotate 等页面字典形态——旋转页坐标语义夹具用。
    内容流为单段 Helvetica 文本（标准 14 字体，无需 ToUnicode 即可抽取）。"""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 600] " + page_extra
         + " /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>").encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    Path(path).write_bytes(bytes(out))
    return Path(path)


# ---- 解析档位夹具（与旧 test_parse_document 内联夹具逐行对应） ----


def _make_pdf(path):
    """运行时生成无书签 PDF（标题与正文同字号——结构只能靠文本信号识别）。"""
    p = Pdf(path)
    p.text(72, 72, "第一章 招标公告", size=18)
    p.text(72, 110, "本项目为测试采购项目，现邀请合格投标人参加投标。")
    p.text(72, 140, "招标范围包括软件开发、系统集成与三年运维服务。")
    p.text(72, 170, "投标人应具备相应资质，并在截止时间前提交投标文件。")
    p.text(72, 220, "第二章 投标人须知", size=18)
    p.text(72, 260, "投标人应在截止时间前递交密封投标文件，逾期不予受理。")
    p.text(72, 320, "第三章 评标办法", size=18)
    p.text(72, 360, "本项目采用综合评分法，评分因素包括技术与商务两部分。")
    return p.save()


def _make_pdf_with_toc(path):
    """带书签的多页 PDF：标题与正文同字号，结构只能靠书签。"""
    p = Pdf(path)
    for i, cn in enumerate("一二三", 1):
        p.text(72, 72, f"第{cn}章 测试章节{i}")
        for j in range(6):
            p.text(72, 110 + j * 20, f"第{cn}章的正文内容第{j}段，写入足够内容以通过扫描件阈值校验。")
        p.bookmark(f"第{cn}章 测试章节{i}")
        p.show_page()
    return p.save()


def _make_pdf_printed_toc(path):
    """无书签 PDF：结构来自第 2 页印刷目录（孤立章节号行 + 引导点线条目；
    正文标题也拆行）。封面巨字用于验证不再产生伪标题。"""
    p = Pdf(path)
    p.text(72, 100, "测试项目采购文件", size=24)
    p.text(72, 130, "（封面巨字在字号判级时代会全部变成伪标题）")
    p.show_page()
    p.text(72, 72, "目 录", size=16)
    p.text(72, 110, "第一章")
    p.text(72, 128, "招标公告....................................1")
    p.text(72, 160, "第二章")
    p.text(72, 178, "投标人须知..................................3")
    p.text(72, 210, "第三章 评标办法.............................5")
    p.show_page()
    p.text(72, 72, "第一章")
    p.text(72, 90, "招标公告")
    for j in range(6):
        p.text(72, 130 + j * 20, f"公告正文第{j}段，本项目为测试采购项目内容填充。")
    p.show_page()
    p.text(72, 72, "第二章")
    p.text(72, 90, "投标人须知")
    for j in range(6):
        p.text(72, 130 + j * 20, f"须知正文第{j}段，投标人应遵守各项规定要求。")
    p.show_page()
    p.text(72, 72, "第三章 评标办法")
    for j in range(6):
        p.text(72, 110 + j * 20, f"评标正文第{j}段，综合评分法满分一百分整。")
    return p.save()


def _make_pdf_with_enumeration(path):
    """无书签无目录：正文含「本文件包括下述内容」式自枚举清单（连续 L1 编号行）。"""
    p = Pdf(path)
    p.text(72, 72, "招标文件包括下述内容")
    for i, name in enumerate(["商务文件", "技术文件", "附件"], 1):
        p.text(72, 96 + i * 22, f"第{'一二三'[i - 1]}部分 {name}")
    p.text(72, 170, "以下为各部分正文内容。")
    for cn, title in (("一", "投标邀请"), ("二", "投标人须知"), ("三", "评标办法")):
        y = 190 + "一二三".index(cn) * 90
        p.text(72, y, f"第{cn}章 {title}")
        for j in range(3):
            p.text(72, y + 24 + j * 20, f"第{cn}章正文第{j}段，填充足够内容避免扫描页误判。{'x' * 5}")
    return p.save()


def _make_pdf_split_headings(path, chapters=3):
    """无书签无目录：正文标题拆行（孤立章节号一行 + 标题文字一行）。"""
    titles = [("第一章", "招标公告"), ("第二章", "投标人须知"), ("第三章", "评标办法")]
    p = Pdf(path)
    for prefix, title in titles[:chapters]:
        p.text(72, 72, prefix)
        p.text(72, 90, title)
        for j in range(4):
            p.text(72, 130 + j * 20, f"{title}正文第{j}段，本项目为测试采购项目。")
        p.show_page()
    return p.save()


def _make_pdf_link_toc(path):
    """无书签 PDF：目录页条目带内部跳转链接（Word 导出的常见形态）——
    链接矩形即条目、目标即物理页。正文标题拆行（章节号与标题分两行）。
    命名目标可前向引用（save 时解析），目录页链接指向后文正文页。"""
    entries = [("第一章 招标公告", 3), ("第二章 投标人须知", 4), ("第三章 评标办法", 5)]
    p = Pdf(path)
    p.text(72, 100, "测试项目采购文件", size=24)
    p.show_page()
    p.text(72, 60, "目 录", size=16)
    for i, (title, target) in enumerate(entries):
        y = 100 + i * 26
        p.text(72, y, f"{title}..........{target - 2}")
        # 矩形贴紧行高（真实 Word 导出的链接矩形即条目文本范围）
        p.link(60, y - 2, 520, y + 10, f"dst{target}")
    p.show_page()
    for title, target in entries:
        p.text(72, 72, title.split()[0])
        p.text(72, 90, title.split()[1])
        for j in range(5):
            p.text(72, 130 + j * 20, f"{title}正文第{j}段，填充足够内容避免扫描页误判。")
        p.dest(f"dst{target}")
        p.show_page()
    return p.save()


def _make_pdf_with_header_footer(path, npages=4):
    """每页带重复页眉（大字号，不剔除会成为伪标题）与页码的 PDF。"""
    p = Pdf(path)
    for i in range(1, npages + 1):
        p.text(72, 30, "第三章 投标人须知", size=15)
        p.text(72, p.h - 30, f"{i}/{npages}")
        for j in range(5):
            p.text(72, 100 + j * 20, f"正文段落第{j}行，写入足够内容以通过扫描件阈值校验，内容编号{i}-{j}。")
        p.show_page()
    return p.save()
