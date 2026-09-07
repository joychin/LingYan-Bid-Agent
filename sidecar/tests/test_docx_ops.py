"""docx 正文工具族：建节/读视图/素材元素注入/带修订标记的定向修订。

覆盖链路：素材 docx 上传解析（产 element_map）→ 勾选建块 → 节文件创建 →
元素注入（表格合并单元格/图片关系保真）→ 修订标记（跨 run 替换/插入/删除，
拒绝全部修订=原文的自校验）→ 错误路径（非 docx 素材/路径越界/find 不命中/
既有修订标记段落）。
"""

import json
import struct
import zlib
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from app import runctx
from app.knowledge import materials_lib as mlib
from app.tools.docx_ops import (
    docx_assemble_volume,
    docx_material_inject,
    docx_section_create,
    docx_section_read,
    docx_section_revise,
    docx_source_inject,
)
from tests.util import init_env

COMPANY = "北京华信科技有限公司"


def _tiny_png(path: Path) -> None:
    """1×1 红点 PNG（图片关系迁移的最小载体）。"""

    def chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")
    )


def _make_material_docx(path: Path, png: Path) -> None:
    """素材原件：标题 + 跨 run 公司名段 + 合并单元格表格 + 图片段。"""
    doc = Document()
    doc.add_heading("运维服务方案", 1)
    p = doc.add_paragraph()
    p.add_run("本项目由")
    p.add_run("北京华信")
    p.add_run("科技有限公司承建，服务期三年。")
    t = doc.add_table(rows=3, cols=3)
    t.style = "Table Grid"
    t.rows[0].cells[0].text = "人员角色"
    t.cell(0, 1).merge(t.cell(0, 2)).text = "配置要求"
    t.cell(1, 0).merge(t.cell(2, 0)).text = "项目经理"
    t.cell(1, 1).text = "1 人"
    t.cell(1, 2).text = "PMP"
    t.cell(2, 1).text = "工程师"
    t.cell(2, 2).text = "5 人"
    doc.add_picture(str(png), width=914400 // 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def _make_tender_docx(path: Path) -> None:
    """招标原件：两章结构 + 投标函空栏段 + 含空格子的报价表（格式件拷贝/填空载体）。"""
    doc = Document()
    doc.add_heading("第一章 招标公告", 1)
    doc.add_paragraph("本项目公开招标，欢迎合格的投标人参加投标。")
    doc.add_heading("第四章 投标文件格式", 1)
    doc.add_heading("投标函", 2)
    doc.add_paragraph("致：______（招标人名称）")
    t = doc.add_table(rows=2, cols=3)
    t.style = "Table Grid"
    t.rows[0].cells[0].text = "项目名称"
    t.rows[0].cells[1].text = ""
    t.rows[0].cells[2].text = "报价（元）"
    t.rows[1].cells[0].text = ""
    t.rows[1].cells[1].text = "报价大写"
    t.rows[1].cells[2].text = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def _tender_source(env) -> Path:
    """把招标原件放进任务 sources/，返回绝对路径。"""
    from app.artifact_store import sources_dir

    p = sources_dir(env["task"]["id"]) / "招标文件.docx"
    _make_tender_docx(p)
    return p


@pytest.fixture
def env(tmp_path, monkeypatch):
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    mlib.ensure_dirs()
    png = tmp_path / "dot.png"
    _tiny_png(png)
    src = mlib.mt_files_dir() / "历史运维方案.docx"
    _make_material_docx(src, png)
    from app import db

    f = db.mt_insert_file("历史运维方案.docx", "hash_docx_1")
    mlib.run_parse(f["id"])
    block = mlib.create_block(
        f["id"], "运维整章", "历史项目运维章节",
        ranges=[[1, 10 ** 6]],  # 全文（_squash_ranges 会夹紧到实际行数）
    )
    yield {"task": task, "conv": conv, "file": f, "block": block, "png": png}
    runctx.clear_run()


def _make_section(name: str = "技术部分/3.1 运维方案.docx") -> str:
    rel = name if name.startswith("body/") else f"body/{name}"
    r = docx_section_create.invoke({"path": rel, "title": "3.1 运维方案"})
    assert r.startswith("[已创建]"), r
    return rel


# ---------- 建节与读视图 ----------

def test_create_and_read(env):
    from app.artifact_store import work_dir

    r = docx_section_create.invoke({"path": "body/技术部分/3.1 需求分析", "title": "3.1 需求分析", "paragraphs": "第一段。\n第二段。"})
    assert r.startswith("[已创建]") and "正文 2 段" in r
    # 路径自动补 .docx
    assert (work_dir(env["task"]["id"]) / "body" / "技术部分" / "3.1 需求分析.docx").is_file()
    view = docx_section_read.invoke({"path": "body/技术部分/3.1 需求分析.docx"})
    assert "[P1]（Heading 1）3.1 需求分析" in view
    assert "[P2]（Normal）第一段。" in view
    assert "共 3 个段落" in view


def test_create_refuses_overwrite(env):
    _make_section()
    r = docx_section_create.invoke({"path": "body/技术部分/3.1 运维方案.docx", "title": "x"})
    assert r.startswith("[创建失败]") and "已存在" in r


def test_path_containment(env):
    assert "只允许落在任务 work/body/" in docx_section_create.invoke({"path": "out/x.docx", "title": "x"})
    assert "路径越界" in docx_section_create.invoke({"path": "body/../../x.docx", "title": "x"})
    assert "只允许落在任务 work/body/" in docx_section_read.invoke({"path": "drafts/x.docx"})


def test_read_missing(env):
    assert "文件不存在" in docx_section_read.invoke({"path": "body/不存在.docx"})


# ---------- 素材注入 ----------

def test_material_inject_full_chain(env):
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section})
    assert r.startswith("[已注入]"), r
    assert "表格 1 张" in r and "图片 1 张" in r
    from app.artifact_store import work_dir

    dst = work_dir(env["task"]["id"]) / section
    chk = Document(str(dst))
    texts = "\n".join(p.text for p in chk.paragraphs)
    assert "运维服务方案" in texts and COMPANY in texts
    assert len(chk.tables) == 1
    xml = chk.tables[0]._tbl.xml
    assert "vMerge" in xml and "gridSpan" in xml  # 合并单元格随元素拷贝保留
    for blip in chk.element.body.findall(".//" + qn("a:blip")):
        rid = blip.get(qn("r:embed"))
        assert rid in chk.part.related_parts  # 图片关系完好


def test_material_inject_rebuilds_element_map(env):
    """旧解析产物无 element_map：注入自动幂等重跑补产。"""
    mlib.mt_parse_dir("历史运维方案.docx").joinpath("element_map.json").unlink()
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section})
    assert r.startswith("[已注入]"), r
    assert mlib.read_element_map("历史运维方案.docx")


def test_material_inject_requires_docx_source(env, tmp_path):
    """pdf/txt 等原件无可注入元素：明确拒绝并指路文本方式。"""
    from app import db

    txt = mlib.mt_files_dir() / "服务清单.txt"
    txt.write_text("# 服务清单\n\n提供驻场运维服务。\n", encoding="utf-8")
    f = db.mt_insert_file("服务清单.txt", "hash_txt_1")
    mlib.run_parse(f["id"])
    block = mlib.create_block(f["id"], "服务清单", "", ranges=[[1, 100]])
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": block["id"], "dest": section})
    assert r.startswith("[注入失败]") and "不是 docx" in r


def test_material_inject_missing_block(env):
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": "blk_000000000000", "dest": section})
    assert r.startswith("[注入失败]") and "不存在" in r


# ---------- 招标原件拷贝（docx_source_inject） ----------


def test_source_inject_whole_file(env):
    _tender_source(env)
    section = _make_section()
    r = docx_source_inject.invoke({"source": "招标文件.docx", "dest": section})
    assert r.startswith("[已注入]") and "整份文件" in r, r
    assert "表格 1 张" in r
    chk = Document(str(_abs(env, section)))
    texts = "\n".join(p.text for p in chk.paragraphs)
    assert "第一章 招标公告" in texts and "致：______（招标人名称）" in texts
    assert len(chk.tables) == 1 and chk.tables[0].cell(0, 0).text == "项目名称"


def test_source_inject_line_range(env):
    """行号区间拷（L 前缀容忍）：只带第四章格式章，不带第一章公告。"""
    from app.parse import convert as parse_convert

    src = _tender_source(env)
    md_lines = parse_convert(src).md.splitlines()
    start = next(i for i, ln in enumerate(md_lines, 1) if ln.startswith("# 第四章"))
    section = _make_section()
    r = docx_source_inject.invoke(
        {"source": "招标文件.docx", "dest": section, "lines": f"L{start}-{len(md_lines)}"}
    )
    assert r.startswith("[已注入]") and f"行号区间 {start}-{len(md_lines)}" in r, r
    chk = Document(str(_abs(env, section)))
    texts = "\n".join(p.text for p in chk.paragraphs)
    assert "第四章 投标文件格式" in texts and "投标函" in texts
    assert "招标公告" not in texts and "欢迎合格的投标人" not in texts
    assert len(chk.tables) == 1  # 报价表随格式章带入


def test_source_inject_rejects(env):
    from app.artifact_store import sources_dir

    sroot = sources_dir(env["task"]["id"])
    sroot.mkdir(parents=True, exist_ok=True)
    (sroot / "格式附件.txt").write_text("投标函格式", encoding="utf-8")
    section = _make_section()
    r = docx_source_inject.invoke({"source": "格式附件.txt", "dest": section})
    assert r.startswith("[注入失败]") and "不是 docx" in r
    assert "没有文件" in docx_source_inject.invoke({"source": "不存在的附件.docx", "dest": section})
    _tender_source(env)
    assert "起-止" in docx_source_inject.invoke(
        {"source": "招标文件.docx", "dest": section, "lines": "全部"}
    )
    assert "文件不存在" in docx_source_inject.invoke(
        {"source": "招标文件.docx", "dest": "body/未建节.docx"}
    )


# ---------- 修订标记 ----------

def _injected_section(env) -> tuple[str, Document]:
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section})
    assert r.startswith("[已注入]"), r
    return section, Document(str(_abs(env, section)))


def _abs(env, rel: str) -> Path:
    from app.artifact_store import work_dir

    return work_dir(env["task"]["id"]) / rel


def test_revise_replace_across_runs(env):
    """公司名拆在多个 run：替换落成 w:del/w:ins，拒绝修订=原文。"""
    section, _ = _injected_section(env)
    view = docx_section_read.invoke({"path": section})
    para_no = next(
        int(ln.split("]")[0][2:]) for ln in view.splitlines() if COMPANY in ln
    )
    edits = [
        {"para": para_no, "action": "replace", "find": COMPANY, "text": "上海中信科技有限公司"},
        # 同段第二处：穿过本轮已落的修订标记定位（换公司名 + 换工期是常态场景）
        {"para": para_no, "action": "replace", "find": "服务期三年", "text": "服务期两年"},
    ]
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps(edits)})
    assert r.startswith("[已修订]") and "2 处" in r, r

    chk = Document(str(_abs(env, section)))
    para = chk.paragraphs[para_no - 1]
    del_text = "".join(
        t.text or "" for t in para._p.iter(qn("w:delText"))
    )
    assert COMPANY in del_text and "服务期三年" in del_text
    ins_text = "".join(
        t.text or "" for e in para._p.iter(qn("w:ins")) for t in e.iter(qn("w:t"))
    )
    assert "上海中信科技有限公司" in ins_text and "服务期两年" in ins_text
    # 段内其余文字未被标记动过（接受视角：前缀+两处新值+后缀齐整）
    from app.tools.docx_ops import _accepted_text

    assert _accepted_text(para._p) == (
        "本项目由上海中信科技有限公司承建，服务期两年。"
    )


def test_revise_insert_and_delete(env):
    section, _ = _injected_section(env)
    n_before = len(Document(str(_abs(env, section))).paragraphs)
    view = docx_section_read.invoke({"path": section})
    head_no = next(int(ln.split("]")[0][2:]) for ln in view.splitlines() if "运维服务方案" in ln)
    tail_no = next(int(ln.split("]")[0][2:]) for ln in view.splitlines() if "服务期三年" in ln)
    edits = [
        {"para": tail_no, "action": "insert_after", "text": "本章按本次招标文件要求编制。"},
        {"para": head_no, "action": "delete"},
    ]
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps(edits)})
    assert r.startswith("[已修订]") and "2 处" in r, r

    chk = Document(str(_abs(env, section)))
    assert len(chk.paragraphs) == n_before + 1  # 删的是标记、插的是真段落
    # 插入段：段落标记与内容均为 ins（拒绝修订=整段消失）
    ins_para = chk.paragraphs[tail_no]  # 插在 tail_no 段后
    ppr = ins_para._p.find(qn("w:pPr"))
    assert ppr is not None and ppr.find(qn("w:rPr")).find(qn("w:ins")) is not None
    # 视图按「接受修订后」文本展示——新段内容对模型可见（python-docx .text 不含 ins）
    view = docx_section_read.invoke({"path": section})
    assert "本章按本次招标文件要求编制" in view
    assert "〔删除修订" in view  # 被删段在视图中明确标出
    # 删除段：run 文本全部转 delText
    gone = chk.paragraphs[head_no - 1]
    assert not gone.text or all(
        t.tag == qn("w:delText") for t in gone._p.iter() if t.tag in (qn("w:t"), qn("w:delText"))
    )


def test_revise_find_mismatch_keeps_file(env):
    section, _ = _injected_section(env)
    before = _abs(env, section).read_bytes()
    edits = [{"para": 2, "action": "replace", "find": "根本不存在的文本", "text": "x"}]
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps(edits)})
    assert r.startswith("[修订失败]") and "未找到期望文本" in r
    assert _abs(env, section).read_bytes() == before  # 失败不落盘


def test_revise_bad_payload(env):
    section = _make_section()
    assert "不是合法 JSON" in docx_section_revise.invoke({"path": section, "edits": "{oops"})
    assert "非空 JSON 数组" in docx_section_revise.invoke({"path": section, "edits": "[]"})
    assert "replace 需 find 与 text" in docx_section_revise.invoke(
        {"path": section, "edits": json.dumps([{"para": 1, "action": "replace", "text": "x"}])}
    )
    assert "超出范围" in docx_section_revise.invoke(
        {"path": section, "edits": json.dumps([{"para": 99, "action": "delete"}])}
    )
    assert "不可同时传" in docx_section_revise.invoke(
        {"path": section, "edits": json.dumps([
            {"para": 1, "table": 1, "row": 1, "col": 1, "action": "fill", "text": "x"},
        ])}
    )
    assert "三件套" in docx_section_revise.invoke(
        {"path": section, "edits": json.dumps([{"action": "fill", "text": "x"}])}
    )


# ---------- 表格单元格修订 ----------


def _format_section(env) -> str:
    """拷好招标格式件的节（格式件填空的测试载体）。"""
    _tender_source(env)
    section = _make_section()
    assert docx_source_inject.invoke(
        {"source": "招标文件.docx", "dest": section}
    ).startswith("[已注入]")
    return section


def test_view_table_cell_coordinates(env):
    """表格视图逐行展开格坐标：空格显式（空）、合并格标注。"""
    section = _format_section(env)
    view = docx_section_read.invoke({"path": section})
    assert "[T1] 表格 2行×3列" in view
    assert "[T1] R1：C1=项目名称 C2=（空） C3=报价（元）" in view
    assert "[T1] R2：C1=（空） C2=报价大写 C3=（空）" in view


def test_view_merge_annotations(env):
    """合并格视图标注：横向合并标「同左」、纵向合并标「同上」。"""
    section, _ = _injected_section(env)
    view = docx_section_read.invoke({"path": section})
    assert "[T1] R1：C1=人员角色 C2=配置要求 C3=（同左合并格）" in view
    assert "[T1] R2：C1=项目经理" in view
    assert "[T1] R3：C1=（同上合并格）" in view


def test_revise_cell_fill_and_replace(env):
    """格式件填空：空格 fill、旧值 replace，段落与格混在同一次提交互不影响。"""
    from app.tools.docx_ops import _accepted_text

    section = _format_section(env)
    edits = [
        {"table": 1, "row": 1, "col": 2, "action": "fill", "text": "智慧园区运维项目"},
        {"table": 1, "row": 2, "col": 3, "action": "fill", "text": "【待补：报价】"},
        {"table": 1, "row": 2, "col": 2, "action": "replace", "find": "报价大写", "text": "报价大写金额"},
        {"para": 2, "action": "insert_after", "text": "函件正文补充行。"},
    ]
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps(edits)})
    assert r.startswith("[已修订]") and "4 处" in r, r

    chk = Document(str(_abs(env, section)))
    c12 = chk.tables[0].cell(0, 1)
    assert _accepted_text(c12.paragraphs[0]._p) == "智慧园区运维项目"
    ins_text = "".join(
        t.text or "" for e in c12._tc.iter(qn("w:ins")) for t in e.iter(qn("w:t"))
    )
    assert "智慧园区运维项目" in ins_text  # fill 落成插入修订（Word 审阅可见）
    c22 = chk.tables[0].cell(1, 1)
    assert _accepted_text(c22.paragraphs[0]._p) == "报价大写金额"
    view = docx_section_read.invoke({"path": section})  # 视图（接受视角）可见填入值
    assert "C2=智慧园区运维项目" in view
    from app.tools.docx_ops import section_text_lines

    assert any("智慧园区运维项目" in ln for ln in section_text_lines(chk))


def test_revise_merged_cell_via_continuation_coordinate(env):
    """合并格的续坐标（R3C1）与原点坐标指向同一格：任一坐标都能改到内容。"""
    from app.tools.docx_ops import _accepted_text

    section, _ = _injected_section(env)
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"table": 1, "row": 3, "col": 1, "action": "replace", "find": "项目经理", "text": "项目总监"},
    ])})
    assert r.startswith("[已修订]"), r
    chk = Document(str(_abs(env, section)))
    assert _accepted_text(chk.tables[0].cell(1, 0).paragraphs[0]._p) == "项目总监"


def test_revise_cell_fill_nonempty_rejected(env):
    section = _format_section(env)
    before = _abs(env, section).read_bytes()
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"table": 1, "row": 1, "col": 1, "action": "fill", "text": "x"},
    ])})
    assert r.startswith("[修订失败]") and "非空格子" in r
    assert _abs(env, section).read_bytes() == before  # 失败不落盘


def test_revise_cell_out_of_range_and_find_miss(env):
    section = _format_section(env)
    assert "超出范围" in docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"table": 1, "row": 9, "col": 1, "action": "fill", "text": "x"},
    ])})
    assert "未找到期望文本" in docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"table": 1, "row": 1, "col": 1, "action": "replace", "find": "根本不存在", "text": "x"},
    ])})


def test_flatten_rejected_covers_table_cells(env):
    """自校验视角覆盖格内段落——表格修订写坏（拒绝视角文本变化）可被拦截。"""
    from app.tools.docx_ops import _flatten_rejected

    section = _format_section(env)
    flattened = _flatten_rejected(Document(str(_abs(env, section))))
    assert "项目名称" in flattened and "报价大写" in flattened


# ---------- replace 重写与恢复点 ----------


def test_create_replace_rotates_restore_points(env):
    section = _make_section()
    r = docx_section_create.invoke(
        {"path": section, "title": "3.1 运维方案", "paragraphs": "初稿", "replace": True}
    )
    assert r.startswith("[已重建]"), r
    d = _abs(env, section).with_name(_abs(env, section).name + ".restorepoints")
    assert len([p for p in d.iterdir() if p.suffix == ".bak"]) == 1
    # 连续重建 → 恢复点只留 3 个（栈深与工作台编辑/产物一致）
    for i in range(4):
        docx_section_create.invoke(
            {"path": section, "title": "x", "paragraphs": f"v{i}", "replace": True}
        )
    assert len([p for p in d.iterdir() if p.suffix == ".bak"]) == 3


# ---------- 样式与编号定义迁移 ----------


def test_material_inject_migrates_style_and_numbering(env):
    """注入元素引用自定义样式（basedOn 链）与多级编号：定义随迁，Word 打开不丢观感。"""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    src = mlib.mt_files_dir() / "编号样式素材.docx"
    doc = Document()
    doc.styles.element.append(parse_xml(
        f'<w:style {nsdecls("w")} w:type="paragraph" w:styleId="BideCustom">'
        f'<w:name w:val="BideCustom"/><w:basedOn w:val="BideCustomBase"/></w:style>'
    ))
    doc.styles.element.append(parse_xml(
        f'<w:style {nsdecls("w")} w:type="paragraph" w:styleId="BideCustomBase">'
        f'<w:name w:val="BideCustomBase"/></w:style>'
    ))
    np = doc.part.numbering_part.element
    np.append(parse_xml(
        f'<w:abstractNum {nsdecls("w")} w:abstractNumId="77">'
        f'<w:multiLevelType w:val="hybridMultilevel"/>'
        f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
        f'<w:lvlText w:val="%1"/></w:lvl></w:abstractNum>'
    ))
    np.append(parse_xml(f'<w:num {nsdecls("w")} w:numId="77"><w:abstractNumId w:val="77"/></w:num>'))
    p = doc.add_paragraph("自定义样式编号段落")
    p.style = doc.styles["BideCustom"]
    p._p.get_or_add_pPr().append(parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="77"/></w:numPr>'
    ))
    doc.save(src)

    from app import db

    f = db.mt_insert_file("编号样式素材.docx", "hash_style_1")
    mlib.run_parse(f["id"])
    block = mlib.create_block(f["id"], "自定义样式章", "", ranges=[[1, 1000]])
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": block["id"], "dest": section})
    assert r.startswith("[已注入]") and "随迁样式定义" in r, r

    chk = Document(str(_abs(env, section)))
    ids = {s.get(qn("w:styleId")) for s in chk.styles.element.findall(qn("w:style"))}
    assert {"BideCustom", "BideCustomBase"} <= ids  # basedOn 链递归补齐
    nums = {n.get(qn("w:numId")) for n in chk.part.numbering_part.element.findall(qn("w:num"))}
    assert "77" in nums  # numId 连其 abstractNum 一并补拷


# ---------- 整本合册 ----------

_KEY = "tender.directory/tender-response-docs@1"

_DIR_SINGLE = {
    "response_documents": [
        {
            "name": "技术部分",
            "scope": "",
            "directory": [
                {"目录名称": "第三章 技术方案", "level": 1, "children": [
                    {"目录名称": "3.1 项目理解与需求分析", "level": 2, "children": [],
                     "交付形态": "正文编写", "来源位置": ["REQ-01"]},
                    {"目录名称": "3.2 总体设计方案", "level": 2, "children": [],
                     "交付形态": "混合", "来源位置": ["SCORE-02"]},
                ]},
                {"目录名称": "附件：资质证书复印件", "level": 1, "children": [],
                 "交付形态": "模板或附件填充", "来源位置": ["MAND-02"]},
            ],
        }
    ]
}


def _seed_dir_artifact(env, content):
    from app import publish

    publish.publish_artifact(
        _KEY, content, task_id=env["task"]["id"], conversation_id=env["conv"]["id"]
    )


def test_assemble_tree_order_headings_and_missing(env):
    """树序合册：容器标题层级随树深、节文件自带标题跳过、缺失节点名、
    模板填充叶子未产出按附件对待（点名不占位）；重跑覆盖且整本不算孤儿。"""
    _seed_dir_artifact(env, _DIR_SINGLE)
    docx_section_create.invoke(
        {"path": "body/3.1 项目理解与需求分析", "title": "3.1 项目理解与需求分析",
         "paragraphs": "3.1 正文第一段。"}
    )
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]"), r
    assert "合并 1 节" in r
    assert "缺失 1 节未并入：3.2 总体设计方案" in r
    assert "模板填充类未产出 1 节（按附件对待，不占整本位）：附件：资质证书复印件" in r

    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    paras = chk.paragraphs
    assert paras[0].style.name == "Title" and paras[0].text == "技术部分"
    assert paras[1].style.name == "Heading 1" and paras[1].text == "第三章 技术方案"
    assert paras[2].style.name == "Heading 2" and paras[2].text == "3.1 项目理解与需求分析"
    texts = [p.text for p in paras]
    assert texts.count("3.1 项目理解与需求分析") == 1  # 节文件自带标题段已跳过
    assert "3.1 正文第一段。" in texts
    assert not any("资质证书复印件" in t for t in texts)  # 未产出格式件不进整本
    # 页脚页码域（可打印闭环）
    assert "PAGE" in chk.sections[0].footer.paragraphs[0]._p.xml
    # 重复合册：整本自身不算孤儿（派生产物；缺失节点名的「未并入」仍在）
    r2 = docx_assemble_volume.invoke({})
    assert "个节文件未并入" not in r2


def test_assemble_includes_produced_format_node(env):
    """模板填充叶子产出节文件即按树序并进整本（格式件是标书组成部分）。"""
    _seed_dir_artifact(env, _DIR_SINGLE)
    docx_section_create.invoke(
        {"path": "body/3.1 项目理解与需求分析", "title": "3.1 项目理解与需求分析",
         "paragraphs": "3.1 正文第一段。"}
    )
    docx_section_create.invoke(
        {"path": "body/附件：资质证书复印件", "title": "附件：资质证书复印件",
         "paragraphs": "（复印件附后）"}
    )
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]") and "合并 2 节" in r, r
    assert "模板填充类未产出" not in r
    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    texts = [p.text for p in chk.paragraphs]
    assert "（复印件附后）" in texts
    assert texts.count("附件：资质证书复印件") == 1  # 树序标题一份（节文件自带标题已跳过）
    assert "个节文件未并入" not in r  # 格式件文件已消费，不算孤儿


def test_assemble_preserves_revision_marks_and_images(env):
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "3.1 运维方案", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": ["REQ-01"]},
            ]}
        ]
    })
    section = "body/3.1 运维方案.docx"
    assert docx_section_create.invoke({"path": section, "title": "3.1 运维方案"}).startswith("[已创建]")
    assert docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section}).startswith("[已注入]")
    view = docx_section_read.invoke({"path": section})
    para_no = next(int(ln.split("]")[0][2:]) for ln in view.splitlines() if COMPANY in ln)
    assert docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"para": para_no, "action": "replace", "find": COMPANY, "text": "上海中信科技有限公司"},
    ])}).startswith("[已修订]")

    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]") and "含图片 1 张" in r, r
    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    assert chk.element.body.find(".//" + qn("w:ins")) is not None  # 修订标记原样保留
    assert chk.element.body.find(".//" + qn("w:del")) is not None
    for blip in chk.element.body.findall(".//" + qn("a:blip")):
        assert blip.get(qn("r:embed")) in chk.part.related_parts  # 图片关系完好


def test_assemble_multi_volume_and_orphans(env):
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "3.1 项目理解", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ]},
            {"name": "商务部分", "scope": "", "directory": [
                {"目录名称": "6.1 售后服务承诺", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ]},
        ]
    })
    docx_section_create.invoke({"path": "body/技术部分/3.1 项目理解", "title": "3.1 项目理解", "paragraphs": "正文"})
    docx_section_create.invoke({"path": "body/旧版遗留节", "title": "旧版遗留节", "paragraphs": "旧稿"})
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]")
    assert _abs(env, "body/整本-技术部分.docx").is_file()
    assert "[合册失败]" not in r
    assert "商务部分：无已写节文件" in r  # 缺失整册也只报事实，不炸
    assert "未并入" in r and "body/旧版遗留节.docx" in r  # 孤儿节文件点名


def test_assemble_without_directory_errors(env):
    assert "[合册失败] 无投标目录产物" in docx_assemble_volume.invoke({})


# ---------- 终稿视角文本抽取 ----------


def test_section_text_lines_accepted_view(env):
    """校验对象=接受全部修订后的终稿：插入修订计入、删除修订不计。"""
    from app.tools.docx_ops import section_text_lines

    section = _make_section()
    assert docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"para": 1, "action": "insert_after", "text": "插入的新段落"},
    ])}).startswith("[已修订]")
    assert "插入的新段落" in section_text_lines(Document(str(_abs(env, section))))

    section2 = "body/删除演示.docx"
    assert docx_section_create.invoke(
        {"path": section2, "title": "X", "paragraphs": "保留段\n删除段"}
    ).startswith("[已创建]")
    assert docx_section_revise.invoke({"path": section2, "edits": json.dumps([
        {"para": 3, "action": "delete"},  # P3=删除段（P1=标题、P2=保留段）
    ])}).startswith("[已修订]")
    # 被删段以空行占位：P 段号与读视图对齐，终稿视角内容消失
    assert section_text_lines(Document(str(_abs(env, section2)))) == ["X", "保留段", ""]


# ---------- review 修复批（2026-09-07）----------


def test_revise_replace_across_revision_boundary(env):
    """二轮修订替换横跨「上一轮插入内容 + 原文」边界：每个匹配 run 原位包
    del（ins 内变 ins>del 嵌套、原文留 p>del），拒绝视角原文完整——共用单一
    del 挂首 run 位置会把原文 run 挪进 ins 子树，自校验必拒且模型无法自救。"""
    from app.tools.docx_ops import _accepted_text, _flatten_rejected

    section, _ = _injected_section(env)
    # 第一轮：换公司名（产生 w:ins）
    view = docx_section_read.invoke({"path": section})
    para_no = next(int(ln.split("]")[0][2:]) for ln in view.splitlines() if COMPANY in ln)
    r1 = docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"para": para_no, "action": "replace", "find": COMPANY, "text": "上海中信科技有限公司"},
    ])})
    assert r1.startswith("[已修订]"), r1
    rejected_before = _flatten_rejected(Document(str(_abs(env, section))))

    # 第二轮：find 横跨「新公司名（ins 内容）+ 原文『承建』」边界
    r2 = docx_section_revise.invoke({"path": section, "edits": json.dumps([
        {"para": para_no, "action": "replace", "find": "上海中信科技有限公司承建", "text": "我司承建"},
    ])})
    assert r2.startswith("[已修订]"), r2  # 自校验通过=落盘成功

    chk = Document(str(_abs(env, section)))
    para = chk.paragraphs[para_no - 1]
    assert _accepted_text(para._p) == "本项目由我司承建，服务期三年。"
    assert _flatten_rejected(chk) == rejected_before  # 拒绝全部修订=原文逐字一致


def test_tools_survive_corrupt_docx(env):
    """损坏 docx（用户上传的招标/素材原件是外部输入，半截文件是现实情况）：
    工具返回失败文案，不打崩 run。"""
    section = _make_section()
    _abs(env, section).write_bytes(b"not a zip file")
    assert docx_section_read.invoke({"path": section}).startswith("[读取失败]")
    assert docx_section_revise.invoke(
        {"path": section, "edits": json.dumps([{"para": 1, "action": "delete"}])}
    ).startswith("[修订失败]")
    # 素材原件损坏：element_map 是解析落盘的独立 json 仍可用，Document() 打开才炸
    src = mlib.mt_files_dir() / env["file"]["file_name"]
    src.write_bytes(b"\x50\x4b broken zip")
    section2 = _make_section("技术部分/3.2 另一节.docx")
    assert docx_material_inject.invoke(
        {"block_id": env["block"]["id"], "dest": section2}
    ).startswith("[注入失败]")


def test_dest_path_lexical_escape(env):
    """body/../ 单级穿越：词法前缀检查放行、resolve 后落 work/ 根——resolve 后的
    body 目录祖先链校验必须拦截。"""
    from app.artifact_store import work_dir

    r = docx_section_create.invoke({"path": "body/../escaped", "title": "x"})
    assert r.startswith("[创建失败]") and "work/body/" in r, r
    assert not (work_dir(env["task"]["id"]) / "escaped.docx").exists()


def test_revise_insert_after_keeps_submission_order(env):
    """同段连续 insert_after：文档顺序与提交顺序一致（游标锚=上次插入的新段，
    否则 addnext 紧跟定位段导致整批倒序）。"""
    section = _make_section()
    edits = [
        {"para": 1, "action": "insert_after", "text": "第一条"},
        {"para": 1, "action": "insert_after", "text": "第二条"},
        {"para": 1, "action": "insert_after", "text": "第三条"},
    ]
    r = docx_section_revise.invoke({"path": section, "edits": json.dumps(edits)})
    assert r.startswith("[已修订]") and "3 处" in r, r
    from app.tools.docx_ops import _accepted_text

    texts = [_accepted_text(p._p) for p in Document(str(_abs(env, section))).paragraphs]
    i = texts.index("第一条")
    assert texts[i + 1] == "第二条" and texts[i + 2] == "第三条"


def test_assemble_keeps_mismatched_own_heading(env):
    """节文件自带标题与树标题写法不一致：不吞（判据=样式+文本匹配节标题；
    只看 Heading1 会把素材自带的章标题静默剥掉——宁可重复发可见可修）。"""
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "3.1 运维方案", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ]}
        ]
    })
    # 建档标题写法与树节点不一致（素材整章注入后，素材自己的章标题同款形态）
    assert docx_section_create.invoke({"path": "body/3.1 运维方案", "title": "运维方案"}).startswith("[已创建]")
    assert docx_material_inject.invoke(
        {"block_id": env["block"]["id"], "dest": "body/3.1 运维方案.docx"}
    ).startswith("[已注入]")
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]"), r
    texts = [p.text for p in Document(str(_abs(env, "body/整本-技术部分.docx"))).paragraphs]
    assert "3.1 运维方案" in texts  # 树标题照发
    assert "运维方案" in texts  # 节自带标题不被吞
    assert "运维服务方案" in texts  # 素材章标题内容保留
