"""docx 正文工具族（tender-body docx 直出路线，2026-09-06 定案）。

正文节文件 = 任务 work/body/ 下每节一个 .docx；模型不碰二进制——本工具族把
docx 翻译成文本世界（读视图/编号寻址），写入全由程序机械完成：

- docx_section_create：建节文件（标题 + 可选初始段落；已存在不覆盖，
  重写传 replace=true——旧版自动入恢复点栈）
- docx_section_read：序列化视图（P1..Pn 段落+样式+图片标记，T1..Tm 表格逐行
  展开 R行 C列= 格文本——合并格标「同左/同上」，格坐标即修订寻址）
- docx_material_inject：素材块元素级注入——从素材 docx 原件把块区间对应的
  元素（段落/表格连合并单元格、图片连关系）整体拷进目标节文件，零转写保真；
  寻址 = 素材解析时落盘的 element_map（md 行号区间 → 原件 body 子元素）；
  元素引用的样式与自动编号定义随迁（含 basedOn/link 链；编号定义按内容判定
  沿用、id 冲突时重映射并改写引用——numbering id 只是文档内部门牌号）
- docx_source_inject：招标原件拷贝——任务 sources/ 的 docx 按「整文件或 md
  行号区间」元素级拷进正文节；现场跑解析注册表拿 element_lines 定位（确定性、
  不依赖任务侧解析落盘）；格式跟随与格式件（投标函/一览表等模板填充类）场景，
  与素材注入共用同一套迁移引擎
- docx_image_insert：单图插入——证书复印件/扫描件/截图等独立图片（docx 直出
  管线的放图通道；素材块/招标件内的图走注入、不经此工具）。图源=知识库抽取图
  /任务 sources 图片/PDF 原件按页现场渲染；全宽居中、段落标记+内容双插入修订
  （与插段同构——拒绝修订=整段含图消失）
- docx_section_revise：定向修订，全部落成 Word 原生修订标记（w:ins/w:del，
  author=Tender Agent）——用户在 Word 审阅界面逐条接受/拒绝；正文段落按
  P 序号、表格单元格按 table/row/col（replace 改旧值、fill 填空格）；落盘前
  程序做「拒绝全部修订后文本与修订前逐字一致」的自校验（标记写坏的机械防线，
  覆盖正文与表格单元格段落）
- docx_assemble_volume：整本合册——按投标目录树序把各节 docx 合并成每册
  一个整本文件（容器节点发章标题——按树序自动编号（第X章/1.1，格式取目录
  产物 numbering 字段）、一级章前分页、页脚页码；模板填充类叶子
  产出节文件即按树序并入、未产出按附件对待不占整本位；整本是派生产物，
  内容真值在节文件，重新合册覆盖）

寻址纪律：段落序号以 docx_section_read 视图为准（body 直属段落，不含表格内
段落）；revise 提交 (序号, 期望原文 find) 双重校验防漂移，多条段落编辑按序号
从大到小应用（防插入/删除位移；表格格编辑不改变段落序号，与段落批互不影响，
另批处理）。表格的插行/删行与嵌套表格不支持（在 Word 中改）。

设计参考：document-skills 插件（Proprietary——只借思想不搬代码：修订标记
形态、组合寻址、图片三件套、生成后机械校验）；图片关系迁移走
get_or_add_image（按内容去重、自动避让 partname）。
"""

from __future__ import annotations

import functools
import json
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm
from langchain_core.tools import tool
from lxml import etree

from .. import db, runctx
from ..artifact_store import sources_dir, work_dir
from ..config import workspace_dir
from ..knowledge import materials_lib
from ..parse import convert as parse_convert
from ..parse.pdf import render_page_png
from . import body_contract

_AUTHOR = "Tender Agent"
_COMMENT_AUTHOR = "Swift Agent"  # 批注作者（Word 审阅侧栏可见；待办批注与修订标记分属两套体系）
_VIEW_TEXT_LIMIT = 800  # 视图单段截断（修订需精确文本，超长段提示去 Word 处理）
_CELL_TEXT_LIMIT = 60  # 视图单元格截断（填空场景格文本短；长格内容去 Word 看）


def _task_id() -> str | None:
    ctx = runctx.current_run()
    if ctx is None:
        return None
    conv = db.get_conversation(ctx.conversation_id) if ctx.conversation_id else None
    return (conv or {}).get("task_id")


def _dest_path(task_id: str, rel: str, *, must_exist: bool) -> tuple[Path, str]:
    """正文 docx 路径解析：只放行 work/body/ 下、自动补 .docx、防目录穿越。

    返回 (绝对路径, 相对 work/ 的展示路径)；违规抛 ValueError（工具层转人话）。
    """
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("未指定文件路径")
    if not rel.endswith(".docx"):
        rel += ".docx"
    if not rel.startswith("body/"):
        raise ValueError("docx 正文只允许落在任务 work/body/ 目录下")
    root = work_dir(task_id).resolve()
    p = (root / rel).resolve()
    body_root = root / "body"
    # resolve 后校验 body 目录在祖先链——词法前缀检查挡不住 body/../x.docx
    # 这类单级穿越（折叠后落 work/ 根），也不能漏掉 symlink 指向外部的情况
    if body_root != p and body_root not in p.parents:
        raise ValueError("路径越界（docx 正文只允许落在任务 work/body/ 目录下）")
    if must_exist and not p.is_file():
        raise ValueError(f"文件不存在：work/{rel}（先用 docx_section_create 创建）")
    return p, rel


def _rotate_restore_point(dst: Path) -> None:
    """旧文件入恢复点栈（<文件名>.restorepoints/NNNN.bak、留 3 个轮换——工作台编辑
    恢复点同款目录形态；.bak 不匹配 rglob("*.docx")，不进面板列表与「本轮文件」）。"""
    d = dst.with_name(dst.name + ".restorepoints")
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    dst.rename(d / f"{ts}.bak")
    points = sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".bak")
    for old in points[:-3]:
        old.unlink()


# source_inject 的元素映射缓存：同原件一个 run 拷多个格式件（投标函/授权书/
# 一览表…）不重复整本解析——几百页招标文件每次解析秒级；(路径, mtime) 为键，
# 原件被替换（mtime 变）即自动失效重解析；FIFO 限 8 条防膨胀
_ELEMENT_LINES_CACHE: dict[tuple[str, float], list] = {}
_ELEMENT_LINES_CACHE_MAX = 8


def _source_element_lines(src_path: Path) -> list:
    if not src_path.is_file():
        return []
    key = (str(src_path), src_path.stat().st_mtime)
    hit = _ELEMENT_LINES_CACHE.get(key)
    if hit is not None:
        return hit
    res = parse_convert(src_path)
    lines = list(res.info.get("element_lines") or [])
    if len(_ELEMENT_LINES_CACHE) >= _ELEMENT_LINES_CACHE_MAX:
        _ELEMENT_LINES_CACHE.pop(next(iter(_ELEMENT_LINES_CACHE)))
    _ELEMENT_LINES_CACHE[key] = lines
    return lines


# ---------- 修订标记（tracked changes）核心 ----------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_rev_id(doc: Document) -> int:
    ids = [
        int(e.get(qn("w:id")))
        for e in doc.element.body.iter()
        if e.tag in (qn("w:ins"), qn("w:del")) and (e.get(qn("w:id")) or "").isdigit()
    ]
    return (max(ids) + 1) if ids else 1


def _has_tracked(p_el) -> bool:
    # iter 覆盖全部后代：段内 w:ins/w:del 与段落标记修订（pPr/rPr 内）一并检出
    return any(e.tag in (qn("w:ins"), qn("w:del")) for e in p_el.iter())


def _text_runs(p_el) -> list:
    """参与文本定位的 run 流：直属 w:r + w:ins 内 w:r（顺序），跳过 w:del 子树。

    同段多轮修订需要穿过本轮已落的修订标记定位（嵌套 ins>del 合法，Word
    显示为对插入内容的再修订）；定位基准 = 接受视角文本。
    """
    out: list = []

    def walk(node):
        for ch in node:
            if ch.tag == qn("w:del"):
                continue
            if ch.tag == qn("w:r"):
                out.append(ch)
                continue
            walk(ch)

    walk(p_el)
    return out


def _run_text(r) -> str:
    return "".join(t.text or "" for t in r.findall(qn("w:t")))


def _set_run_text(r, text: str) -> None:
    """run 文本重设：保留首个 w:t（带 preserve），其余 w:t 清空。"""
    ts = r.findall(qn("w:t"))
    if not ts:
        t = parse_xml(f'<w:t {nsdecls("w")} xml:space="preserve">{escape(text)}</w:t>')
        r.append(t)
        return
    ts[0].text = text
    ts[0].set(qn("xml:space"), "preserve")
    for extra in ts[1:]:
        extra.text = ""


def _split_run_head(run, keep: int):
    """run 截为前 keep 字符，剩余文本生成新 run 插在其后（拷贝全部属性）。"""
    text = _run_text(run)
    tail = text[keep:]
    _set_run_text(run, text[:keep])
    if not tail:
        return run
    new_r = deepcopy(run)
    _set_run_text(new_r, tail)
    run.addnext(new_r)
    return new_r


def _tracked_replace(para, old: str, new: str, rev_id: int) -> None:
    """段内定向替换（接受视角定位，可穿过已有修订标记）：每个匹配 run 在原
    位置包独立 w:del（w:t→w:delText；ins 内 run 变 ins>del 合法嵌套），新文本
    以首匹配 run 的格式包 w:ins 插在末个 del 之后。"""
    p_el = para._p
    runs = _text_runs(p_el)
    full = "".join(_run_text(r) for r in runs)
    pos = full.find(old)
    if pos < 0:
        raise ValueError(f"段落内未找到期望文本「{old[:60]}」")
    end = pos + len(old)
    # 字符偏移 → run 序列，首尾拆分对齐匹配边界
    off = 0
    match_runs: list = []
    for r in runs:
        rlen = len(_run_text(r))
        if rlen == 0 or off + rlen <= pos or off >= end:
            off += rlen
            continue
        if off < pos:
            r = _split_run_head(r, pos - off)
            off = pos
        run_end = off + len(_run_text(r))
        if run_end > end:
            _split_run_head(r, end - off)
        match_runs.append(r)
        off = run_end
    if not match_runs:
        raise ValueError("匹配区间为空")
    date = _now_iso()
    # per-run 原位包 del：匹配可能横跨「已有 w:ins 内容 + 原文」（二轮修订常态），
    # run 的父级不一——每个 run 在自己原位置包独立 w:del（ins 内变 ins>del 合法
    # 嵌套、正文留 p>del），拒绝视角原文完整；若整批共用一个 del 挂在首 run
    # 位置，会把正文 run 挪进 ins 子树、拒绝修订后原文凭空消失（自校验必拒）。
    last_del = None
    for r in match_runs:
        for t in r.findall(qn("w:t")):
            t.tag = qn("w:delText")
        del_el = parse_xml(f'<w:del {nsdecls("w")} w:id="{rev_id}" w:author="{_AUTHOR}" w:date="{date}"/>')
        r.addprevious(del_el)
        del_el.append(r)  # move 出原位置、原父级原顺序
        last_del = del_el
    rpr = match_runs[0].find(qn("w:rPr"))
    rpr_xml = rpr.xml if rpr is not None else ""
    ins_el = parse_xml(
        f'<w:ins {nsdecls("w")} w:id="{rev_id + 1}" w:author="{_AUTHOR}" w:date="{date}">'
        f'<w:r>{rpr_xml}<w:t xml:space="preserve">{escape(new)}</w:t></w:r></w:ins>'
    )
    last_del.addnext(ins_el)


def _tracked_insert_after(anchor_p_el, text: str, rev_id: int, style_id: str | None = None):
    """新段落插在锚段（lxml 元素）之后，段落标记与内容均为插入修订（拒绝修订=
    整段消失）。返回新段元素——同段连续 insert_after 以返回值为下一次的锚
    （否则 addnext 紧跟定位段，同批多条会倒序）。style_id 非空时挂该样式
    （w:pStyle 挂 styleId：正文段=Tender Body，封面行=Tender Cover/Sub，
    由调用方按样式名解析，随锚段所在文档的模板有无自适应）。"""
    date = _now_iso()
    pstyle = f'<w:pStyle w:val="{style_id}"/>' if style_id else ""
    new_p = parse_xml(
        f'<w:p {nsdecls("w")}>'
        f'<w:pPr>{pstyle}<w:rPr><w:ins w:id="{rev_id}" w:author="{_AUTHOR}" w:date="{date}"/></w:rPr></w:pPr>'
        f'<w:ins w:id="{rev_id + 1}" w:author="{_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:ins></w:p>'
    )
    anchor_p_el.addnext(new_p)
    return new_p


def _tracked_fill(para, text: str, rev_id: int) -> None:
    """空格子填入：文本以 w:ins 追加进段落（拒绝修订=回到空格子）。

    只用于接受视角为空的表格单元格——段落本身存在（python-docx 建格自带空段），
    追加插入修订即可；沿用格子既有段落属性（对齐等）。
    """
    date = _now_iso()
    ins_el = parse_xml(
        f'<w:ins {nsdecls("w")} w:id="{rev_id}" w:author="{_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:ins>'
    )
    para._p.append(ins_el)


def _tracked_delete(para, rev_id: int) -> None:
    """段落删除修订：全部 run（含 w:ins 内，嵌套=删除先前的插入）文本转
    删除文本，段落标记本身也标删除（接受修订时段落真正消失；pPr/rPr 的
    w:del 置于最前——CT_ParaRPr 顺序）。"""
    p_el = para._p
    date = _now_iso()
    for r in list(p_el.iter(qn("w:r"))):  # list 快照：边遍历边移动
        del_el = parse_xml(f'<w:del {nsdecls("w")} w:id="{rev_id}" w:author="{_AUTHOR}" w:date="{date}"/>')
        r.addprevious(del_el)
        del_el.append(r)
        for t in r.findall(qn("w:t")):
            t.tag = qn("w:delText")
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        ppr = parse_xml(f'<w:pPr {nsdecls("w")}/>')
        p_el.insert(0, ppr)
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = parse_xml(f'<w:rPr {nsdecls("w")}/>')
        ppr.insert(0, rpr)
    rpr.insert(0, parse_xml(
        f'<w:del {nsdecls("w")} w:id="{rev_id}" w:author="{_AUTHOR}" w:date="{date}"/>'
    ))


def _collect_rejected(node, parts: list) -> None:
    """「拒绝全部修订」视角收文本：跳过 w:ins 子树；w:t 与 w:delText 均计入。"""
    for ch in node:
        if ch.tag == qn("w:ins"):
            continue
        if ch.tag in (qn("w:t"), qn("w:delText")):
            parts.append(ch.text or "")
        _collect_rejected(ch, parts)


def _flatten_rejected(doc: Document) -> str:
    """「拒绝全部修订」视角收全文（正文段落 + 表格单元格段落，顺序稳定）。

    表格部分按 表格序→行序→格序 展开——格编辑写坏修订标记（拒绝视角文本
    变化）与正文段落一样触发落盘前自校验拒绝。合并格在 row.cells 里重复
    出现，重复收集对称存在于修订前后两侧，不影响相等性比较。
    """
    def _para_rejected(p_el) -> str | None:
        ppr = p_el.find(qn("w:pPr"))
        rpr = ppr.find(qn("w:rPr")) if ppr is not None else None
        if rpr is not None and rpr.find(qn("w:ins")) is not None:
            return None  # 段落标记为插入——拒绝修订后整段不存在
        parts: list[str] = []
        _collect_rejected(p_el, parts)
        return "".join(parts)

    out: list[str] = []
    for p in doc.paragraphs:
        text = _para_rejected(p._p)
        if text is not None:
            out.append(text)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    text = _para_rejected(p._p)
                    if text is not None:
                        out.append(text)
    return "\n".join(out)


def _collect_accepted(node, parts: list) -> None:
    """「接受全部修订」视角收文本：w:ins 内容计入、w:del 子树跳过、w:delText 不计。"""
    for ch in node:
        if ch.tag == qn("w:del"):
            continue
        if ch.tag == qn("w:t"):
            parts.append(ch.text or "")
        _collect_accepted(ch, parts)


def _accepted_text(p_el) -> str:
    parts: list[str] = []
    _collect_accepted(p_el, parts)
    return "".join(parts)


# ---------- 视图与图片迁移 ----------

def _comment_texts(doc: Document) -> dict[int, str]:
    """comment id → 批注文本（无批注部件返回空——读视图/清点不因批注缺失报错）。

    python-docx 的 Document.comments 在无部件时懒创建空部件（不落盘无副作用）。
    """
    try:
        return {c.comment_id: (c.text or "").strip() for c in doc.comments if (c.text or "").strip()}
    except Exception:
        return {}


def view_lines(doc: Document) -> list[str]:
    view = []
    comment_texts = _comment_texts(doc)
    paras = doc.paragraphs
    for i, para in enumerate(paras, 1):
        style = para.style.name if para.style is not None else "?"
        imgs = len(para._p.findall(".//" + qn("a:blip")))
        bits = f"[P{i}]（{style}）"
        if imgs:
            bits += f"〔图×{imgs}〕"
        ppr = para._p.find(qn("w:pPr"))
        rpr = ppr.find(qn("w:rPr")) if ppr is not None else None
        para_deleted = rpr is not None and rpr.find(qn("w:del")) is not None
        if para_deleted:
            bits += "〔删除修订：接受后此段消失〕"
        elif _has_tracked(para._p):
            bits += "〔已含修订标记〕"
        # 本段锚定的待办批注（commentRangeStart 是段落直接子元素；id 对不上批注部件=陈旧引用跳过）
        notes = [
            t for m in para._p.findall(qn("w:commentRangeStart"))
            if (raw := m.get(qn("w:id")) or "").isdigit() and (t := comment_texts.get(int(raw)))
        ]
        if notes:
            shown = "；".join(n[:40] + ("…" if len(n) > 40 else "") for n in notes)
            bits += f"〔批注：{shown}〕"
        # python-docx 的 .text 不含修订标记内容——视图按「接受全部修订后」文本展示
        text = _accepted_text(para._p) or "（空段落）"
        if len(text) > _VIEW_TEXT_LIMIT:
            text = text[:_VIEW_TEXT_LIMIT] + f"…（截断，全段 {len(text)} 字，请在 Word 中查看）"
        view.append(bits + text)
    for ti, t in enumerate(doc.tables, 1):
        view.append(
            f"[T{ti}] 表格 {len(t.rows)}行×{len(t.columns)}列"
            "（单元格按 R行C列 寻址：docx_section_revise 传 table/row/col；合并格标「同左/同上」）"
        )
        prev_cells: list = []
        for ri, row in enumerate(t.rows, 1):
            bits: list[str] = []
            last_tc = None
            for ci, cell in enumerate(row.cells, 1):
                tc = cell._tc
                above = prev_cells[ci - 1] if ci <= len(prev_cells) else None
                if tc is last_tc:
                    bits.append(f"C{ci}=（同左合并格）")
                elif above is not None and tc is above._tc:
                    bits.append(f"C{ci}=（同上合并格）")
                else:
                    text = " / ".join(
                        s for p in cell.paragraphs if (s := _accepted_text(p._p).strip())
                    ) or "（空）"
                    if len(text) > _CELL_TEXT_LIMIT:
                        text = text[:_CELL_TEXT_LIMIT] + "…（截断）"
                    bits.append(f"C{ci}={text}")
                last_tc = tc
            view.append(f"[T{ti}] R{ri}：" + " ".join(bits))
            prev_cells = list(row.cells)
    head = f"共 {len(paras)} 个段落、{len(doc.tables)} 个表格（段落按 P 编号，表格按 T 编号）"
    if comment_texts:
        head += f"，待办批注 {len(comment_texts)} 条"
    view.insert(0, head)
    return view


def _migrate_images(src_doc: Document, dst_doc: Document, element) -> int:
    """把元素引用的源文档图片登记进目标文档并改写引用（按内容去重、partname 自动避让）。"""
    moved = 0
    for blip in element.findall(".//" + qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        if not rid:
            continue
        try:
            image_part = src_doc.part.related_parts[rid]
            blob = image_part.blob
        except KeyError:
            continue
        try:
            new_rid, _image = dst_doc.part.get_or_add_image(BytesIO(blob))
        except Exception:
            continue  # 图片部件不可读：跳过（保留旧引用=裂图）——跨包挂外部 part 会损坏序列化
        blip.set(qn("r:embed"), new_rid)
        moved += 1
    return moved


def _sig_shingles(text: str) -> set[str]:
    """强归一化（只留中文与字母数字）的 10 字 shingle 集合：重复注入探测用，
    格式符号（表格竖线/视图标签/列表前缀）不参与比对。"""
    s = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]", "", text)
    return {s[i : i + 10] for i in range(max(0, len(s) - 9))}


def _strip_inner_sectpr(el) -> None:
    """剥段落 pPr 内的分节符：素材/节文件自带的分节属性（纸向/页边距/页码
    重起）随元素拷贝会中途生效、突变节文件版式（2026-09-08 实证：横向页设置
    进入节文件）。文档级分节只归节文件自身的文末 sectPr（不在拷贝面）。"""
    ppr = el.find(qn("w:pPr"))
    if ppr is None:
        return
    for sect in ppr.findall(qn("w:sectPr")):
        ppr.remove(sect)


_BASE_TEMPLATE = Path(__file__).resolve().parent.parent / "resources" / "tender_base_template.docx"
_BODY_STYLE_NAME = "Tender Body"  # 版式文件自定义正文样式（1.5 倍行距+首行缩进 2 字符）
_COVER_NODE_NAME = "封面"  # 树首封面节点的约定名（合册按清洗后标题识别，tender-outline 定下）
TEMPLATE_SETTING_KEY = "docx_template"  # app_settings 键：默认版式的用户文件名（空=内置基准）
BUILTIN_TEMPLATE_KEY = "__builtin__"  # 内置版式寻址键（版式库 API 与 LLM 工具共用）
BUILTIN_TEMPLATE_NAME = "内置标书基准版式"  # 用户可见名（2026-09-09「模板库」改名「版式库」随改）


def templates_dir() -> Path:
    """用户版式文件目录（data/templates/，版式库 API 与工具共用）。"""
    from .. import config

    d = config.data_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def active_template_name() -> str | None:
    """默认版式的用户文件名；None=内置基准生效。"""
    from .. import db

    return (db.get_setting(TEMPLATE_SETTING_KEY) or "").strip() or None


def list_templates_info() -> list[dict]:
    """版式库清单（读侧真值，HTTP API 与 list_templates 工具同源消费）：
    内置恒首位 + 用户版式 mtime 降序；active=命中默认位（未设默认时内置即
    默认）。stat 竞态（glob 到 stat 之间文件被删）跳行不抛。"""
    active = active_template_name()

    def _row(p: Path, *, key: str, name: str, builtin: bool) -> dict:
        st = p.stat()
        return {
            "name": name,
            "key": key,
            "builtin": builtin,
            "active": key == active or (builtin and active is None),
            "size": st.st_size,
            "mtime": st.st_mtime,
        }

    out = [_row(_BASE_TEMPLATE, key=BUILTIN_TEMPLATE_KEY, name=BUILTIN_TEMPLATE_NAME, builtin=True)]
    items: list[tuple[float, Path]] = []
    for p in templates_dir().glob("*.docx"):
        try:
            items.append((p.stat().st_mtime, p))
        except OSError:
            continue
    for _, p in sorted(items, reverse=True):
        try:
            out.append(_row(p, key=p.name, name=p.stem, builtin=False))
        except OSError:
            continue
    return out


def _active_template_path() -> Path:
    """默认版式：app_settings 命中的用户版式文件（data/templates/）优先，
    否则内置基准。用户版式文件被误删等异常静默回落内置（探测不报错——
    版式缺失不该打断建节）。"""
    try:
        name = active_template_name()
        if name:
            p = templates_dir() / name
            if p.is_file():
                return p
    except Exception:
        pass
    return _BASE_TEMPLATE


def _blank_from(template: Path) -> Document:
    """从指定版式文件起建空白文档（剥离自带的样式示例段，只留 sectPr）。"""
    doc = Document(str(template))
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    return doc


def _new_document() -> Document:
    """从默认版式起建（格式与内容分离：版式全部活在版式文件 styles.xml；
    默认位=app_settings 的用户版式，缺省内置基准，由 scripts/
    make_base_template.py 生成维护；代码只挂样式名）。

    版式文件 body 带样式示例段（打开可直观预览/改版式），起建时整段剥离
    （body 只留 sectPr=版面/页脚），示例永不进入节文件与合册。版式文件缺失
    时回落 python-docx 默认模板（英文版式，仅防打包漏带资源，不作为常态）。"""
    tpl = _active_template_path()
    if tpl.is_file():
        return _blank_from(tpl)
    return Document()


def _body_style(doc: Document):
    """Tender Body 样式对象，版式文件不带时返回 None（正文段回落 Normal，
    建节不因换版式缺样式名而失败）。"""
    try:
        return doc.styles[_BODY_STYLE_NAME]
    except KeyError:
        return None


def _style_id_by_name(doc: Document, name: str) -> str | None:
    """按样式名解析 styleId（w:pStyle 的 w:val 挂的是 styleId 不是样式名），
    无此样式返回 None——调用方回落默认样式，换版式缺样式名不失败。"""
    try:
        return doc.styles[name].element.get(qn("w:styleId"))
    except KeyError:
        return None


def _ensure_body_style(p_el, style_id: str) -> None:
    """无样式引用的素材正文段挂版式正文样式（素材拷贝归顺版式，2026-09-08
    用户拍板：素材归顺、招标格式件保真）：获得标书正文缩进/行距/对齐；
    已带样式引用（内置标题自动吃宿主定义、自定义样式走保真迁移）与表格整表
    保持原样——某段自定义素材该不该归顺是语义判断，归写作流程的改写适配
    步骤，机械层不做。"""
    ppr = p_el.find(qn("w:pPr"))
    if ppr is None:
        ppr = parse_xml(f'<w:pPr {nsdecls("w")}/>')
        p_el.insert(0, ppr)
    if ppr.find(qn("w:pStyle")) is None:
        ppr.insert(0, parse_xml(f'<w:pStyle {nsdecls("w")} w:val="{style_id}"/>'))


# ---------- 样式与自动编号定义迁移 ----------

def _find_by_id(root, tag: str, attr: str, val: str):
    for e in root.findall(qn(tag)):
        if e.get(qn(attr)) == val:
            return e
    return None


def _merge_missing_numbering(src_doc: Document, dst_doc: Document, elements) -> int:
    """编号定义迁移：按定义内容判定沿用，id 冲突时重映射——拷贝元素的编号引用
    解析到与源文档相同的定义，并改写 elements 上的引用。

    numbering id 只是文档内部门牌号：建节模板自带 numId 1-9/abstractNumId
    0-8，素材（历史标书）的 id 同样从小数字分配——同 id 不代表同定义，沿用
    目标定义会让中文编号静默变圆点、多级编号错位（2026-09-08 review 实证）。
    迁移规则：
    - dst 缺该 numId：原 id 迁入（abstractNumId 同缺则原 id 齐迁；abstractNumId
      相撞且定义不同则 abstractNum 换新 id 迁入，num 改指向新 id）；
    - dst 已有同 numId：定义内容等价才沿用；不同则分配未用的新 numId 迁入
      源定义并改写引用；
    - 同一次调用内同 numId 共享映射（块内列表编号连续）；跨调用不复用——
      不同素材块的同定义列表保持独立序列（各自从 1 开始，贴近原文语义）；
    - w:numStyleLink（num 链编号样式）不重映射，沿用目标定义——编号样式
      多为内建、语义跨文档一致。
    """
    try:
        src_root = src_doc.part.numbering_part.element
        dst_root = dst_doc.part.numbering_part.element
    except Exception:
        return 0  # 任一侧无 numbering 部件 = 无编号可迁
    used = sorted({
        n.get(qn("w:val"))
        for el in elements
        for n in el.findall(".//" + qn("w:numId"))
        if n.get(qn("w:val"))
    })
    if not used:
        return 0

    def norm_num(num_el) -> bytes:
        # 剥 numId 属性与 abstractNumId 引用（文档内部门牌，非定义内容）
        e = deepcopy(num_el)
        e.attrib.pop(qn("w:numId"), None)
        ref = e.find(qn("w:abstractNumId"))
        if ref is not None:
            e.remove(ref)
        return etree.tostring(e)

    def norm_abs(abs_el) -> bytes:
        # 剥 id 属性与 nsid/tmpl（Word 各文档独立生成的随机 GUID，比对噪音）
        e = deepcopy(abs_el)
        e.attrib.pop(qn("w:abstractNumId"), None)
        for t in ("w:nsid", "w:tmpl"):
            for x in e.findall(qn(t)):
                e.remove(x)
        return etree.tostring(e)

    def def_key(root, nid: str) -> tuple[bytes, bytes] | None:
        num = _find_by_id(root, "w:num", "w:numId", nid)
        if num is None:
            return None
        ref = num.find(qn("w:abstractNumId"))
        abs_e = (
            _find_by_id(root, "w:abstractNum", "w:abstractNumId", ref.get(qn("w:val")))
            if ref is not None else None
        )
        return (norm_num(num), norm_abs(abs_e) if abs_e is not None else b"")

    dst_nums = {n.get(qn("w:numId")): n for n in dst_root.findall(qn("w:num"))}
    dst_abs = {a.get(qn("w:abstractNumId")): a for a in dst_root.findall(qn("w:abstractNum"))}

    def _ints(ids) -> set[int]:
        out = set()
        for k in ids:
            try:
                out.add(int(k))
            except (TypeError, ValueError):
                continue
        return out

    free_num = max(_ints(dst_nums), default=0) + 1
    free_abs = max(_ints(dst_abs), default=0) + 1

    def add_abs(src_aid: str, new_aid: str | None = None) -> str:
        """迁 abstractNum（new_aid 缺省保留原 id）；abstractNum 必须排在全部 num 之前。"""
        a = deepcopy(_find_by_id(src_root, "w:abstractNum", "w:abstractNumId", src_aid))
        aid = new_aid or src_aid
        a.set(qn("w:abstractNumId"), aid)
        first_num = dst_root.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(a)
        else:
            dst_root.append(a)
        dst_abs[aid] = a
        return aid

    remap: dict[str, str] = {}
    moved = 0
    for nid in used:
        key = def_key(src_root, nid)
        if key is None:
            continue  # 源侧定义缺失（悬挂引用）——无从迁
        src_num = _find_by_id(src_root, "w:num", "w:numId", nid)
        if src_num.find(qn("w:numStyleLink")) is not None:
            continue  # 编号样式链场景不重映射（见 docstring）
        if nid in dst_nums and def_key(dst_root, nid) == key:
            remap[nid] = nid  # id 相撞但定义等价：沿用目标
            continue
        ref = src_num.find(qn("w:abstractNumId"))
        src_aid = ref.get(qn("w:val")) if ref is not None else None
        new_aid = src_aid
        if src_aid:
            existing = dst_abs.get(src_aid)
            if existing is None:
                add_abs(src_aid)
            elif norm_abs(existing) != key[1]:
                new_aid = add_abs(src_aid, str(free_abs))  # 相撞且定义不同 → 新 id 迁入
                free_abs += 1
            # 相撞但定义等价 → 复用目标既有 abstractNum
        new_num = deepcopy(src_num)
        new_nid = nid
        if nid in dst_nums:
            while str(free_num) in dst_nums:
                free_num += 1
            new_nid = str(free_num)
            free_num += 1
        new_num.set(qn("w:numId"), new_nid)
        if src_aid and new_aid != src_aid:
            new_num.find(qn("w:abstractNumId")).set(qn("w:val"), new_aid)
        dst_root.append(new_num)
        dst_nums[new_nid] = new_num
        remap[nid] = new_nid
        moved += 1

    # 改写拷贝元素上的引用（含迁入的样式定义里的 numPr——调用方传副本进来）
    for el in elements:
        for n in el.findall(".//" + qn("w:numId")):
            v = n.get(qn("w:val"))
            if v in remap and remap[v] != v:
                n.set(qn("w:val"), remap[v])
    return moved


def _merge_missing_styles(src_doc: Document, dst_doc: Document, elements) -> int:
    """把元素引用而目标缺定义的样式（段落/字符/表格样式）从源拷过来。

    元素级拷贝沿用源文档样式引用——目标缺定义时 Word 回退默认样式，自定义样式
    （带编号的标题、特殊字体段落）会丢观感。依赖链（basedOn/link/next 指向的
    样式、样式自身的编号引用）递归补齐；源也没有的（如内建样式 id 差异）不硬造。
    """
    src_root = src_doc.styles.element
    dst_root = dst_doc.styles.element
    have = {s.get(qn("w:styleId")) for s in dst_root.findall(qn("w:style"))}
    pending = {
        r.get(qn("w:val"))
        for el in elements
        for tag in ("w:pStyle", "w:rStyle", "w:tblStyle")
        for r in el.findall(".//" + qn(tag))
        if r.get(qn("w:val"))
    }
    moved = 0
    while pending:
        sid = pending.pop()
        if not sid or sid in have:
            continue
        src_style = _find_by_id(src_root, "w:style", "w:styleId", sid)
        if src_style is None:
            continue
        new_style = deepcopy(src_style)
        dst_root.append(new_style)
        have.add(sid)
        moved += 1
        for tag in ("w:basedOn", "w:link", "w:next"):
            ref = src_style.find(qn(tag))
            val = ref.get(qn("w:val")) if ref is not None else None
            if val and val not in have:
                pending.add(val)
        # 传迁入副本：id 冲突重映射时样式定义里的 numPr 引用同步改写
        _merge_missing_numbering(src_doc, dst_doc, [new_style])
    return moved


def _merge_missing_comments(src_doc: Document, dst_doc: Document, elements) -> int:
    """把拷贝元素引用的源文档批注迁入目标文档（id 重映射，与编号迁移同构）。

    随段落 deepcopy 拷入的 commentRangeStart/End/commentReference 引用的是源文档
    comments part 的 id——不迁移则批注悬空丢失。只迁拷贝元素实际引用的条目（跳过
    被丢弃的节标题段上的锚），源里查不到的陈旧标记就地摘除防悬空。
    """
    markers = (qn("w:commentRangeStart"), qn("w:commentRangeEnd"), qn("w:commentReference"))
    nodes: list = []
    refs: set[str] = set()
    for el in elements:
        for m in el.iter(*markers):
            nodes.append(m)
            refs.add(m.get(qn("w:id")) or "")
    if not nodes:
        return 0
    id_map: dict[str, str] = {}
    for cid in sorted(refs):
        if not cid.isdigit():
            continue
        src_c = src_doc.comments.get(int(cid))
        if src_c is None:
            continue
        new_c = dst_doc.comments.add_comment(
            text=src_c.text or "", author=src_c.author or _COMMENT_AUTHOR, initials=src_c.initials or "AI"
        )
        id_map[cid] = str(new_c.comment_id)
    for m in nodes:
        old = m.get(qn("w:id")) or ""
        if old in id_map:
            m.set(qn("w:id"), id_map[old])
        else:
            m.getparent().remove(m)  # 陈旧/悬空标记：摘除防引用错乱
    return len(id_map)


# ---------- 工具 ----------


def _tool_guard(label: str):
    """工具体兜底：意外异常（损坏 docx、IO 失败等）转失败文案返回，不打崩 run。

    工具铁律：外部输入（用户上传的招标/素材原件）半截或损坏是现实输入，
    Document()/save 抛出的非 ValueError 异常必须转字符串；具体的人话报错
    （ValueError 分支）优先于本兜底。
    """

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                return f"[{label}失败] {type(e).__name__}: {e}"

        return wrapper

    return deco


@tool
@_tool_guard("创建")
def docx_section_create(path: str, title: str, paragraphs: str = "", replace: bool = False) -> str:
    """创建正文节 docx 文件（work/body/ 下，每节一文件）。

    用途：tender-body 正文阶段为一节建档（标题 + 可选初始段落）。已存在默认不
    覆盖（防误清已写内容）；**重写本节传 replace=true**（用户裁决的重写范围），
    旧版自动入恢复点栈（保留最近 3 版，文件名不变旁挂 .restorepoints/ 目录）。
    Args:
        path: 相对任务 work/ 的路径，如 body/技术部分/3.1 需求分析.docx（自动补 .docx）
        title: 节标题（写入文档一级标题样式，进目录域）
        paragraphs: 可选初始段落，换行分隔（推理撰写/格式跟随模式可一次性带全文）
        replace: 已存在的节重写时传 true；默认 false 不覆盖
    """
    task_id = _task_id()
    if not task_id:
        return "[创建失败] 当前会话未归属任务"
    try:
        dst, rel = _dest_path(task_id, path, must_exist=False)
    except ValueError as e:
        return f"[创建失败] {e}"
    replaced = False
    if dst.exists():
        if not replace:
            return (
                f"[创建失败] work/{rel} 已存在（不覆盖已写内容）——"
                "确属重写范围请传 replace=true（旧版自动存恢复点）"
            )
        _rotate_restore_point(dst)
        replaced = True
    doc = _new_document()
    doc.add_heading(title.strip() or "未命名", 1)
    body_style = _body_style(doc)
    for text in paragraphs.split("\n"):
        if text.strip():
            doc.add_paragraph(text.strip(), style=body_style.name if body_style else None)
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(dst)
    n_init = sum(1 for t in paragraphs.split("\n") if t.strip())
    head = "[已重建] " if replaced else "[已创建] "
    return (
        f"{head}work/{rel}（标题「{title.strip()}」，正文 {n_init} 段）\n"
        "下一步：贴素材底稿用 docx_material_inject；直接写内容/修订用 docx_section_revise。"
    )


@tool
@_tool_guard("读取")
def docx_section_read(path: str) -> str:
    """读取正文节 docx 的文本视图（段落编号 P1..Pn + 样式 + 图片/修订标记，表格 T1..Tm）。

    用途：写或修订前先读视图拿段落序号；docx_section_revise 的 para 序号以本视图为准。
    """
    task_id = _task_id()
    if not task_id:
        return "[读取失败] 当前会话未归属任务"
    try:
        dst, rel = _dest_path(task_id, path, must_exist=True)
    except ValueError as e:
        return f"[读取失败] {e}"
    doc = Document(str(dst))
    return "\n".join(view_lines(doc))


@tool
@_tool_guard("注入")
def docx_material_inject(block_id: str, dest: str) -> str:
    """把写作素材块原样注入正文节 docx（元素级拷贝：段落/表格含合并单元格、图片零转写）。

    用途：素材修订模式的底稿落地——检索（search_references）命中块后，用其块 id
    （blk_ 开头）把历史章节整体拷进目标节文件，格式与内容保真，后续用
    docx_section_revise 定向修订。注入内容不带修订标记（干净底稿，修订才标记）。
    仅支持 docx 原件的素材（历史标书大头）；pdf 等原件无可注入元素。
    Args:
        block_id: 素材块 id（search_references 命中的引用键 mt:<fid>:b:<块id> 中的块 id）
        dest: 目标节文件（须已用 docx_section_create 创建）
    """
    task_id = _task_id()
    if not task_id:
        return "[注入失败] 当前会话未归属任务"
    b = db.mt_get_block(block_id.strip())
    if not b:
        return "[注入失败] 素材块不存在（可能已被删除，请重新检索选用）"
    f = db.mt_get_file(b["file_id"])
    if not f:
        return "[注入失败] 素材文件记录缺失"
    src_path = materials_lib.mt_files_dir() / f["file_name"]
    if src_path.suffix.lower() != ".docx":
        return f"[注入失败] 素材「{f['file_name']}」原件不是 docx（{src_path.suffix or '无后缀'}），没有可保真注入的元素；请以文本方式参考该素材自行撰写"
    try:
        dst, rel = _dest_path(task_id, dest, must_exist=True)
    except ValueError as e:
        return f"[注入失败] {e}"
    if not src_path.is_file():
        return "[注入失败] 素材原件文件缺失（可能已被删除）"
    element_map = materials_lib.read_element_map(f["file_name"])
    if element_map is None:
        # 旧解析未产映射：幂等重跑补产。补跑前后比对 md——「同原件确定性解析、
        # 锚定不变」只在解析代码不变时成立，解析升级会使行号漂移、旧块勾选区间
        # 错位（拷错元素而非报错），变了拒绝注入、点名重勾（探测+用户裁决）
        md_path = materials_lib.mt_parse_paths(f["file_name"])[0]
        old_md = md_path.read_text(encoding="utf-8") if md_path.is_file() else None
        materials_lib.run_parse(f["id"])
        element_map = materials_lib.read_element_map(f["file_name"])
        if (
            element_map is not None
            and old_md is not None
            and old_md != md_path.read_text(encoding="utf-8")
        ):
            return (
                "[注入失败] 素材重新解析后内容行号已变化，现有素材块的勾选区间会错位"
                "——请在写作素材库重新确认该文件的勾选（删除重建相关块）后再注入"
            )
    if element_map is None:
        return "[注入失败] 素材元素映射不可用（解析未产出），请删除后重新上传该素材"
    # 同块重复注入探测：注入是 append 语义，重复=内容翻倍。块特征 shingle 已大量
    # 出现在节文件接受视角文本中=已注入过（硬拦；概率防线，注入后大幅改写会漏拦
    # ——validate_body 的素材使用率另有兜底）
    block_sections = (materials_lib.block_content(b["id"]) or {}).get("sections") or []
    bs = _sig_shingles("\n".join(sec.get("text") or "" for sec in block_sections))
    if len(bs) >= 5:
        cur = "\n".join(section_text_lines(Document(str(dst))))
        if len(bs & _sig_shingles(cur)) / len(bs) >= 0.6:
            return (
                f"[注入失败] 素材块《{b.get('title') or b['id']}》的内容已大量出现在 "
                f"work/{rel}（已注入过）——注入是追加语义，重复注入会翻倍内容；"
                "确需重新贴底稿请先重建节文件（docx_section_create 传 replace=true）"
            )
    ranges = b.get("ranges") or []  # db 层已反序列化为 [[s,e],…]
    idx = sorted({
        el for el, s, e in element_map
        if isinstance(el, int) and any(
            isinstance(r, (list, tuple)) and len(r) == 2 and r[0] <= e and r[1] >= s
            for r in ranges
        )
    })
    if not idx:
        return "[注入失败] 素材块区间未映射到任何 docx 元素（可能只勾选了空段落）"
    src = Document(str(src_path))
    dst_doc = Document(str(dst))
    body_style = _body_style(dst_doc)
    body_style_id = body_style.element.get(qn("w:styleId")) if body_style else None
    children = list(src.element.body.iterchildren())
    sect = dst_doc.element.body.find(qn("w:sectPr"))
    n_para = n_tbl = n_img = 0
    copied: list = []
    for i in idx:
        if i >= len(children):
            continue
        el = children[i]
        if el.tag.split("}")[-1] not in ("p", "tbl"):
            continue
        new_el = deepcopy(el)
        _strip_inner_sectpr(new_el)
        if new_el.tag == qn("w:p") and body_style_id:
            _ensure_body_style(new_el, body_style_id)
        n_img += _migrate_images(src, dst_doc, new_el)
        if sect is not None:
            sect.addprevious(new_el)
        else:
            dst_doc.element.body.append(new_el)
        copied.append(new_el)
        if el.tag.split("}")[-1] == "tbl":
            n_tbl += 1
        else:
            n_para += 1
    if n_para + n_tbl == 0:
        return "[注入失败] 映射区间内没有可注入的段落/表格元素"
    n_style = _merge_missing_styles(src, dst_doc, copied)
    n_num = _merge_missing_numbering(src, dst_doc, copied)
    dst_doc.save(dst)
    # AI 引用打点：注入落盘成功才算一次引用（容错——打点失败不影响注入结果）
    try:
        db.mt_touch_blocks([b["id"]])
    except Exception:
        pass
    return (
        f"[已注入] 《{b.get('title') or '素材块'}》→ work/{rel}：段落 {n_para} 个、"
        f"表格 {n_tbl} 张、图片 {n_img} 张（内容与格式逐字节取自素材原件，样式引用沿用源文档）"
        + (f"，随迁样式定义 {n_style} 个、编号定义 {n_num} 组" if n_style or n_num else "")
        + "\n下一步：docx_section_read 拿段落序号 → docx_section_revise 定向修订"
        "（旧项目名/公司名/参数按本次承诺清单改）→ check_name_residue 扫残留。"
    )


@tool
@_tool_guard("注入")
def docx_source_inject(source: str, dest: str, lines: str = "") -> str:
    """把任务 sources/ 里招标原件的 docx 内容原样拷进正文节（元素级：段落/表格/图片零转写）。

    用途：格式跟随与格式件节点（投标函/授权书/投标一览表等）——招标规定的格式
    原样拷入目标节文件（格式逐字节保真，不重排不走样），再用 docx_section_revise
    填空适配（表格空格子 fill、旧值 replace；承诺值出自清单、未定值【待补：…】）。
    仅支持 docx 原件；pdf 等无可拷元素，按该来源的解析文本自行成形。注入内容
    不带修订标记（干净底稿，填空改值才标记）。
    Args:
        source: 任务 sources/ 里的文件名（如 招标文件.docx、格式附件-投标函.docx；
                目录部分会被剥掉，只在 sources/ 内寻址）
        dest: 目标节文件（须已用 docx_section_create 创建）
        lines: 可选行号区间 "起-止"（该来源解析 md 的行号闭区间，取自
               work/parse/<文件名>/<文件名>.outline.json 的 start_line/end_line 或
               analysis 表出处列，可带 L 前缀如 L412-L430）；留空 = 整份文件
               （独立格式附件的常态用法）
    """
    task_id = _task_id()
    if not task_id:
        return "[注入失败] 当前会话未归属任务"
    name = (source or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return "[注入失败] 未指定来源文件"
    sroot = sources_dir(task_id).resolve()
    src_path = (sroot / name).resolve()
    if sroot != src_path and sroot not in src_path.parents:
        return f"[注入失败] 路径越界：{source}"
    if not src_path.is_file():
        return (
            f"[注入失败] sources/ 下没有文件：{name}"
            "（文件名以 check_pipeline_state 的 [sources]/[candidates] 段为准）"
        )
    if src_path.suffix.lower() != ".docx":
        return (
            f"[注入失败] 「{name}」原件不是 docx（{src_path.suffix or '无后缀'}），"
            "没有可保真拷贝的元素；请按该来源的解析文本（work/parse）自行成形本节"
        )
    lo = hi = None
    if (lines or "").strip():
        try:
            a, _, b = (lines or "").strip().partition("-")
            lo, hi = int(a.strip().lstrip("Ll")), int(b.strip().lstrip("Ll"))
        except ValueError:
            return "[注入失败] lines 须为「起-止」行号（如 412-430 或 L412-L430），取自 outline.json 或 analysis 出处列"
        if lo > hi:
            lo, hi = hi, lo
    try:
        dst, rel = _dest_path(task_id, dest, must_exist=True)
    except ValueError as e:
        return f"[注入失败] {e}"
    # 现场跑解析注册表拿元素映射：确定性幂等（同原件同映射），不依赖任务侧
    # 解析是否落盘——独立格式附件可能没走过 parse_document（走缓存）
    idx = sorted({
        el for el, s, e in _source_element_lines(src_path)
        if isinstance(el, int) and (lo is None or (s <= hi and e >= lo))
    })
    if not idx:
        return "[注入失败] 行号区间未映射到任何 docx 元素（核对 outline.json 的行号区间）"
    src = Document(str(src_path))
    dst_doc = Document(str(dst))
    children = list(src.element.body.iterchildren())
    # 同区间重复注入拦截（2026-09-10 review，与素材侧同口径）：注入是 append
    # 语义，同区间重拷=格式件整段翻倍（写手遗忘已注入/工具超时重试/HITL 续跑
    # 重放同一调用都可能触发），且下游 validate_body 节间查重/合册对同节重复
    # 均无防线、可直达交付合册。概率防线：大幅改写后漏拦可接受
    incoming = _sig_shingles(
        "".join("".join(children[i].itertext()) for i in idx if i < len(children))
    )
    if len(incoming) >= 5:
        # 目标侧同口径 itertext（section_text_lines 的表格行/单元格有截断，
        # 重叠率被稀释漏拦——两侧同为元素全量文本，重复注入时 ≈100% 命中）
        cur = _sig_shingles("".join(dst_doc.element.body.itertext()))
        if len(incoming & cur) / len(incoming) >= 0.6:
            scope_hit = "整份文件" if lo is None else f"行号区间 {lo}-{hi}"
            return (
                f"[注入失败] 《{name}》（{scope_hit}）的内容已大量出现在 work/{rel}"
                "（已注入过）——注入是追加语义，重复拷贝会翻倍格式件；确需重拷请先重建"
                "节文件（docx_section_create 传 replace=true）"
            )
    sect = dst_doc.element.body.find(qn("w:sectPr"))
    n_para = n_tbl = n_img = 0
    copied: list = []
    for i in idx:
        if i >= len(children):
            continue
        el = children[i]
        if el.tag.split("}")[-1] not in ("p", "tbl"):
            continue
        new_el = deepcopy(el)
        _strip_inner_sectpr(new_el)
        n_img += _migrate_images(src, dst_doc, new_el)
        if sect is not None:
            sect.addprevious(new_el)
        else:
            dst_doc.element.body.append(new_el)
        copied.append(new_el)
        if el.tag.split("}")[-1] == "tbl":
            n_tbl += 1
        else:
            n_para += 1
    if n_para + n_tbl == 0:
        return "[注入失败] 区间内没有可拷贝的段落/表格元素"
    n_style = _merge_missing_styles(src, dst_doc, copied)
    n_num = _merge_missing_numbering(src, dst_doc, copied)
    dst_doc.save(dst)
    scope = "整份文件" if lo is None else f"行号区间 {lo}-{hi}"
    return (
        f"[已注入] 《{name}》（{scope}）→ work/{rel}：段落 {n_para} 个、"
        f"表格 {n_tbl} 张、图片 {n_img} 张（内容与格式逐字节取自招标原件）"
        + (f"，随迁样式定义 {n_style} 个、编号定义 {n_num} 组" if n_style or n_num else "")
        + "\n下一步：docx_section_read 拿段落序号与表格格坐标 → docx_section_revise 填空"
        "（表格空格子 fill、旧值 replace；招标方信息保留、我方信息按承诺清单填，未定值【待补：…】）"
        "→ validate_body 自查。"
    )


@tool
@_tool_guard("插图")
def docx_image_insert(dest: str, image: str, after: str = "", page: int = 1) -> str:
    """把一张图片插入正文节 docx（证书复印件/扫描件/系统截图——独立图片进正文的唯一
    通道，自写文字无法带图）。

    图片作为新段落落在指定位置：全宽适配（页宽减边距）、居中、带插入修订标记
    （Word 审阅可逐张接受/拒绝）。多张图=多次调用。
    Args:
        dest: 目标节文件（须已用 docx_section_create 创建）
        image: 图片路径（工作区相对，三类来源）：①知识库抽取图
               knowledge/parse/<文件stem>/images/img_001.png——search_company_assets
               命中行会给出路径，证书扫描 PDF 的抽取图每页一张、文件序号即页序；
               ②当前任务上传图 sources/<文件名>（可带任务前缀）；
               ③PDF 原件（knowledge/files/xxx.pdf 或 sources/xxx.pdf）——传页号
               现场渲染那一页为图，兜住抽取缺图的形态。支持 png/jpg/bmp/gif；
               webp 与 docx 原件不支持（换 PDF 或图片版）。
        after: 插在该段落号之后（P 序号以 docx_section_read 视图为准，可带 P 前缀）；
               留空=追加到节末尾
        page: image 指向 PDF 时的页号（1 起；图片文件忽略此参数）
    """
    task_id = _task_id()
    if not task_id:
        return "[插图失败] 当前会话未归属任务"
    try:
        dst, rel = _dest_path(task_id, dest, must_exist=True)
    except ValueError as e:
        return f"[插图失败] {e}"
    # 图源解析：sources/ 短前缀（含任务前缀形态）归一到当前任务 sources/，其余按
    # workspace 相对（knowledge/…）；resolve 后 containment——图源只认工作区内文件
    segs = [s for s in (image or "").strip().replace("\\", "/").split("/") if s]
    if segs and segs[0] == task_id:
        segs = segs[1:]
    if not segs:
        return "[插图失败] 未指定图片路径"
    if segs[0] == "sources":
        if len(segs) < 2:
            return "[插图失败] sources/ 后未指定文件名"
        base = sources_dir(task_id).resolve()
        src = (base / "/".join(segs[1:])).resolve()
        if base != src and base not in src.parents:
            return f"[插图失败] 路径越界：{image}"
    else:
        root = workspace_dir().resolve()
        src = (root / "/".join(segs)).resolve()
        if root != src and root not in src.parents:
            return (
                f"[插图失败] 路径越界或不在工作区内：{image}"
                "（图源=知识库抽取图 knowledge/parse/…/images/ 或任务 sources/ 下的文件）"
            )
    if not src.is_file():
        return f"[插图失败] 图片文件不存在：{image}（以检索命中行给出的路径或任务 sources/ 清单为准）"

    suffix = src.suffix.lower()
    if suffix == ".pdf":
        pd = pymupdf.open(str(src))
        try:
            n_pages = pd.page_count
        finally:
            pd.close()
        if not 1 <= int(page) <= n_pages:
            return f"[插图失败] 页号超范围：该 PDF 共 {n_pages} 页（page 须 1-{n_pages}）"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp_png = Path(tf.name)
        try:
            render_page_png(src, int(page), tmp_png)
            data = tmp_png.read_bytes()
        finally:
            tmp_png.unlink(missing_ok=True)
        src_label = f"{image} 第 {page} 页（按页渲染）"
    elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
        data = src.read_bytes()
        src_label = image
    else:
        return (
            f"[插图失败] 「{image}」不是可插入的图片或 PDF（{suffix or '无后缀'}）"
            "——webp 请换 png/jpg 上传；docx 原件不作图源，请传 PDF 或图片版"
        )

    doc = Document(str(dst))
    before = _flatten_rejected(doc)
    sec = doc.sections[-1] if doc.sections else None
    try:
        avail = sec.page_width - sec.left_margin - sec.right_margin if sec else None
    except TypeError:
        avail = None
    width = avail if isinstance(avail, int) and avail > 0 else Cm(15)
    # drawing XML 让 python-docx 生成（先临时挂在节末），修订标记再手包+搬位
    tmp_p = doc.add_paragraph()
    run = tmp_p.add_run()
    try:
        run.add_picture(BytesIO(data), width=width)
    except Exception as e:
        return f"[插图失败] 图片无法解析（{type(e).__name__}）——请确认文件是完好的 png/jpg 图片"
    date = _now_iso()
    rev_id = _next_rev_id(doc)
    ins_el = parse_xml(
        f'<w:ins {nsdecls("w")} w:id="{rev_id + 1}" w:author="{_AUTHOR}" w:date="{date}"/>'
    )
    r_el = run._r
    r_el.addprevious(ins_el)
    ins_el.append(r_el)
    p_el = tmp_p._p
    # 段落标记修订（拒绝修订=整段含图消失）+ 居中；图片段不挂 Tender Body（正文
    # 样式带首行缩进会把图推偏）；缺段落标记修订会让拒绝视角多出空行（自校验拦截）
    p_el.insert(0, parse_xml(
        f'<w:pPr {nsdecls("w")}>'
        f'<w:jc w:val="center"/>'
        f'<w:rPr><w:ins w:id="{rev_id}" w:author="{_AUTHOR}" w:date="{date}"/></w:rPr>'
        f'</w:pPr>'
    ))
    if (after or "").strip():
        try:
            idx = int((after or "").strip().lstrip("Pp"))
        except ValueError:
            return "[插图失败] after 须为段落号（如 5 或 P5，以 docx_section_read 视图为准）"
        paras = doc.paragraphs
        if not 1 <= idx <= len(paras):
            return f"[插图失败] 段落号超范围：after={idx}，本节视图共 {len(paras)} 段"
        paras[idx - 1]._p.addnext(p_el)
        where = f"P{idx} 之后"
    else:
        sect = doc.element.body.find(qn("w:sectPr"))
        if sect is not None:
            sect.addprevious(p_el)
        else:
            doc.element.body.append(p_el)
        where = "节末"
    if _flatten_rejected(doc) != before:
        return "[插图失败] 修订标记自校验未通过（未保存，文件未变）——请重试或换图源"
    doc.save(dst)
    return (
        f"[已插图] {src_label} → work/{rel}（{where}）：图片 1 张，全宽居中、带插入修订标记"
        "\n下一步：docx_section_read 确认位置（图片段显示〔图×1〕）；需要图注可在该段前后"
        "用 docx_section_revise 插文字段。"
    )


@tool
@_tool_guard("批注")
def docx_comment_add(path: str, text: str, after: str = "") -> str:
    """给正文节 docx 加一条 Word 批注——缺料/待澄清/待核验等待办的唯一落点。

    批注锚定在指定段落上：Word 审阅侧栏可见（作者 Swift Agent）、打印与 PDF
    导出默认不带；docx_section_read 视图该段行尾显示〔批注：…〕，validate_body
    清点待办批注，合册时批注原样迁移进整本。**正文里禁止写【待补】【待澄清】
    占位文字**（会进交付稿）——缺什么、要用户裁决什么、哪个数字待核验，都走本工具。
    Args:
        path: 目标节文件（相对任务 work/，须已用 docx_section_create 创建）
        text: 批注内容——写清缺什么/要澄清什么（如「项目经理 PMP 证书编号缺失，
              需向用户确认后回填」）
        after: 锚定段落号（P 序号以 docx_section_read 视图为准，可带 P 前缀）；
               留空=节末最后一段
    """
    task_id = _task_id()
    if not task_id:
        return "[批注失败] 当前会话未归属任务"
    if not (text or "").strip():
        return "[批注失败] 批注内容为空——写清缺什么/要澄清什么"
    try:
        dst, rel = _dest_path(task_id, path, must_exist=True)
    except ValueError as e:
        return f"[批注失败] {e}"
    doc = Document(str(dst))
    paras = doc.paragraphs
    if not paras:
        return "[批注失败] 本节没有段落可锚定"
    if (after or "").strip():
        try:
            idx = int((after or "").strip().lstrip("Pp"))
        except ValueError:
            return "[批注失败] after 须为段落号（如 5 或 P5，以 docx_section_read 视图为准）"
        if not 1 <= idx <= len(paras):
            return f"[批注失败] 段落号超范围：after={idx}，本节视图共 {len(paras)} 段"
        para, where = paras[idx - 1], f"P{idx}"
    else:
        para, where = paras[-1], f"P{len(paras)}"
    # 段落直接子 run 为空（全空段/内容全裹在修订标记里）时补一个零宽锚点 run——
    # 批注锚在段尾，不往修订子树里插标记元素
    runs = para.runs or [para.add_run("")]
    doc.add_comment(runs, text=text.strip(), author=_COMMENT_AUTHOR, initials="AI")
    doc.save(dst)
    total = len(_comment_texts(doc))
    snippet = text.strip()[:30] + ("…" if len(text.strip()) > 30 else "")
    return (
        f"[已加批注] work/{rel} {where}：「{snippet}」（本节待办批注共 {total} 条）"
        "\n待办批注收尾必须逐条向用户点名（validate_body 也会清点）；正文里不要写占位文字。"
    )


@tool
@_tool_guard("修订")
def docx_section_revise(path: str, edits: str) -> str:
    """对正文节 docx 做定向修订，全部落成 Word 原生修订标记（用户在 Word 中审阅接受/拒绝）。

    用途：素材底稿注入后的适配修订（换公司名/项目名/参数）、招标格式件填空
    （函件空栏/表格空格子）、局部新写、删除无关段。每处修订在 Word 修订视图可见
    （作者 Tender Agent）；程序落盘前自校验「拒绝全部修订后与修订前逐字一致」
    （覆盖正文段落与表格单元格），标记损坏即拒绝保存。
    Args:
        path: 目标节文件（相对任务 work/，如 body/技术部分/3.1 需求分析.docx）
        edits: JSON 数组，两类条目（不可混在同一条里）——正文段落
              {"para": 段落序号, "action": "replace|insert_after|delete",
               "find": 期望原文片段（replace 必填，防段落漂移的双重校验）,
               "text": 新文本, "style": 样式名（仅 insert_after 可选，如
               "Tender Cover"/"Tender Cover Sub"——封面等非正文段落挂指定
               版式；样式不存在回落正文样式并在返回中注记）}；表格单元格
               {"table": T序号, "row": 行, "col": 列,
               "action": "replace|fill", "find": 格内期望原文（replace 必填，须
               完整出现在同一格内段落）, "text": 新文本}——fill 仅限空格子
               （接受视角为空，填空动作）。replace 只替换首处命中；同段多条按
               接受视角顺序定位。多条段落编辑按序号从大到小应用（防位移），
               表格格编辑不改段落数、另批处理。表格插行/删行、嵌套表格不支持
               （在 Word 中改）。
    """
    task_id = _task_id()
    if not task_id:
        return "[修订失败] 当前会话未归属任务"
    try:
        dst, rel = _dest_path(task_id, path, must_exist=True)
    except ValueError as e:
        return f"[修订失败] {e}"
    try:
        items = json.loads(edits)
    except ValueError:
        return "[修订失败] edits 不是合法 JSON"
    if not isinstance(items, list) or not items:
        return "[修订失败] edits 须为非空 JSON 数组"
    errs: list[str] = []
    para_items: list[dict] = []
    cell_items: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            errs.append("每项须为对象")
            continue
        has_para = isinstance(it.get("para"), int) and not isinstance(it.get("para"), bool)
        has_cell = all(
            isinstance(it.get(k), int) and not isinstance(it.get(k), bool)
            for k in ("table", "row", "col")
        )
        if has_para and has_cell:
            errs.append("para 与 table/row/col 不可同时传")
            continue
        if has_para:
            act = it.get("action")
            if act not in ("replace", "insert_after", "delete"):
                errs.append(f"P{it.get('para')}：action 须为 replace|insert_after|delete")
            elif act == "replace" and (not it.get("find") or it.get("text") is None):
                errs.append(f"P{it.get('para')}：replace 需 find 与 text")
            elif act == "insert_after" and not it.get("text"):
                errs.append(f"P{it.get('para')}：insert_after 需 text")
            else:
                para_items.append(it)
        elif has_cell:
            act = it.get("action")
            where = f"T{it.get('table')}({it.get('row')},{it.get('col')})"
            if act not in ("replace", "fill"):
                errs.append(f"{where}：action 须为 replace|fill")
            elif act == "replace" and (not it.get("find") or it.get("text") is None):
                errs.append(f"{where}：replace 需 find 与 text")
            elif act == "fill" and not it.get("text"):
                errs.append(f"{where}：fill 需 text")
            else:
                cell_items.append(it)
        else:
            errs.append("每项须含整数 para（正文段落）或 table/row/col 三件套（表格单元格）")
    if errs:
        return "[修订失败] " + "；".join(errs)
    doc = Document(str(dst))
    paras = doc.paragraphs
    before = _flatten_rejected(doc)
    applied = 0
    body_style = _body_style(doc)
    body_style_id = body_style.element.get(qn("w:styleId")) if body_style else None
    # 段落从后往前：插入/删除改变段落数，先改大序号防位移；同段连续
    # insert_after 以「上次插入的新段」为锚保提交顺序（游标按段序号记）
    insert_anchors: dict[int, object] = {}
    style_notes: set[str] = set()  # 指定了但版式里不存在的样式名（回落正文样式）
    for it in sorted(para_items, key=lambda x: x["para"], reverse=True):
        i = it["para"]
        if i < 1 or i > len(paras):
            return f"[修订失败] 段落序号 {i} 超出范围（现共 {len(paras)} 段；序号以 docx_section_read 为准）"
        para = paras[i - 1]
        rev_id = _next_rev_id(doc)
        act = it["action"]
        try:
            if act == "replace":
                _tracked_replace(para, str(it["find"]), str(it["text"]), rev_id)
            elif act == "insert_after":
                anchor = insert_anchors.get(i, para._p)
                style_id = body_style_id
                style_name = it.get("style")
                if isinstance(style_name, str) and style_name.strip():
                    resolved = _style_id_by_name(doc, style_name.strip())
                    if resolved is None:
                        style_notes.add(style_name.strip())
                    else:
                        style_id = resolved
                insert_anchors[i] = _tracked_insert_after(
                    anchor, str(it["text"]), rev_id, style_id=style_id
                )
            else:
                _tracked_delete(para, rev_id)
        except ValueError as e:
            return f"[修订失败] P{i}：{e}"
        applied += 1
    # 表格单元格（格编辑不改段落数，与段落批寻址互不影响；嵌套表格内容不达——
    # find 定位不到会明确报错）
    for it in cell_items:
        t_no, r, c = it["table"], it["row"], it["col"]
        if t_no < 1 or t_no > len(doc.tables):
            return f"[修订失败] 表格序号 {t_no} 超出范围（现共 {len(doc.tables)} 张；序号以 docx_section_read 视图为准）"
        tbl = doc.tables[t_no - 1]
        if r < 1 or r > len(tbl.rows) or c < 1 or c > len(tbl.columns):
            return (
                f"[修订失败] T{t_no} 单元格坐标 ({r},{c}) 超出范围"
                f"（{len(tbl.rows)}行×{len(tbl.columns)}列；坐标以视图 R行C列 为准）"
            )
        cell_paras = tbl.cell(r - 1, c - 1).paragraphs
        rev_id = _next_rev_id(doc)
        if it["action"] == "fill":
            if any(_accepted_text(p._p).strip() for p in cell_paras):
                return (
                    f"[修订失败] T{t_no}({r},{c}) 非空格子不能用 fill——"
                    "read 视图取该格原文片段改用 replace"
                )
            _tracked_fill(cell_paras[0], str(it["text"]), rev_id)
        else:
            find = str(it["find"])
            target = next((p for p in cell_paras if find in _accepted_text(p._p)), None)
            if target is None:
                return (
                    f"[修订失败] T{t_no}({r},{c}) 格内未找到期望文本「{find[:60]}」"
                    "（find 须完整出现在同一格内段落）"
                )
            try:
                _tracked_replace(target, find, str(it["text"]), rev_id)
            except ValueError as e:
                return f"[修订失败] T{t_no}({r},{c})：{e}"
        applied += 1
    if _flatten_rejected(doc) != before:
        return "[修订失败] 修订标记一致性自校验未通过（未保存）——请重读视图核对序号与原文后重试"
    doc.save(dst)
    bits = (
        f"[已修订] work/{rel}：{applied} 处已落成 Word 修订标记（作者 {_AUTHOR}），"
        f"在 Word 中审阅可逐条接受/拒绝。修订后建议 check_name_residue 扫旧名残留。"
    )
    if style_notes:
        bits += f"（注：样式 {'、'.join(sorted(style_notes))} 不存在，该段已用正文样式）"
    return bits


# ---------- 整本合册与文本抽取 ----------

def _tree_nodes(nodes: list[dict], depth: int = 1):
    """目录树先序遍历产出 (深度, 标题, 是否容器, 交付形态)——合册的章序真值是树序，不是文件名序。"""
    for n in nodes:
        children = n.get("children") or []
        title = str(n.get("目录名称") or "").strip()
        mode = str(n.get("交付形态") or "").strip()
        if title:
            yield depth, title, bool(children), mode
        yield from _tree_nodes(children, depth + 1)


# ---------- 章节编号（合册按树序生成；格式取目录产物 numbering 字段） ----------

_CN_DIGITS = "零一二三四五六七八九"

# 目录节点名自带编号的前缀形态（合册会再加程序编号 → 双重编号；探测点名请用户
# 裁决，提示不是门禁）。数字形态限一两位+空格，避开「2026 年度」类年份误报。
_SELF_NUMBERED = re.compile(
    r"^(第([一二三四五六七八九十百]+|\d+)章|[一二三四五六七八九十]+、"
    r"|（[一二三四五六七八九十]+）|\d{1,2}(\.\d+)*[ 　])"
)


def _cn_num(n: int) -> str:
    """1–99 → 中文数字（十一、二十一…）；超范围回落阿拉伯数字（防御，章节数到不了）。"""
    if not 1 <= n <= 99:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    head = "十" if tens == 1 else _CN_DIGITS[tens] + "十"
    return head + (_CN_DIGITS[ones] if ones else "")


class _HeadingNumberer:
    """合册章节编号器：编号=树位置的纯函数（每册一个实例，各册从首章重起）。

    编号写进标题文本，不走 Word 样式绑定自动编号——素材拷入的标题段会被 Word
    一起计数打乱章序、docx-preview 对经典绑定写法不渲染、节文件单看永远「第一章」。
    chapter=第X章+1.1（一级全角空格接题名）、decimal=1+1.1、gov=一、（一）1.、
    none=不加；封面节点不调用 prefix（不占序）。
    """

    def __init__(self, scheme: str):
        self.scheme = scheme if scheme in ("chapter", "decimal", "gov", "none") else "chapter"
        self.counters = [0] * 10  # counters[depth]：各深度当前计数（下标 1 起）

    def prefix(self, depth: int) -> str:
        """发一个 depth 级标题的编号前缀（消费一个序号并重置更深计数）。"""
        if self.scheme == "none" or not 1 <= depth <= 9:
            return ""
        self.counters[depth] += 1
        for d in range(depth + 1, 10):
            self.counters[d] = 0
        if self.scheme == "gov":
            if depth == 1:
                return f"{_cn_num(self.counters[1])}、"
            if depth == 2:
                return f"（{_cn_num(self.counters[2])}）"
            return f"{self.counters[depth]}."
        if self.scheme == "chapter" and depth == 1:
            return f"第{_cn_num(self.counters[1])}章\u3000"
        return ".".join(str(self.counters[d]) for d in range(1, depth + 1)) + " "


def _is_title_para(p_el, title: str) -> bool:
    """节文件首段是否为其自带标题段（合册时跳过——标题由合册器按树深重发）。

    判据统一为「样式非空且接受视角文本=节标题」：只看 Heading1 会把注入素材
    自带的章标题段（Heading1、文本≠节标题）静默剥掉——素材内容丢失；宁可
    保守漏剥（首段与树标题写法有出入时合册重复发标题，可见可修）。
    """
    ppr = p_el.find(qn("w:pPr"))
    pstyle = ppr.find(qn("w:pStyle")) if ppr is not None else None
    style_val = (pstyle.get(qn("w:val")) or "") if pstyle is not None else ""
    return bool(style_val) and _accepted_text(p_el).strip() == title.strip()


def section_lines_labeled(doc: Document) -> list[tuple[str, str]]:
    """(定位标签, 文本) 序列：段落 P{i}、表格行 T{t}R{r}。

    行集与 section_text_lines 同源同序——标签供 validate_body 的占位/残留提示
    定位（与 docx_section_read 视图互查，表格行不再被标成越界的 P 号）。
    合并单元格的行文本含重复格文本（python-docx row.cells 口径），只影响
    可读性不影响校验。
    """
    out: list[tuple[str, str]] = []
    for i, p in enumerate(doc.paragraphs, 1):
        out.append((f"P{i}", _accepted_text(p._p)))
    for ti, t in enumerate(doc.tables, 1):
        for ri, row in enumerate(t.rows, 1):
            cells = ["".join(_accepted_text(p._p) for p in c.paragraphs) for c in row.cells]
            out.append((f"T{ti}R{ri}", " | ".join(cells)))
    return out


def section_text_lines(doc: Document) -> list[str]:
    """docx 正文文本行（**接受全部修订后的终稿视角**——评委最终看到的文本）。

    段落逐行 + 表格每行单元格拼接。行序与 docx_section_read 视图的 P 编号
    **严格一致**：段落标记被标删的段（整段删除修订）以空行占位——空行对
    占位清点/残留扫描/素材使用率/承诺比对全部无操作，而 P 段号不漂移（校验
    提示里的定位与视图可互查）。插入修订算在内（终稿存在）、删除修订的内容
    不算（终稿消失）。
    """
    return [text for _label, text in section_lines_labeled(doc)]


def section_comments_labeled(doc: Document) -> list[tuple[str, str]]:
    """(锚定段落 P 标签, 批注文本)——待办批注的定位清点（validate_body 消费）。

    只扫正文级段落（commentRangeStart 是段落直接子元素）；锚在表格格内或跨段的
    批注落在「?」兜底行——宁可位置不明也不漏清点。
    """
    texts = _comment_texts(doc)
    if not texts:
        return []
    out: list[tuple[str, str]] = []
    anchored: set[int] = set()
    for i, para in enumerate(doc.paragraphs, 1):
        for m in para._p.findall(qn("w:commentRangeStart")):
            raw = m.get(qn("w:id")) or ""
            if not raw.isdigit():
                continue
            cid = int(raw)
            anchored.add(cid)
            t = texts.get(cid)
            if t:
                out.append((f"P{i}", t))
    out.extend(("?", t) for cid, t in texts.items() if cid not in anchored)
    return out


def head_text(path: str | Path, max_chars: int = 200) -> str:
    """docx 开头文本（接受修订视角）：前几段/表格行非空文本拼到 max_chars 截断。

    派发拼装的兄弟节摘要用（dispatch_enrich）——给并发写手看兄弟节开头、
    防跨节重复表达。文件损坏由调用方决定跳过（本函数不吞异常）。
    """
    doc = Document(str(path))
    parts: list[str] = []
    used = 0
    for text in section_text_lines(doc):
        t = text.strip()
        if not t:
            continue
        parts.append(t)
        used += len(t)
        if used >= max_chars:
            break
    return "".join(parts)[:max_chars]


@tool
@_tool_guard("合册")
def docx_assemble_volume() -> str:
    """按投标目录树序把正文节 docx 合册成整本文件（每册一个，tender-body 收尾必调）。

    用途：全部节完成后调用，产出 work/body/整本-<册名>.docx。容器章由本工具发
    标题（层级随树深，Word 可自动生成目录）、叶子节内容元素级拷入（图片/表格/
    修订标记原样保留——在整本里继续用 Word 审阅逐条接受/拒绝）、一级章前分页、
    页脚页码；模板填充类叶子（目录标非正文）**产出节文件即按树序并入**（拷原件
    填空的格式件本就是标书组成部分）、未产出的按附件对待不占整本位（返回行点名）。
    章节编号按树序自动生成（第一章/1.1；格式取目录产物的 numbering 字段，缺省
    第X章+1.1；封面不占序，目录产物里可改为 1+1.1/一、（一）/不编号）。
    树首节点为「封面」时（tender-outline 的结构约定）整本首页即封面页：跳过册名
    大标题与封面节点自身标题、开「首页不同」（封面页不带页眉页脚，页码从封面
    后一页起显示）。缺失的正文节文件逐个点名，不中断其余节。**整本是派生产物**：改内容
    回节文件层改（或让模型改）再重新调用本工具覆盖合册，直接手改整本会被下次
    合册覆盖。
    """
    task_id = _task_id()
    if not task_id:
        return "[合册失败] 当前会话未归属任务"
    _, content, _ = body_contract.load_directory(task_id)
    if content is None:
        return "[合册失败] 无投标目录产物（或内容不可读）——合册按目录树排序，请先 tender-outline 生成目录"
    docs = [d for d in content.get("response_documents") or [] if d.get("directory")]
    if not docs:
        return "[合册失败] 目录产物没有响应文件树"
    multi = body_contract.multi_volume(content)
    numberer_scheme = str(content.get("numbering") or "").strip() or "chapter"
    wroot = work_dir(task_id).resolve()
    consumed: set[str] = set()
    reports: list[str] = []
    for doc in docs:
        vol = str(doc.get("name") or "").strip() or "主册"
        vol_dir = body_contract.sanitize_name(vol) if multi else ""
        nodes = list(_tree_nodes(doc.get("directory") or []))
        numberer = _HeadingNumberer(numberer_scheme)  # 各册从首章重起
        self_numbered: list[str] = []  # 节点名自带编号（合册再编号会双重，探测点名）
        # 封面=树首一级叶子且清洗后标题为「封面」（tender-outline 的结构约定）：
        # 整本首页即封面页——跳过册名大标题（封面自带册名）与节点自身标题，
        # 开「首页不同」让封面页不带页眉页脚；无封面时行为与旧版逐字节一致。
        has_cover = (
            bool(nodes)
            and nodes[0][0] == 1
            and not nodes[0][2]
            and body_contract.sanitize_name(nodes[0][1]) == _COVER_NODE_NAME
        )
        out = _new_document()  # 模板自带 A4 版面/页边距/页脚页码，无需再手拼
        if has_cover:
            out.sections[0].different_first_page_header_footer = True
        else:
            out.add_heading(vol, 0)
        merged = n_img = n_comment = 0
        missing: list[str] = []
        unfilled: list[str] = []  # 模板填充类叶子未产出节文件（按附件对待）
        placeholders: list[str] = []  # 内联占位兜底扫描命中（正规落点=批注，此为防线）
        seen_chapter = False
        for idx, (depth, title, is_container, mode) in enumerate(nodes):
            if _SELF_NUMBERED.match(title):
                self_numbered.append(title)
            stem = body_contract.sanitize_name(title)
            rel_src = f"body/{vol_dir}/{stem}.docx" if vol_dir else f"body/{stem}.docx"
            if not is_container and mode in body_contract.NON_PROSE_DELIVERY:
                if not (wroot / rel_src).is_file():
                    unfilled.append(title)
                    continue  # 模板填充未产出：按附件对待（打印装订时物理附上），不占整本位
                # 已产出（拷原件+填空）：按树序并入整本，与正文叶子同路
            if has_cover and idx == 0:
                # 封面节点不发「封面」标题行（节文件内容即整页），但占一级位：
                # seen_chapter 置位让第一章拿到分页、封面独占首页；编号不占序
                seen_chapter = True
            else:
                # 标题带编号发（对账剥节文件标题仍用裸 title，见 _is_title_para 调用处）
                h = out.add_heading(numberer.prefix(depth) + title, min(depth, 9))
                if depth == 1:
                    if seen_chapter:
                        h.paragraph_format.page_break_before = True
                    seen_chapter = True
            if is_container:
                continue
            src_path = wroot / rel_src
            if not src_path.is_file():
                missing.append(title)
                continue
            consumed.add(rel_src)
            src = Document(str(src_path))
            # 内联占位兜底：接受视角逐行扫（整段删除修订不误报）——正规待办落点是
            # docx_comment_add 批注，正文占位文字会进交付稿，点名逼改
            for label, text in section_lines_labeled(src):
                for mark in body_contract.PLACEHOLDER_MARKS:
                    if mark in text:
                        i = text.find(mark)
                        placeholders.append(f"{title}({label})：{text[i : i + 24].strip()}")
                        break
            children = [
                c for c in src.element.body.iterchildren()
                if c.tag.split("}")[-1] in ("p", "tbl")
            ]
            if children and children[0].tag.split("}")[-1] == "p" and _is_title_para(children[0], title):
                children = children[1:]
            copied: list = []
            for el in children:
                new_el = deepcopy(el)
                _strip_inner_sectpr(new_el)
                n_img += _migrate_images(src, out, new_el)
                copied.append(new_el)
                sect = out.element.body.find(qn("w:sectPr"))
                if sect is not None:
                    sect.addprevious(new_el)
                else:
                    out.element.body.append(new_el)
            _merge_missing_styles(src, out, copied)
            _merge_missing_numbering(src, out, copied)
            n_comment += _merge_missing_comments(src, out, copied)
            merged += 1
        if merged == 0:
            detail = f"（缺失：{'、'.join(missing)}）" if missing else "（目录树无叶子节点）"
            reports.append(f"{vol}：无已写节文件{detail}，未产出整本")
            continue
        try:
            dst, rel = _dest_path(task_id, f"body/整本-{body_contract.sanitize_name(vol)}.docx", must_exist=False)
        except ValueError as e:
            return f"[合册失败] {e}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        out.save(tmp)
        tmp.replace(dst)  # 原子替换：整本是派生产物，重跑直接覆盖（恢复语义在节文件层）
        bits = f"{vol}：合并 {merged} 节 → work/{rel}"
        if n_img:
            bits += f"（含图片 {n_img} 张）"
        if n_comment:
            bits += f"（含批注 {n_comment} 条待处理）"
        if missing:
            bits += f"；缺失 {len(missing)} 节未并入：{'、'.join(missing)}"
        reports.append(bits)
        if placeholders:
            shown = "；".join(placeholders[:8]) + ("…" if len(placeholders) > 8 else "")
            reports.append(
                f"⚠️ {vol}：正文含 {len(placeholders)} 处内联占位【待补/待澄清】"
                "（占位文字会进交付稿——删除该文字，改用 docx_comment_add 加批注记待办）："
                + shown
            )
        if unfilled:
            reports.append(
                f"{vol}：模板填充类未产出 {len(unfilled)} 节（按附件对待，不占整本位）："
                + "、".join(unfilled)
            )
        if self_numbered:
            shown = "、".join(self_numbered[:6]) + ("…" if len(self_numbered) > 6 else "")
            reports.append(
                f"⚠️ {vol}：{len(self_numbered)} 个目录节点名自带编号（{shown}）——"
                "合册已再按树序自动编号，会出现「第一章 一、xxx」式双重编号；"
                "请在目录产物中把节点名改为不带编号的纯标题后重新合册"
            )
    orphans: list[str] = []
    body_root = wroot / "body"
    if body_root.is_dir():
        for p in sorted(body_root.rglob("*.docx")):
            rel_path = p.relative_to(wroot).as_posix()
            if not p.name.startswith("整本-") and rel_path not in consumed:
                orphans.append(rel_path)
    lines = ["[已合册]", *reports]
    if orphans:
        shown = "、".join(orphans[:8]) + ("…" if len(orphans) > 8 else "")
        lines.append(f"⚠️ {len(orphans)} 个节文件未并入（目录无对应节点，先看 check_pipeline_state 的 [body] 段对账）：{shown}")
    lines.append("整本是派生产物：改内容请回节文件层改，再重新调用本工具覆盖合册。")
    return "\n".join(lines)
