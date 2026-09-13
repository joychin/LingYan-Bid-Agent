"""生成标书基准 docx 模板（app/resources/tender_base_template.docx）。

行业共识「格式与内容分离」的载体：所有版式定义（字体/标题分级/正文行距缩进/
封面两档/目录/页边距/页码）活在本模板的 styles.xml 里，docx_ops 建节与合册从它
起建、只挂样式名。改版式=改本脚本重跑（等价于在 Word 里改样式后另存），不是改
业务代码。

版式取值来源=2026-09-13 用户提供的版式参考件（一份高校学位论文格式规范；实测
导出其 styles.xml/页脚/页面设置，并对照其正文自述的版式条文）——中文正式
文档通行档：

  · 页面 A4，上下 2.54 / 左右 3.18。**注**：参考件正文条文写「上下左右 25mm」，
    与文件实际情况不一致，此处以文件实测为准；要改成 25mm 只动下面四个 MARGIN。
  · 正文 宋体小四、1.5 倍行距、首行缩进 2 字符、两端对齐
  · 标题 黑体分级加粗黑色（中西文同族，参考件标题的 ascii 也是黑体）、顶格无缩进：
    一级三号 / 二级小三 / 三级四号 / 四级小四
  · 封面 大字黑体二号加粗居中，落款黑体小三加粗居中
  · 页码 右下角、Times New Roman 五号、数字两侧无修饰线
  · 页眉 小五号宋体、页眉上边距 15mm（只定义样式与边距，不建页眉部件——参考件
    本身也没有页眉，避免给每册凭空加一个空页眉）
  · 目录 「目录」三号黑体加粗居中；条目小四宋体 + 右对齐点线前导，层级缩进 2 字符递进

Normal 保持中性（无缩进、单倍行距）——素材拷贝的无样式段落与表格单元格都吃
Normal，正文档位由自定义样式 Tender Body 承载，避免首行缩进/1.5 行距泄漏进表格
单元格。标题的行间气口用显式 space_before/after 表达（参考件靠手打空段制造气口，
机械合册没有那个自由度）。

用法：cd sidecar && uv run python scripts/make_base_template.py
"""

from pathlib import Path
import re

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH,
    WD_BREAK,
    WD_TAB_ALIGNMENT,
    WD_TAB_LEADER,
)
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent.parent / "app" / "resources" / "tender_base_template.docx"

# 字号档（中文号数 ↔ pt，参考件通篇用号数标注）
ER_HAO = 22        # 二号
SAN_HAO = 16       # 三号
XIAO_SAN = 15      # 小三
SI_HAO = 14        # 四号
XIAO_SI = 12       # 小四
WU_HAO = 10.5      # 五号
XIAO_WU = 9        # 小五

EAST_BODY = "宋体"  # 正文中文字族
EAST_HEAD = "黑体"  # 标题/封面/目录标题中文字族
LATIN = "Times New Roman"  # 正文与页码的西文字族
BLACK = RGBColor(0, 0, 0)

# 页面（参考件实测值；条文写 25mm 与文件不符，以文件为准）
MARGIN_V = Cm(2.54)
MARGIN_H = Cm(3.18)
HEADER_DIST = Cm(1.5)
FOOTER_DIST = Cm(1.75)

# (样式名, 字号pt, 加粗) —— 参考件 2.2.2.2「自然科学类」章节标号规则的层级字号
HEADINGS = [
    ("Heading 1", SAN_HAO, True),
    ("Heading 2", XIAO_SAN, True),
    ("Heading 3", SI_HAO, True),
    ("Heading 4", XIAO_SI, True),
]

HEADING_SPACE = Pt(13)  # 标题前后气口（参考件用空段表达，见模块 docstring）


# 主题引用属性——python-docx 默认模板的 Heading/Title 等样式天生带这组属性，
# OOXML 里 *Theme 优先于同名显式属性；而默认 theme1.xml 的东亚字形是空串，
# 引用落空时 Word 回退应用默认东亚字体（Mac/无中文语言包的 Office=ＭＳ 明朝，
# 即 2026-09-13「整本正文显示 MS 明朝」的根因）。设置显式字体前必须摘掉。
_THEME_FONT_ATTRS = ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme")


def _set_fonts(style, east: str, latin: str = LATIN) -> None:
    """设置样式的字体：中文走 eastAsia、西文走 ascii/hAnsi、复杂文种走 cs，
    并摘掉 *Theme 引用（否则显式名被主题引用压住，见 _THEME_FONT_ATTRS 注释）。
    标题传 latin=黑体（参考件标题中西文同族），正文/页码传 Times New Roman。"""
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in _THEME_FONT_ATTRS:
        fonts.attrib.pop(qn(attr), None)
    fonts.set(qn("w:ascii"), latin)
    fonts.set(qn("w:hAnsi"), latin)
    fonts.set(qn("w:eastAsia"), east)
    fonts.set(qn("w:cs"), latin)


def _style_char_twin(doc, style_id: str, *, size: float, bold: bool, east: str, latin: str) -> None:
    """同步硬化段落样式的伴生字符样式（Heading1Char/TitleChar 等）。

    python-docx 默认模板给每个内置标题配了带 Word 2007 旧配色（#365F91 蓝/
    斜体/Calibri）的字符样式，且段落样式经 w:link 指向它；docx-preview 渲染时
    把链接字符样式追加在同选择器规则后面（renderStyles 的 linked concat），
    同优先级后写者赢——伴生样式不同步硬化，版式预览里标题永远是旧的蓝脸。
    （Word 本体不受此影响，但预览即用户所见。）"""
    try:
        char = next(
            s for s in doc.styles
            if s.element.get(qn("w:styleId")) == f"{style_id}Char"
        )
    except StopIteration:
        return
    char.font.size = Pt(size)
    char.font.bold = bold
    char.font.italic = False
    char.font.color.rgb = BLACK
    _set_fonts(char, east, latin)


def _harden_theme_and_defaults(doc) -> None:
    """docDefaults 与 theme1.xml 兜底（与 _THEME_FONT_ATTRS 同一根因的第二道防线）：

    ① docDefaults 的 rFonts 也是主题引用、lang 东亚语是 en-US——显式化为
       宋体/Times New Roman + eastAsia=zh-CN（无样式链命中的文字不再落空主题，
       东亚语言标注对不再让 Word 按「日语环境」挑默认字体）。
    ② theme1.xml 的 major/minor 东亚字形从空串填为 黑体/宋体——素材合并
       （_merge_missing_styles）迁入的样式自带 eastAsiaTheme 引用且我们改不了，
       非空主题字形让这些引用解析到宋体而不是应用默认（ＭＳ 明朝）。
    """
    # ① docDefaults
    rpr = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
    fonts = rpr.get_or_add_rFonts()
    for attr in _THEME_FONT_ATTRS:
        fonts.attrib.pop(qn(attr), None)
    fonts.set(qn("w:ascii"), LATIN)
    fonts.set(qn("w:hAnsi"), LATIN)
    fonts.set(qn("w:eastAsia"), EAST_BODY)
    fonts.set(qn("w:cs"), LATIN)
    lang = rpr.find(qn("w:lang"))
    if lang is not None:
        lang.set(qn("w:eastAsia"), "zh-CN")

    # ② theme1.xml（majorFont 段=黑体 标题族，minorFont 段=宋体 正文档）
    for part in doc.part.package.iter_parts():
        if str(part.partname) != "/word/theme/theme1.xml":
            continue
        xml = part.blob.decode("utf-8")
        fills = [EAST_HEAD, EAST_BODY]

        def _fill(m, _i=iter(fills)):
            return m.group(0).replace('typeface=""', f'typeface="{next(_i)}"')

        part._blob = re.sub(r"<a:(?:majorFont|minorFont)>.*?<a:ea typeface=\"\"/>", _fill, xml, flags=re.S).encode("utf-8")
        break


def _style(doc, name: str, style_id: str):
    """取已有段落样式；默认模板没有的自定义族现场新建并钉死 styleId。"""
    try:
        return doc.styles[name]
    except KeyError:
        st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.element.set(qn("w:styleId"), style_id)
        return st


def _page_field_runs() -> list:
    """页脚页码域（PAGE 字段），字体按参考件钉死 Times New Roman 五号、无修饰线。"""
    rpr = (
        f'<w:rPr {nsdecls("w")}>'
        f'<w:rFonts w:ascii="{LATIN}" w:hAnsi="{LATIN}" w:eastAsia="{LATIN}" w:cs="{LATIN}"/>'
        f'<w:sz w:val="{int(WU_HAO * 2)}"/><w:szCs w:val="{int(WU_HAO * 2)}"/>'
        f"</w:rPr>"
    )
    return [
        parse_xml(f'<w:r {nsdecls("w")}>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'),
        parse_xml(
            f'<w:r {nsdecls("w")}>{rpr}'
            f'<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        ),
        parse_xml(f'<w:r {nsdecls("w")}>{rpr}<w:fldChar w:fldCharType="end"/></w:r>'),
    ]


def main() -> None:
    doc = Document()
    _harden_theme_and_defaults(doc)

    # 页面：A4 + 参考件页边距（上下 2.54 / 左右 3.18）+ 页眉页脚距
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin = sec.bottom_margin = MARGIN_V
    sec.left_margin = sec.right_margin = MARGIN_H
    sec.header_distance = HEADER_DIST
    sec.footer_distance = FOOTER_DIST

    # 页脚：右下角页码域（参考件 4.2.2「页码置于页面右下角」）
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in _page_field_runs():
        footer._p.append(run)

    # Normal：中性正文——宋体小四单倍行距，无缩进（表格/素材段落也吃它，
    # 不带正文专属格式）
    normal = doc.styles["Normal"]
    normal.font.size = Pt(XIAO_SI)
    _set_fonts(normal, EAST_BODY)
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing = 1.0
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)

    # Tender Body：正文段（建节初始段/修订插段/素材归顺段挂它）——参考件正文档：
    # 宋体小四、1.5 倍行距、首行缩进 2 字符、两端对齐。firstLineChars=200 是
    # Word 的「字符」单位（随字号自适应）；firstLine=480 twips 是 12pt 下同宽兜底，
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

    # Tender Cover / Tender Cover Sub：封面两档——大字行（项目名/「投标文件·册名」）
    # 黑体二号加粗，落款行（投标人/日期）黑体小三加粗，均居中无缩进。
    cover = doc.styles.add_style("Tender Cover", WD_STYLE_TYPE.PARAGRAPH)
    cover.element.set(qn("w:styleId"), "TenderCover")
    cover.base_style = normal
    cover.quick_style = True
    cover.font.size = Pt(ER_HAO)
    cover.font.bold = True
    _set_fonts(cover, EAST_HEAD, EAST_HEAD)
    cpf = cover.paragraph_format
    cpf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cpf.line_spacing = 1.5
    cpf.space_before = Pt(0)
    cpf.space_after = Pt(18)
    cover_sub = doc.styles.add_style("Tender Cover Sub", WD_STYLE_TYPE.PARAGRAPH)
    cover_sub.element.set(qn("w:styleId"), "TenderCoverSub")
    cover_sub.base_style = cover
    cover_sub.quick_style = True
    cover_sub.font.size = Pt(XIAO_SAN)
    cover_sub.font.bold = True
    csf = cover_sub.paragraph_format
    csf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    csf.space_after = Pt(6)

    # 标题：黑体分级加粗黑色、中西文同族（去默认模板的英文蓝与 Times 混排），
    # 顶格无缩进，keepNext+keepLines 防标题落单在页尾；italic 显式关掉
    # （默认模板四级标题自带斜体，中文标题不该斜）
    for name, size, bold in HEADINGS:
        st = doc.styles[name]
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.italic = False
        st.font.color.rgb = BLACK
        _set_fonts(st, EAST_HEAD, EAST_HEAD)
        spf = st.paragraph_format
        spf.space_before = HEADING_SPACE
        spf.space_after = HEADING_SPACE
        spf.line_spacing = 1.0
        spf.keep_with_next = True
        spf.keep_together = True
        _style_char_twin(doc, name.replace(" ", ""), size=size, bold=bold,
                         east=EAST_HEAD, latin=EAST_HEAD)

    # Title：文档大标题（合册容器章用），黑体二号加粗居中，去默认底边框
    title = doc.styles["Title"]
    title.font.size = Pt(ER_HAO)
    title.font.bold = True
    title.font.italic = False
    title.font.color.rgb = BLACK
    _set_fonts(title, EAST_HEAD, EAST_HEAD)
    _style_char_twin(doc, "Title", size=ER_HAO, bold=True, east=EAST_HEAD, latin=EAST_HEAD)
    tpf = title.paragraph_format
    tpf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tpf.space_before = Pt(0)
    tpf.space_after = Pt(22)
    ppr = title.element.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is not None:
        ppr.remove(pbdr)

    # 目录：TOC Heading（「目录」二字，三号黑体加粗居中）+ toc 1..3（小四宋体、
    # 右对齐点线前导、层级缩进 2 字符递进——参考件 2.1.5 的「阶梯式排列」）
    toc_head = _style(doc, "TOC Heading", "TOCHeading")
    toc_head.base_style = normal
    toc_head.quick_style = True
    toc_head.font.size = Pt(SAN_HAO)
    toc_head.font.bold = True
    toc_head.font.color.rgb = BLACK
    _set_fonts(toc_head, EAST_HEAD, EAST_HEAD)
    thpf = toc_head.paragraph_format
    thpf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    thpf.space_before = Pt(0)
    thpf.space_after = Pt(18)
    tab_pos = sec.page_width - sec.left_margin - sec.right_margin  # 页宽内文区，点线顶到右缘
    for lvl, name in enumerate(("toc 1", "toc 2", "toc 3"), start=1):
        toc = _style(doc, name, f"TOC{lvl}")
        toc.base_style = normal
        toc.quick_style = True
        toc.font.size = Pt(XIAO_SI)
        toc.font.color.rgb = BLACK
        _set_fonts(toc, EAST_BODY)
        tpf_lvl = toc.paragraph_format
        tpf_lvl.line_spacing = 1.5
        tpf_lvl.space_before = Pt(0)
        tpf_lvl.space_after = Pt(0)
        tpf_lvl.left_indent = Pt(XIAO_SI * 2 * (lvl - 1))  # 每级缩进 2 字符
        tpf_lvl.tab_stops.add_tab_stop(tab_pos, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)

    # 页眉：只定义样式（参考件 4.2.2「页眉处仅可出现文档题目，小五号宋体」），
    # 不建页眉部件——不给每册凭空加空页眉
    header = _style(doc, "Tender Header", "TenderHeader")
    header.base_style = normal
    header.font.size = Pt(XIAO_WU)
    _set_fonts(header, EAST_BODY)
    hpf = header.paragraph_format
    hpf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hpf.line_spacing = 1.0

    # 样式示例段：按真实标书的装订顺序排三页（封面→目录→正文层级），所见即
    # 所得地预览各级版式。docx_ops._new_document 起建时整段剥离（body 只留
    # sectPr），示例永不进入业务产物——「文件里有字」与「产物干净」两全。
    # 分页用段首显式 w:br run（段落 pageBreakBefore 直接格式 docx-preview
    # 不认，它只查样式级属性）。
    doc.add_paragraph("XX 项目投标文件（封面大字示例）", style="Tender Cover")
    doc.add_paragraph("投标人：XX 有限公司", style="Tender Cover Sub")
    doc.add_paragraph("日期：2026 年 9 月", style="Tender Cover Sub")

    toc_head_p = doc.add_paragraph(style="TOC Heading")
    toc_head_p.add_run().add_break(WD_BREAK.PAGE)
    toc_head_p.add_run("目  录")
    for text, lvl in (
        ("第一章 技术方案\t1", 1),
        ("1.1 项目理解\t2", 2),
        ("1.1.1 建设背景\t3", 3),
    ):
        doc.add_paragraph(text, style=f"toc {lvl}")

    title_p = doc.add_paragraph(style="Title")
    title_p.add_run().add_break(WD_BREAK.PAGE)
    title_p.add_run("XX 市政务服务平台投标文件（样式示例页）")
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
        "标题使用黑体分级加粗（一级三号至四级小四）；页码在页面右下角。"
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
    assert chk.paragraphs[0].style.name == "Tender Cover"  # 示例页首段=封面（真实装订顺序）

    b = chk.styles["Tender Body"]
    bi = b.element.get_or_add_pPr().find(qn("w:ind"))
    assert bi.get(qn("w:firstLineChars")) == "200"
    assert b.paragraph_format.line_spacing == 1.5
    assert b.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY

    # 标题：三号黑体加粗黑色、中西文同族、keepLines、无斜体（默认模板四级斜体）
    h1 = chk.styles["Heading 1"]
    assert h1.font.color.rgb == BLACK and h1.font.size == Pt(SAN_HAO)
    assert h1.font.italic is False
    h1_fonts = h1.element.get_or_add_rPr().get_or_add_rFonts()
    assert h1_fonts.get(qn("w:eastAsia")) == EAST_HEAD
    assert h1_fonts.get(qn("w:ascii")) == EAST_HEAD
    assert chk.styles["Heading 1"].paragraph_format.keep_together is True
    assert chk.styles["Heading 4"].font.italic is False
    # 伴生字符样式同步（docx-preview 把链接字符样式追加渲染，不同步=预览回到旧蓝脸）
    h1c = next(
        s for s in chk.styles if s.element.get(qn("w:styleId")) == "Heading1Char"
    )
    assert h1c.font.color.rgb == BLACK and h1c.font.size == Pt(SAN_HAO)
    assert h1c.font.italic is False
    hc_fonts = h1c.element.get_or_add_rPr().get_or_add_rFonts()
    assert hc_fonts.get(qn("w:eastAsia")) == EAST_HEAD

    # Normal 仍中性（表格/素材段落吃它）：单倍行距、无缩进
    n = chk.styles["Normal"]
    assert n.paragraph_format.line_spacing == 1.0
    assert n.element.get_or_add_pPr().find(qn("w:ind")) is None
    nfonts = n.element.get_or_add_rPr().get_or_add_rFonts()
    assert nfonts.get(qn("w:eastAsia")) == EAST_BODY
    assert nfonts.get(qn("w:ascii")) == LATIN

    # 封面两档：二号/小三、黑体加粗居中
    cov = chk.styles["Tender Cover"]
    assert cov.font.size == Pt(ER_HAO) and cov.font.bold is True
    assert cov.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    cov_fonts = cov.element.get_or_add_rPr().get_or_add_rFonts()
    assert cov_fonts.get(qn("w:eastAsia")) == EAST_HEAD
    sub = chk.styles["Tender Cover Sub"]
    assert sub.font.size == Pt(XIAO_SAN) and sub.font.bold is True
    assert sub.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER

    # 目录：条目样式带右对齐点线制表位
    toc1 = chk.styles["toc 1"]
    assert toc1.paragraph_format.tab_stops[0].alignment == WD_TAB_ALIGNMENT.RIGHT
    assert toc1.paragraph_format.tab_stops[0].leader == WD_TAB_LEADER.DOTS
    assert chk.styles["TOC Heading"].font.size == Pt(SAN_HAO)

    # 页码：右下角 + 五号 Times New Roman
    ftr_p = chk.sections[0].footer.paragraphs[0]
    assert ftr_p.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert 'w:val="21"' in ftr_p._p.xml and LATIN in ftr_p._p.xml
    assert any(t.text and "PAGE" in t.text for t in ftr_p._p.iter(qn("w:instrText")))

    # twips↔EMU 换算有取整漂移，按毫米级容差断言
    assert abs(chk.sections[0].page_width - Cm(21)) < Cm(0.5)
    assert abs(chk.sections[0].left_margin - MARGIN_H) < Cm(0.5)
    assert abs(chk.sections[0].header_distance - HEADER_DIST) < Cm(0.5)

    # 主题引用防线（ＭＳ 明朝回归守卫）：我们改过的样式不得残留 *Theme 引用；
    # theme1.xml 东亚字形必须非空（兜素材合并进来的带引用样式）
    for sid in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Title"):
        rf = chk.styles[sid].element.get_or_add_rPr().get_or_add_rFonts()
        for attr in _THEME_FONT_ATTRS:
            assert qn(attr) not in rf.attrib, f"{sid} 残留 {attr}（显式字体会被压住）"
    import zipfile

    with zipfile.ZipFile(OUT) as z:
        theme_xml = z.read("word/theme/theme1.xml").decode("utf-8")
    eas = re.findall(r'<a:(?:majorFont|minorFont)>.*?<a:ea typeface="([^"]+)"', theme_xml, re.S)
    assert len(eas) == 2 and all(eas), f"theme 东亚字形应为非空二元组，实际 {eas}"
    print("self-check ok")


if __name__ == "__main__":
    main()
