"""生成标书基准 docx 模板（app/resources/tender_base_template.docx）。

行业共识「格式与内容分离」的载体：所有版式定义（字体/标题分级/正文行距缩进/
页边距/页码）活在本模板的 styles.xml 里，docx_ops 建节与合册从它起建、只挂
样式名。改版式=改本脚本重跑（等价于在 Word 里改样式后另存），不是改业务代码。

版式档=标书通行惯例（非公文 GB/T 9704 档）：正文宋体小四 1.5 倍行距首行缩进
2 字符、标题黑体分级加粗黑色（默认模板的蓝色英文脸是「生成的 Word 难看」根源）、
A4 上下 2.54/左右 3.18、页脚居中页码。Normal 保持中性（无缩进单倍行距）——
素材拷贝的无样式段落吃 Normal，标书正文格式由自定义样式 Tender Body 承载，
避免首行缩进/1.5 行距泄漏进表格单元格。

用法：cd sidecar && uv run python scripts/make_base_template.py
"""

from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent.parent / "app" / "resources" / "tender_base_template.docx"

LATIN = "Times New Roman"
BLACK = RGBColor(0, 0, 0)

# (样式名, 中文字体, 字号pt, 加粗)
HEADINGS = [
    ("Heading 1", "黑体", 18, True),   # 小二
    ("Heading 2", "黑体", 15, True),   # 小三
    ("Heading 3", "黑体", 14, True),   # 四号
    ("Heading 4", "黑体", 12, True),   # 小四
]


def _set_east_asia(style, east: str) -> None:
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    fonts.set(qn("w:ascii"), LATIN)
    fonts.set(qn("w:hAnsi"), LATIN)
    fonts.set(qn("w:eastAsia"), east)


def main() -> None:
    doc = Document()

    # 页面：A4 + Word 中文默认页边距
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin = sec.right_margin = Cm(3.18)

    # 页脚：居中页码域
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for xml in (
        f'<w:r {nsdecls("w")}><w:fldChar w:fldCharType="begin"/></w:r>',
        f'<w:r {nsdecls("w")}><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>',
        f'<w:r {nsdecls("w")}><w:fldChar w:fldCharType="end"/></w:r>',
    ):
        footer._p.append(parse_xml(xml))

    # Normal：中性正文——宋体小四单倍行距，无缩进（表格/素材段落也吃它，
    # 不带标书正文专属格式）
    normal = doc.styles["Normal"]
    normal.font.size = Pt(12)
    _set_east_asia(normal, "宋体")
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing = 1.0
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)

    # Tender Body：AI 生成的标书正文段（建节初始段/修订插段挂它）——
    # 1.5 倍行距 + 首行缩进 2 字符。firstLineChars=200 是 Word 的「字符」
    # 单位（随字号自适应）；firstLine=480 twips 是 12pt 下同宽兜底，
    # 两者并写，渲染器吃哪个都对。
    body = doc.styles.add_style("Tender Body", WD_STYLE_TYPE.PARAGRAPH)
    body.element.set(qn("w:styleId"), "TenderBody")
    body.base_style = normal
    body.quick_style = True
    bpf = body.paragraph_format
    bpf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    bpf.line_spacing = 1.5
    bpf.space_before = Pt(0)
    bpf.space_after = Pt(0)
    ind = body.element.get_or_add_pPr().get_or_add_ind()
    ind.set(qn("w:firstLineChars"), "200")
    ind.set(qn("w:firstLine"), "480")

    # 标题：黑体分级加粗黑色，去默认模板的英文蓝
    for name, east, size, bold in HEADINGS:
        st = doc.styles[name]
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = BLACK
        _set_east_asia(st, east)
        spf = st.paragraph_format
        spf.space_before = Pt(13)
        spf.space_after = Pt(13)
        spf.line_spacing = 1.0
        spf.keep_with_next = True

    # Title：文档大标题（合册容器章用），黑体二号居中，去默认底边框
    title = doc.styles["Title"]
    title.font.size = Pt(22)
    title.font.bold = True
    title.font.color.rgb = BLACK
    _set_east_asia(title, "黑体")
    tpf = title.paragraph_format
    tpf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tpf.space_before = Pt(0)
    tpf.space_after = Pt(22)
    ppr = title.element.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is not None:
        ppr.remove(pbdr)

    # 样式示例段：打开模板即可直观看到各级版式（所见即所得地改样式）。
    # docx_ops._new_document 起建时整段剥离（body 只留 sectPr），示例永不
    # 进入业务产物——「文件里有字」与「产物干净」两全。
    doc.add_heading("XX 市政务服务平台投标文件（样式示例页）", 0)
    doc.add_heading("第一章 技术方案", 1)
    doc.add_heading("1.1 项目理解", 2)
    doc.add_heading("1.1.1 建设背景", 3)
    doc.add_heading("（4）具体保障措施", 4)
    body_name = body.name
    doc.add_paragraph(
        "本项目为政务服务平台升级改造项目，正文段落使用 Tender Body 样式："
        "宋体小四、1.5 倍行距、首行缩进 2 字符、两端对齐。",
        style=body_name,
    )
    doc.add_paragraph(
        "标题使用黑体分级加粗（一级小二至四级小四）；页脚为居中页码。"
        "本页全部内容在程序建节时自动清空，仅作版式预览。",
        style=body_name,
    )

    # 清掉默认模板自带的空段（模板首行直接是 Title 示例）
    for p in doc.element.body.findall(qn("w:p")):
        if not "".join(t.text or "" for t in p.iter(qn("w:t"))).strip():
            doc.element.body.remove(p)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"written: {OUT} ({OUT.stat().st_size} bytes)")

    # 自检：重开断言关键版式与示例段存在
    chk = Document(str(OUT))
    assert chk.paragraphs, "模板应带样式示例段（起建时剥离）"
    assert chk.paragraphs[0].style.name == "Title"
    b = chk.styles["Tender Body"]
    bi = b.element.get_or_add_pPr().find(qn("w:ind"))
    assert bi.get(qn("w:firstLineChars")) == "200"
    assert b.paragraph_format.line_spacing == 1.5
    h1 = chk.styles["Heading 1"]
    assert h1.font.color.rgb == BLACK and h1.font.size == Pt(18)
    fonts = chk.styles["Normal"].element.get_or_add_rPr().get_or_add_rFonts()
    assert fonts.get(qn("w:eastAsia")) == "宋体"
    # twips↔EMU 换算有取整漂移，按毫米级容差断言
    assert abs(chk.sections[0].page_width - Cm(21)) < Cm(0.5)
    assert abs(chk.sections[0].left_margin - Cm(3.18)) < Cm(0.5)
    print("self-check ok")


if __name__ == "__main__":
    main()
