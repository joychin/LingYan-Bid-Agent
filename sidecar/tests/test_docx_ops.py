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
    _accepted_text,
    _flatten_rejected,
    docx_assemble_volume,
    docx_comment_add,
    docx_image_insert,
    docx_material_inject,
    docx_section_create,
    docx_section_read,
    docx_section_revise,
    docx_source_inject,
    section_text_lines,
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
    assert "[P2]（Tender Body）第一段。" in view
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
    from app import db
    from app.artifact_store import work_dir

    # 注入落盘成功 → AI 引用打点 +1
    assert db.mt_get_block(env["block"]["id"])["use_count"] == 1

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


def test_material_inject_body_style_adoption(env):
    """素材适配模板（2026-09-08 用户拍板：素材库拷贝归顺模板、招标格式件
    保真）：无样式引用的素材正文段挂 Tender Body（标书缩进/行距，与 AI 正文
    同观感——此前吃中性 Normal 不缩进是观感割裂主因）；表格整表与表内文字
    不受影响；素材标题段引用内置 Heading 自动吃宿主（模板）定义；招标格式件
    拷贝不挂样式（格式由招标文件定死）。"""
    section = _make_section()
    assert docx_material_inject.invoke(
        {"block_id": env["block"]["id"], "dest": section}
    ).startswith("[已注入]")
    doc = Document(str(_abs(env, section)))
    body = [p for p in doc.paragraphs if p.text.startswith("本项目由")]
    assert body and all(p.style.name == "Tender Body" for p in body)
    assert any(
        p.text == "运维服务方案" and p.style.name == "Heading 1" for p in doc.paragraphs
    )
    # 表格整表保真：单元格段落不被挂样式（无显式引用，渲染吃 Normal）
    cell_p = doc.tables[0].rows[0].cells[0].paragraphs[0]._p
    cell_ppr = cell_p.find(qn("w:pPr"))
    assert cell_ppr is None or cell_ppr.find(qn("w:pStyle")) is None

    # 招标格式件：保真不挂（同款无样式正文段保持原样）
    _tender_source(env)
    section2 = _make_section("技术部分/投标函.docx")
    assert docx_source_inject.invoke(
        {"source": "招标文件.docx", "dest": section2}
    ).startswith("[已注入]")
    chk = Document(str(_abs(env, section2)))
    zh = [p for p in chk.paragraphs if p.text == "致：______（招标人名称）"]
    assert zh
    zh_ppr = zh[0]._p.find(qn("w:pPr"))
    assert zh_ppr is None or zh_ppr.find(qn("w:pStyle")) is None


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


def test_element_lines_coords_match_md_after_tables(tmp_path):
    """坐标系统一回归（2026-09-10）：表格逐行展开后 element_lines 行号=最终 md
    行号。修复前表格整块 append（内嵌换行不占下标），映射坐标在表格后累计
    漂移——表格后段落按 md 行号找不到元素（实测 13 表拉开 140 行）。"""
    from app.parse.docx import convert

    doc = Document()
    doc.add_heading("第一章 公告", 1)
    doc.add_paragraph("公告正文第一段。")
    t = doc.add_table(rows=3, cols=2)
    t.style = "Table Grid"
    for r in range(3):
        t.cell(r, 0).text = f"行{r}"
        t.cell(r, 1).text = f"值{r}"
    doc.add_heading("附件14：承诺书", 2)
    doc.add_paragraph("我单位承诺：拟派项目经理准时到位。")
    p = tmp_path / "原件.docx"
    doc.save(p)

    res = convert(p)
    md_lines = res.md.splitlines()
    line_no = next(i for i, ln in enumerate(md_lines, 1) if "我单位承诺" in ln)
    els = res.info["element_lines"]
    assert max(e for _el, s, e in els) == len(md_lines), "映射未覆盖到 md 末行（坐标系漂移）"
    hit = [(s, e) for _el, s, e in els if s <= line_no <= e]
    assert hit, "表格后段落未映射（坐标系漂移回归）"
    assert any("我单位承诺" in "\n".join(md_lines[s - 1 : e]) for s, e in hit)


def test_source_inject_outline_range_after_table(env):
    """端到端：按 outline.json 的行号区间注入「表格之后」的附件——写手探针
    风暴的真实形态（承诺书在多张表后，修复前按 outline 区间注入必「未映射」，
    写手被迫逐段试探）。"""
    from app.artifact_store import sources_dir
    from app.parse import convert as parse_convert
    from app.parse import outline_with_lines

    doc = Document()
    doc.add_heading("第一章 招标公告", 1)
    doc.add_paragraph("公告正文。")
    for ti in range(2):
        t = doc.add_table(rows=3, cols=2)
        t.style = "Table Grid"
        for r in range(3):
            t.cell(r, 0).text = f"表{ti}行{r}"
            t.cell(r, 1).text = "值"
    doc.add_heading("附件14：承诺书", 1)
    doc.add_paragraph("我单位承诺：拟派项目经理将准时到位。")
    sroot = sources_dir(env["task"]["id"])
    sroot.mkdir(parents=True, exist_ok=True)
    doc.save(sroot / "谈判文件.docx")

    def find(tree, kw):
        for n in tree:
            if kw in n["标题"]:
                return n
            hit = find(n.get("children") or [], kw)
            if hit:
                return hit
        return None

    node = find(outline_with_lines(parse_convert(sroot / "谈判文件.docx").md), "承诺书")
    assert node is not None
    section = _make_section()
    r = docx_source_inject.invoke(
        {"source": "谈判文件.docx", "dest": section, "lines": f"{node['start_line']}-{node['end_line']}"}
    )
    assert r.startswith("[已注入]"), r
    chk = Document(str(_abs(env, section)))
    texts = "\n".join(p.text for p in chk.paragraphs)
    assert "附件14：承诺书" in texts and "我单位承诺" in texts
    assert "招标公告" not in texts and len(chk.tables) == 0  # 表前的表不被误带


def test_material_inject_block_after_table(env, tmp_path):
    """素材块勾选区间落在表格之后：映射须命中正确元素（修复前两套坐标漂移，
    表格后区块注入错元素或「未映射」——素材库「勾选区间需复核」的部分根因）。"""
    from app import db

    doc = Document()
    doc.add_heading("运维方案", 1)
    t = doc.add_table(rows=3, cols=2)
    t.style = "Table Grid"
    for r in range(3):
        t.cell(r, 0).text = f"行{r}"
        t.cell(r, 1).text = "值"
    doc.add_paragraph("独家承诺文本：现场服务响应时间两小时。")
    src = mlib.mt_files_dir() / "补充素材.docx"
    doc.save(src)
    f = db.mt_insert_file("补充素材.docx", "hash_docx_after_table")
    mlib.run_parse(f["id"])
    md_lines = mlib.mt_parse_paths("补充素材.docx")[0].read_text(encoding="utf-8").splitlines()
    ln = next(i for i, l in enumerate(md_lines, 1) if "独家承诺文本" in l)
    block = mlib.create_block(f["id"], "表格后承诺段", "勾选表格后段落", ranges=[[ln, ln]])

    section = _make_section()
    r = docx_material_inject.invoke({"block_id": block["id"], "dest": section})
    assert r.startswith("[已注入]"), r
    chk = Document(str(_abs(env, section)))
    texts = "\n".join(p.text for p in chk.paragraphs)
    assert "独家承诺文本：现场服务响应时间两小时。" in texts
    assert len(chk.tables) == 0  # 只注入勾选段，表格不带


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


# ---------- 编号定义冲突重映射（numbering id 只是文档内部门牌号） ----------


def _add_cn_numbering(doc, num_id: str, abs_id: str) -> None:
    """素材侧自定义中文编号：先替换模板自带的同 id 定义（素材内 id 唯一），
    与节文件模板的同 id 形成跨文档冲突——模拟历史标书的独立编号空间。"""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    np = doc.part.numbering_part.element
    for el in list(np.findall(qn("w:num"))):
        if el.get(qn("w:numId")) == num_id:
            np.remove(el)
    for el in list(np.findall(qn("w:abstractNum"))):
        if el.get(qn("w:abstractNumId")) == abs_id:
            np.remove(el)
    np.append(parse_xml(
        f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{abs_id}">'
        f'<w:multiLevelType w:val="hybridMultilevel"/>'
        f'<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="chineseCountingThousand"/>'
        f'<w:lvlText w:val="一、"/><w:lvlJc w:val="left"/></w:lvl></w:abstractNum>'
    ))
    np.append(parse_xml(
        f'<w:num {nsdecls("w")} w:numId="{num_id}"><w:abstractNumId w:val="{abs_id}"/></w:num>'
    ))


def _numbered_para(doc, text: str, num_id: str) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    p = doc.add_paragraph(text)
    p._p.get_or_add_pPr().append(parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
    ))


def _numbering_root(chk):
    return chk.part.numbering_part.element


def _numbered_para_ids(chk) -> list[str]:
    out = []
    for p in chk.paragraphs:
        ppr = p._p.find(qn("w:pPr"))
        numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if numpr is not None and numpr.find(qn("w:numId")) is not None:
            out.append(numpr.find(qn("w:numId")).get(qn("w:val")))
    return out


def _abs_ref_of(chk, num_id: str) -> str:
    num = next(n for n in _numbering_root(chk).findall(qn("w:num"))
               if n.get(qn("w:numId")) == num_id)
    return num.find(qn("w:abstractNumId")).get(qn("w:val"))


def _lvl_text_of_abs(chk, abs_id: str) -> str | None:
    abs_el = next(a for a in _numbering_root(chk).findall(qn("w:abstractNum"))
                  if a.get(qn("w:abstractNumId")) == abs_id)
    lvl0 = abs_el.find(qn("w:lvl"))
    return lvl0.find(qn("w:lvlText")).get(qn("w:val")) if lvl0 is not None else None


def test_material_inject_numbering_conflict_remapped(env):
    """numId 撞建节模板（模板自带 numId 1-9）：定义不同则重映射新 id、改写引用，
    素材编号定义保真、模板原定义不动——修复「同 id 即沿用目标定义」的静默错配。"""
    src = mlib.mt_files_dir() / "编号冲突素材.docx"
    doc = Document()
    doc.add_heading("人员配置", 1)
    _add_cn_numbering(doc, "2", "2")  # numId 与 abstractNumId 双撞模板
    _numbered_para(doc, "项目经理一名", "2")
    doc.save(src)

    from app import db

    f = db.mt_insert_file("编号冲突素材.docx", "hash_numc_1")
    mlib.run_parse(f["id"])
    block = mlib.create_block(f["id"], "编号冲突章", "", ranges=[[1, 1000]])
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": block["id"], "dest": section})
    assert r.startswith("[已注入]") and "编号定义 1 组" in r, r

    chk = Document(str(_abs(env, section)))  # 重新打开不炸 = 迁入 XML 可解析
    used = _numbered_para_ids(chk)
    assert used == [used[0]] and used[0] != "2"  # 引用已重映射，不再指向模板 numId 2
    assert _lvl_text_of_abs(chk, _abs_ref_of(chk, used[0])) == "一、"  # 素材定义保真
    assert _lvl_text_of_abs(chk, _abs_ref_of(chk, "2")) != "一、"  # 模板原定义未被改动


def test_material_inject_numbering_sequence_semantics(env):
    """同一块内的多段共享同一重映射（列表编号连续）；另一块再注入=独立序列
    （跨调用不复用映射——不同素材的同定义列表不得被错误并接成连续编号）。"""
    src = mlib.mt_files_dir() / "编号序列素材.docx"
    doc = Document()
    doc.add_heading("服务承诺", 1)
    _add_cn_numbering(doc, "2", "2")
    _numbered_para(doc, "七乘二十四小时响应", "2")
    _numbered_para(doc, "两小时内到场", "2")
    doc.add_heading("培训计划", 1)
    _numbered_para(doc, "管理员培训一期", "2")
    doc.save(src)

    from app import db

    f = db.mt_insert_file("编号序列素材.docx", "hash_nums_1")
    mlib.run_parse(f["id"])
    block1 = mlib.create_block(f["id"], "承诺章", "", ranges=[[1, 3]])
    block2 = mlib.create_block(f["id"], "培训章", "", ranges=[[4, 1000]])
    section = _make_section()
    assert docx_material_inject.invoke({"block_id": block1["id"], "dest": section}).startswith("[已注入]")
    chk = Document(str(_abs(env, section)))
    first_two = _numbered_para_ids(chk)
    assert len(first_two) == 2 and first_two[0] == first_two[1]  # 块内两段同一编号方案

    assert docx_material_inject.invoke({"block_id": block2["id"], "dest": section}).startswith("[已注入]")
    chk = Document(str(_abs(env, section)))
    ids = _numbered_para_ids(chk)
    assert len(ids) == 3
    assert ids[2] != ids[0]  # 跨块独立序列（不被并接）
    assert _lvl_text_of_abs(chk, _abs_ref_of(chk, ids[2])) == "一、"  # 定义仍保真


def test_material_inject_numbering_abs_conflict_only(env):
    """numId 不撞但 abstractNumId 撞模板：定义不同则 abstractNum 换新 id 迁入，
    num 保留原 id 改指向——此前这条轴同样静默错配。"""
    src = mlib.mt_files_dir() / "编号半撞素材.docx"
    doc = Document()
    doc.add_heading("售后条款", 1)
    _add_cn_numbering(doc, "77", "3")  # numId 不撞；abstractNumId=3 撞模板且定义不同
    _numbered_para(doc, "质保期三年", "77")
    doc.save(src)

    from app import db

    f = db.mt_insert_file("编号半撞素材.docx", "hash_numh_1")
    mlib.run_parse(f["id"])
    block = mlib.create_block(f["id"], "编号半撞章", "", ranges=[[1, 1000]])
    section = _make_section()
    assert docx_material_inject.invoke({"block_id": block["id"], "dest": section}).startswith("[已注入]")

    chk = Document(str(_abs(env, section)))
    used = _numbered_para_ids(chk)
    assert used == ["77"]  # numId 不撞 → 原 id 保留
    new_abs = _abs_ref_of(chk, "77")
    assert new_abs != "3"  # abstractNum 已换新 id（不指向模板的 3）
    assert _lvl_text_of_abs(chk, new_abs) == "一、"  # 素材定义保真
    assert _lvl_text_of_abs(chk, "3") != "一、"  # 模板 abstractNum 3 未被改动


# ---------- 2026-09-08 机制修复：分节符/字体/丢图/锚定漂移/重复注入 ----------


def test_material_inject_strips_inner_sectpr(env):
    """素材段内分节符（横向页等版式设置）不得随元素拷贝进入节文件——否则
    分节属性中途生效、版式突变（合册同引擎同防线）。"""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    src = mlib.mt_files_dir() / "分节素材.docx"
    doc = Document()
    doc.add_heading("带分节的章", 1)
    p = doc.add_paragraph("章末段落")
    p._p.get_or_add_pPr().append(parse_xml(
        f'<w:sectPr {nsdecls("w")}><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/></w:sectPr>'
    ))
    doc.save(src)

    from app import db

    f = db.mt_insert_file("分节素材.docx", "hash_sect_1")
    mlib.run_parse(f["id"])
    block = mlib.create_block(f["id"], "分节章", "", ranges=[[1, 1000]])
    section = _make_section()
    assert docx_material_inject.invoke({"block_id": block["id"], "dest": section}).startswith("[已注入]")
    chk = Document(str(_abs(env, section)))
    assert len(chk.element.body.findall(".//" + qn("w:sectPr"))) == 1  # 仅节文件文末分节


def _east(doc, style: str):
    rpr = doc.styles[style].element.find(qn("w:rPr"))
    fonts = rpr.find(qn("w:rFonts")) if rpr is not None else None
    return fonts.get(qn("w:eastAsia")) if fonts is not None else None


def test_base_template_layout_on_create_and_assemble(env):
    """建节/合册从标书基准模板起建（格式与内容分离，模板由
    scripts/make_base_template.py 维护）：中文 eastAsia 定死、正文段挂
    Tender Body（1.5 倍行距+首行缩进 2 字符）、标题黑体加粗黑色（默认英文
    模板的蓝色英文脸是「生成的 Word 难看」的根源）、封面两档居中、A4+页脚
    页码域。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    from app import publish
    from app.artifact_store import work_dir

    section = _make_section("项目理解与需求分析.docx")
    docx_section_create.invoke({  # 已存在 → 覆盖重写，带初始正文段
        "path": section, "title": "项目理解与需求分析",
        "paragraphs": "本项目团队对采购需求的理解如下。", "replace": True,
    })
    doc = Document(str(work_dir(env["task"]["id"]) / section))
    assert _east(doc, "Normal") == "宋体"
    assert _east(doc, "Heading 1") == "黑体"
    h1 = doc.styles["Heading 1"]
    assert h1.font.color.rgb == RGBColor(0, 0, 0) and h1.font.size == Pt(18)
    body = doc.styles["Tender Body"]
    assert body.paragraph_format.line_spacing == 1.5
    ind = body.element.get_or_add_pPr().find(qn("w:ind"))
    assert ind.get(qn("w:firstLineChars")) == "200"
    cover = doc.styles["Tender Cover"]
    assert _east(doc, "Tender Cover") == "黑体"
    assert cover.font.size == Pt(22)
    assert cover.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.styles["Tender Cover Sub"]
    assert sub.font.size == Pt(15) and sub.font.bold is False
    assert sub.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert doc.paragraphs[0].style.name == "Heading 1"
    assert doc.paragraphs[1].style.name == "Tender Body"
    # 模板带的样式示例段在建节产物中整段剥离（body 只留版面）
    assert len(doc.paragraphs) == 2
    assert "样式示例" not in "\n".join(p.text for p in doc.paragraphs)
    pgsz = doc.element.body.find(qn("w:sectPr")).find(qn("w:pgSz"))
    assert pgsz.get(qn("w:w")) == "11906"  # A4
    footer = doc.sections[0].footer._element
    assert any("PAGE" in (t.text or "") for t in footer.iter(qn("w:instrText")))

    publish.publish_artifact(_KEY, _DIR_SINGLE, task_id=env["task"]["id"], conversation_id=env["conv"]["id"])
    assert docx_assemble_volume.invoke({}).startswith("[已合册]")
    vol = Document(str(work_dir(env["task"]["id"]) / "body" / "整本-技术部分.docx"))
    assert _east(vol, "Normal") == "宋体"
    # 模板页脚自带页码域，合册不再手拼（双重页码回归守卫）
    n_fields = sum(
        1 for t in vol.sections[0].footer._element.iter(qn("w:instrText"))
        if "PAGE" in (t.text or "")
    )
    assert n_fields == 1


def test_material_inject_image_only_para_survives(env):
    """纯图片段落在「连续第 3 空行」位不再被空行折叠吃出元素映射——占位行
    保命，图片可注入（2026-09-08 丢图实证的修复）。"""
    src = mlib.mt_files_dir() / "空窗图片素材.docx"
    png = src.parent / "_tiny.png"
    _tiny_png(png)
    doc = Document()
    doc.add_heading("图集", 1)
    doc.add_paragraph("")
    doc.add_paragraph("")
    doc.add_picture(str(png))  # 连续第 3 个空行位（原实现会折叠丢图）
    doc.add_heading("收尾", 1)
    doc.save(src)

    from app import db

    f = db.mt_insert_file("空窗图片素材.docx", "hash_imgwin_1")
    mlib.run_parse(f["id"])
    md = (mlib.mt_parse_dir("空窗图片素材.docx") / "空窗图片素材.docx.md").read_text(encoding="utf-8")
    assert "![](图片)" in md  # 占位行可见（勾选界面/预览同见）
    block = mlib.create_block(f["id"], "图集章", "", ranges=[[1, 1000]])
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": block["id"], "dest": section})
    assert r.startswith("[已注入]") and "图片 1 张" in r  # 图注入成功
    chk = Document(str(_abs(env, section)))
    assert chk.element.body.findall(".//" + qn("a:blip"))


def test_material_inject_reparse_drift_rejected(env):
    """补跑映射时 md 与盘上不一致（模拟解析代码升级重排）：拒绝注入点名重勾，
    不静默按错位区间拷错元素。"""
    md_path = mlib.mt_parse_dir("历史运维方案.docx") / "历史运维方案.docx.md"
    md_path.write_text("被篡改的旧 md，行号与重解析产物必然不同。\n" * 3, encoding="utf-8")
    (md_path.parent / "element_map.json").unlink()
    section = _make_section()
    r = docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section})
    assert r.startswith("[注入失败]") and "勾选区间会错位" in r
    assert "重新确认该文件的勾选" in r


def test_material_inject_duplicate_blocked(env):
    """同块二次注入同一节文件被拦：注入是追加语义，重复=内容翻倍，无正当场景。"""
    section = _make_section()
    assert docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section}).startswith("[已注入]")
    r = docx_material_inject.invoke({"block_id": env["block"]["id"], "dest": section})
    assert r.startswith("[注入失败]") and "已注入过" in r


# ---------- 整本合册 ----------

_KEY = "tender.directory/tender-response-docs@1"

_DIR_SINGLE = {
    "response_documents": [
        {
            "name": "技术部分",
            "scope": "",
            "directory": [
                {"目录名称": "技术方案", "level": 1, "children": [
                    {"目录名称": "项目理解与需求分析", "level": 2, "children": [],
                     "交付形态": "正文编写", "来源位置": ["REQ-01"]},
                    {"目录名称": "总体设计方案", "level": 2, "children": [],
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
    """树序合册：容器标题层级随树深、标题按树序自动编号（缺省第X章+1.1）、
    节文件自带标题跳过（对账用裸名，不受编号影响）、缺失节点名、
    模板填充叶子未产出按附件对待（点名不占位）；重跑覆盖且整本不算孤儿。"""
    _seed_dir_artifact(env, _DIR_SINGLE)
    docx_section_create.invoke(
        {"path": "body/项目理解与需求分析", "title": "项目理解与需求分析",
         "paragraphs": "项目理解正文第一段。"}
    )
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]"), r
    assert "合并 1 节" in r
    assert "缺失 1 节未并入：总体设计方案" in r
    assert "模板填充类未产出 1 节（按附件对待，不占整本位）：附件：资质证书复印件" in r

    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    paras = chk.paragraphs
    assert paras[0].style.name == "Title" and paras[0].text == "技术部分"
    assert paras[1].style.name == "Heading 1" and paras[1].text == "第一章\u3000技术方案"
    assert paras[2].style.name == "Heading 2" and paras[2].text == "1.1 项目理解与需求分析"
    texts = [p.text for p in paras]
    assert texts.count("1.1 项目理解与需求分析") == 1  # 节文件自带标题段已跳过（编号后标题仍只一份）
    assert "项目理解正文第一段。" in texts
    assert not any("资质证书复印件" in t for t in texts)  # 未产出格式件不进整本
    # 页脚页码域（可打印闭环）
    assert "PAGE" in chk.sections[0].footer.paragraphs[0]._p.xml
    # 重复合册：整本自身不算孤儿（派生产物；缺失节点名的「未并入」仍在）
    r2 = docx_assemble_volume.invoke({})
    assert "个节文件未并入" not in r2


_DIR_COVER = {
    "response_documents": [
        {
            "name": "技术部分",
            "scope": "",
            "directory": [
                {"目录名称": "封面", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
                {"目录名称": "技术方案", "level": 1, "children": [
                    {"目录名称": "项目理解与需求分析", "level": 2, "children": [],
                     "交付形态": "正文编写", "来源位置": ["REQ-01"]},
                ]},
            ],
        }
    ]
}


def test_revise_insert_with_style(env):
    """insert_after 可带 style 字段挂指定版式（封面行）；样式不存在回落正文
    样式且返回注记——用户自定义版式缺封面样式名不失败。"""
    section = _make_section()
    edits = json.dumps([
        {"para": 1, "action": "insert_after", "text": "XX 项目投标文件",
         "style": "Tender Cover"},
        {"para": 1, "action": "insert_after", "text": "投标人：XX 有限公司",
         "style": "Tender Cover Sub"},
        {"para": 1, "action": "insert_after", "text": "未知样式行",
         "style": "不存在的样式"},
    ], ensure_ascii=False)
    r = docx_section_revise.invoke({"path": section, "edits": edits})
    assert r.startswith("[已修订]")
    assert "不存在的样式" in r and "正文样式" in r
    chk = Document(str(_abs(env, section)))
    # 插入段在 w:ins 修订包裹里，p.text 读不到——按接受视角取文本
    by_text = {_accepted_text(p._p): p.style.name for p in chk.paragraphs}
    assert by_text["XX 项目投标文件"] == "Tender Cover"
    assert by_text["投标人：XX 有限公司"] == "Tender Cover Sub"
    assert by_text["未知样式行"] == "Tender Body"  # 回落正文样式


def test_assemble_cover_node(env):
    """封面=树首一级叶子（名「封面」）：整本首页即封面页——无册名 Title、
    无「封面」标题行（节文件标题段照旧剥）、封面行挂 Tender Cover、开
    「首页不同」（封面页无页眉页脚）、第一章分页让封面独占一页。"""
    _seed_dir_artifact(env, _DIR_COVER)
    docx_section_create.invoke({"path": "body/封面", "title": "封面"})
    docx_section_revise.invoke({"path": "body/封面", "edits": json.dumps([
        {"para": 1, "action": "insert_after", "text": "XX 项目投标文件（技术部分）",
         "style": "Tender Cover"},
        {"para": 1, "action": "insert_after", "text": "投标人：XX 有限公司",
         "style": "Tender Cover Sub"},
    ], ensure_ascii=False)})
    docx_section_create.invoke(
        {"path": "body/项目理解与需求分析", "title": "项目理解与需求分析",
         "paragraphs": "项目理解正文第一段。"}
    )
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]") and "缺失" not in r and "未产出" not in r

    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    paras = chk.paragraphs
    # 封面行是修订插入（run 在 w:ins 里），文本按接受视角取
    texts = [_accepted_text(p._p) for p in paras]
    assert paras[0].style.name == "Tender Cover" and texts[0] == "XX 项目投标文件（技术部分）"
    assert not any(p.style.name == "Title" for p in paras)  # 册名大标题被跳过
    assert "封面" not in texts  # 封面节点自身标题不发、节文件标题段被剥
    # 封面不占编号序：第一个内容章仍是「第一章」
    chapter = next(p for t, p in zip(texts, paras) if t == "第一章\u3000技术方案")
    assert chapter.paragraph_format.page_break_before is True  # 封面独占首页
    assert chk.sections[0].different_first_page_header_footer is True
    assert "PAGE" in chk.sections[0].footer.paragraphs[0]._p.xml  # 默认页脚仍在


def test_assemble_cover_missing_reported(env):
    """封面缺节文件的两种形态照旧点名（正文编写→缺失正文节；模板或附件填充→
    按附件对待），册名 Title 同样跳过（封面位由树决定，不因缺文件回退双标题）。"""
    _seed_dir_artifact(env, _DIR_COVER)
    docx_section_create.invoke(
        {"path": "body/项目理解与需求分析", "title": "项目理解与需求分析",
         "paragraphs": "项目理解正文第一段。"}
    )
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]")
    assert "缺失 1 节未并入：封面" in r
    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    assert chk.paragraphs[0].style.name == "Heading 1"  # 无 Title，直接进第一章

    import copy

    non_prose = copy.deepcopy(_DIR_COVER)
    non_prose["response_documents"][0]["directory"][0]["交付形态"] = "模板或附件填充"
    _seed_dir_artifact(env, non_prose)
    r2 = docx_assemble_volume.invoke({})
    assert r2.startswith("[已合册]")
    assert "模板填充类未产出 1 节（按附件对待，不占整本位）：封面" in r2
    chk2 = Document(str(_abs(env, "body/整本-技术部分.docx")))
    assert chk2.paragraphs[0].style.name == "Heading 1"


def test_assemble_includes_produced_format_node(env):
    """模板填充叶子产出节文件即按树序并进整本（格式件是标书组成部分），
    与正文统一编号（拍板 2026-09-10：格式件章也占章序）。"""
    _seed_dir_artifact(env, _DIR_SINGLE)
    docx_section_create.invoke(
        {"path": "body/项目理解与需求分析", "title": "项目理解与需求分析",
         "paragraphs": "项目理解正文第一段。"}
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
    assert texts.count("第二章\u3000附件：资质证书复印件") == 1  # 树序标题一份（格式件章统一编号；节文件自带标题已跳过）
    assert "个节文件未并入" not in r  # 格式件文件已消费，不算孤儿


def test_assemble_preserves_revision_marks_and_images(env):
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "运维方案", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": ["REQ-01"]},
            ]}
        ]
    })
    section = "body/运维方案.docx"
    assert docx_section_create.invoke({"path": section, "title": "运维方案"}).startswith("[已创建]")
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


def test_assemble_migrates_comments_and_warns_inline(env):
    """节内待办批注迁入整本（id 重映射、标记不悬空）；内联占位兜底扫描点名。"""
    _seed_dir_artifact(env, _DIR_SINGLE)
    docx_section_create.invoke(
        {"path": "body/项目理解与需求分析", "title": "项目理解与需求分析",
         "paragraphs": "项目理解正文第一段。"}
    )
    assert docx_comment_add.invoke({
        "path": "body/项目理解与需求分析.docx", "after": "2",
        "text": "缺项目批复文件编号，待用户确认",
    }).startswith("[已加批注]")
    docx_section_create.invoke(
        {"path": "body/总体设计方案", "title": "总体设计方案",
         "paragraphs": "方案正文。\n【待补：分项报价表金额】"}
    )
    assert docx_comment_add.invoke({
        "path": "body/总体设计方案.docx",
        "text": "分项报价表金额缺口径，待澄清",
    }).startswith("[已加批注]")

    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]") and "含批注 2 条待处理" in r, r
    assert "正文含 1 处内联占位" in r
    assert "总体设计方案(P3)：【待补：分项报价表金额】" in r

    chk = Document(str(_abs(env, "body/整本-技术部分.docx")))
    cmts = list(chk.comments)
    assert {c.text for c in cmts} == {"缺项目批复文件编号，待用户确认", "分项报价表金额缺口径，待澄清"}
    # 正文标记 id 已重映射、各自指向存在的批注（不悬空、不串号）
    starts = chk.element.body.findall(".//" + qn("w:commentRangeStart"))
    assert {s.get(qn("w:id")) for s in starts} == {str(c.comment_id) for c in cmts}


def test_assemble_multi_volume_and_orphans(env):
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "项目理解", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ]},
            {"name": "商务部分", "scope": "", "directory": [
                {"目录名称": "售后服务承诺", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ]},
        ]
    })
    docx_section_create.invoke({"path": "body/技术部分/项目理解", "title": "项目理解", "paragraphs": "正文"})
    docx_section_create.invoke({"path": "body/旧版遗留节", "title": "旧版遗留节", "paragraphs": "旧稿"})
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]")
    assert _abs(env, "body/整本-技术部分.docx").is_file()
    assert "[合册失败]" not in r
    assert "商务部分：无已写节文件" in r  # 缺失整册也只报事实，不炸
    assert "未并入" in r and "body/旧版遗留节.docx" in r  # 孤儿节文件点名


def test_assemble_without_directory_errors(env):
    assert "[合册失败] 无投标目录产物" in docx_assemble_volume.invoke({})


_DIR_NUMBERING = {
    "response_documents": [
        {
            "name": "技术部分", "scope": "",
            "directory": [
                {"目录名称": "总体部署", "level": 1, "children": [
                    {"目录名称": "部署原则", "level": 2, "children": [
                        {"目录名称": "安全原则", "level": 3, "children": [],
                         "交付形态": "正文编写", "来源位置": []},
                    ]},
                    {"目录名称": "分步实施", "level": 2, "children": [],
                     "交付形态": "正文编写", "来源位置": []},
                ]},
                {"目录名称": "售后服务", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ],
        },
        {
            "name": "商务部分", "scope": "",
            "directory": [
                {"目录名称": "报价说明", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ],
        },
    ]
}


def test_assemble_numbering_schemes(env):
    """章节编号=树位置的纯函数：缺省 chapter（第X章全角空格+1.1）、decimal、
    gov、none 四格式按树序生成；多册各自从首章重起；编号后 _is_title_para
    对账剥标题仍按裸名（自带标题段只剥一份）。"""
    import copy

    for name in ("安全原则", "分步实施", "售后服务"):
        docx_section_create.invoke(
            {"path": f"body/技术部分/{name}", "title": name, "paragraphs": "正文"}
        )
    docx_section_create.invoke(
        {"path": "body/商务部分/报价说明", "title": "报价说明", "paragraphs": "正文"}
    )

    def headings() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for vol in ("技术部分", "商务部分"):
            doc = Document(str(_abs(env, f"body/整本-{vol}.docx")))
            out[vol] = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        return out

    # 缺省（产物无 numbering 字段）=chapter
    _seed_dir_artifact(env, _DIR_NUMBERING)
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]") and "⚠️" not in r, r
    assert headings()["技术部分"] == [
        "第一章\u3000总体部署", "1.1 部署原则", "1.1.1 安全原则",
        "1.2 分步实施", "第二章\u3000售后服务",
    ]
    assert headings()["商务部分"] == ["第一章\u3000报价说明"]  # 各册从首章重起

    for scheme, expected in (
        ("decimal", ["1 总体部署", "1.1 部署原则", "1.1.1 安全原则", "1.2 分步实施", "2 售后服务"]),
        ("gov", ["一、总体部署", "（一）部署原则", "1.安全原则", "（二）分步实施", "二、售后服务"]),
        ("none", ["总体部署", "部署原则", "安全原则", "分步实施", "售后服务"]),
    ):
        content = copy.deepcopy(_DIR_NUMBERING)
        content["numbering"] = scheme
        _seed_dir_artifact(env, content)
        assert docx_assemble_volume.invoke({}).startswith("[已合册]")
        assert headings()["技术部分"] == expected, scheme


def test_assemble_warns_self_numbered_node_names(env):
    """目录节点名自带编号（树格式红线违例）：合册照常编号（双重编号如实可见）
    + ⚠️ 点名请用户修目录产物——探测+提示裁决，不是门禁。"""
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "第一章 技术方案", "level": 1, "children": [
                    {"目录名称": "1.1 项目理解", "level": 2, "children": [],
                     "交付形态": "正文编写", "来源位置": []},
                ]},
            ]}
        ]
    })
    docx_section_create.invoke(
        {"path": "body/1.1 项目理解", "title": "1.1 项目理解", "paragraphs": "正文"}
    )
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]")
    assert "2 个目录节点名自带编号" in r
    assert "第一章 技术方案" in r and "1.1 项目理解" in r
    assert "双重编号" in r
    texts = [p.text for p in Document(str(_abs(env, "body/整本-技术部分.docx"))).paragraphs]
    assert "第一章\u3000第一章 技术方案" in texts  # 双重编号如实可见
    assert "1.1 1.1 项目理解" in texts


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

    reopened = Document(str(_abs(env, section)))
    texts = [_accepted_text(p._p) for p in reopened.paragraphs]
    i = texts.index("第一条")
    assert texts[i + 1] == "第二条" and texts[i + 2] == "第三条"
    # 插入段挂模板正文样式（Tender Body：标书行距/缩进），不吃中性 Normal
    assert reopened.paragraphs[i].style.name == "Tender Body"


def test_assemble_keeps_mismatched_own_heading(env):
    """节文件自带标题与树标题写法不一致：不吞（判据=样式+文本匹配节标题；
    只看 Heading1 会把素材自带的章标题静默剥掉——宁可重复发可见可修）。"""
    _seed_dir_artifact(env, {
        "response_documents": [
            {"name": "技术部分", "scope": "", "directory": [
                {"目录名称": "运维实施方案", "level": 1, "children": [],
                 "交付形态": "正文编写", "来源位置": []},
            ]}
        ]
    })
    # 建档标题写法与树节点不一致（素材整章注入后，素材自己的章标题同款形态）
    assert docx_section_create.invoke({"path": "body/运维实施方案", "title": "运维方案"}).startswith("[已创建]")
    assert docx_material_inject.invoke(
        {"block_id": env["block"]["id"], "dest": "body/运维实施方案.docx"}
    ).startswith("[已注入]")
    r = docx_assemble_volume.invoke({})
    assert r.startswith("[已合册]"), r
    texts = [p.text for p in Document(str(_abs(env, "body/整本-技术部分.docx"))).paragraphs]
    assert "第一章\u3000运维实施方案" in texts  # 树标题照发（带程序编号）
    assert "运维方案" in texts  # 节自带标题不被吞
    assert "运维服务方案" in texts  # 素材章标题内容保留


# ---------- 单图插入（docx_image_insert：独立图片进正文的放图通道） ----------


def _kb_image(file_name: str = "ISO27001证书.pdf") -> str:
    """知识库抽取图：造进 knowledge/parse/<stem>/images/，返回工作区相对路径。"""
    from app.knowledge import store as kb_store

    img_dir = kb_store.kb_images_dir(file_name)
    img_dir.mkdir(parents=True, exist_ok=True)
    _tiny_png(img_dir / "img_001.png")
    return f"knowledge/parse/{Path(file_name).stem}/images/img_001.png"


def test_image_insert_after_paragraph(env):
    """知识库图插在指定段之后：位置/双修订标记/居中/全宽/拒绝视角不漂移/视图可见。"""
    rel = "body/技术部分/3.2 公司资质.docx"
    r = docx_section_create.invoke({
        "path": rel, "title": "3.2 公司资质",
        "paragraphs": "公司持有 ISO27001 信息安全管理体系认证证书。\n证书复印件见下图。",
    })
    assert r.startswith("[已创建]"), r
    r = docx_image_insert.invoke({"dest": rel, "image": _kb_image(), "after": "1"})
    assert r.startswith("[已插图]") and "P1 之后" in r, r

    doc = Document(str(_abs(env, rel)))
    paras = doc.paragraphs  # P1 标题、P2 图片、P3/P4 正文
    img_p = paras[1]._p
    assert len(img_p.findall(".//" + qn("a:blip"))) == 1
    # 段落标记修订（拒绝修订=整段含图消失）+ 内容修订（w:ins 包含图片 run）
    ppr = img_p.find(qn("w:pPr"))
    assert ppr.find(qn("w:rPr")).find(qn("w:ins")) is not None
    ins = img_p.find(qn("w:ins"))
    assert ins is not None and ins.find(".//" + qn("a:blip")) is not None
    # 居中、不挂正文样式（Tender Body 首行缩进会推偏图片）
    assert ppr.find(qn("w:jc")).get(qn("w:val")) == "center"
    assert ppr.find(qn("w:pStyle")) is None
    # 全宽适配：图片宽 = 页宽 − 左右边距（直取 wp:extent——python-docx 的
    # inline_shapes 视图只认 w:p 直接挂 w:r 的形态，修订包裹后匹配不到）
    sec = doc.sections[-1]
    cx = int(img_p.find(".//" + qn("wp:extent")).get("cx"))
    assert cx == int(sec.page_width - sec.left_margin - sec.right_margin)
    # 拒绝视角无空行漂移（工具内自校验的同款断言）
    assert _flatten_rejected(doc) == "3.2 公司资质\n公司持有 ISO27001 信息安全管理体系认证证书。\n证书复印件见下图。"
    # 读视图图片标签可见（模型后续按标签定位）
    assert "〔图×1〕" in docx_section_read.invoke({"path": rel})


def test_image_insert_append_at_end(env):
    """after 留空=追加到节末（sectPr 前）。"""
    rel = _make_section("技术部分/附图.docx")
    r = docx_image_insert.invoke({"dest": rel, "image": _kb_image()})
    assert r.startswith("[已插图]") and "节末" in r, r
    doc = Document(str(_abs(env, rel)))
    assert doc.paragraphs[-1]._p.findall(".//" + qn("a:blip"))


def test_image_insert_pdf_page_render(env):
    """PDF 原件按页现场渲染（抽取缺图的兜底）；任务前缀形态归一；页号越界人话报错。"""
    import pymupdf

    from app.artifact_store import sources_dir

    pdf = sources_dir(env["task"]["id"]) / "证书扫描件.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pd = pymupdf.open()
    pd.new_page().insert_text((72, 72), "ISO27001 CERTIFICATE")
    pd.save(str(pdf))
    pd.close()

    rel = _make_section("技术部分/3.2 公司资质.docx")
    r = docx_image_insert.invoke({"dest": rel, "image": "sources/证书扫描件.pdf", "page": 1})
    assert r.startswith("[已插图]") and "第 1 页" in r, r
    assert any(p._p.findall(".//" + qn("a:blip")) for p in Document(str(_abs(env, rel))).paragraphs)

    # 任务前缀形态（模型引用任务文件常带前缀）同样可插
    r = docx_image_insert.invoke({
        "dest": rel, "image": f"{env['task']['id']}/sources/证书扫描件.pdf", "after": "P1",
    })
    assert r.startswith("[已插图]"), r
    doc = Document(str(_abs(env, rel)))
    assert sum(len(p._p.findall(".//" + qn("a:blip"))) for p in doc.paragraphs) == 2

    # 页号超范围
    r = docx_image_insert.invoke({"dest": rel, "image": "sources/证书扫描件.pdf", "page": 5})
    assert r.startswith("[插图失败]") and "共 1 页" in r


def test_image_insert_rejects(env):
    """容错：越界/不存在/坏格式图源/段落号超范围/目标节缺失，全部人话报错。"""
    rel = _make_section("技术部分/附图.docx")
    assert docx_image_insert.invoke({"dest": rel, "image": "/etc/passwd"}).startswith("[插图失败]")
    assert "不存在" in docx_image_insert.invoke(
        {"dest": rel, "image": "knowledge/parse/无此文件/images/img_001.png"})
    # webp：python-docx 不识别，人话提示换格式
    from app.knowledge import store as kb_store

    webp_dir = kb_store.kb_images_dir("证书.webp")
    webp_dir.mkdir(parents=True, exist_ok=True)
    (webp_dir / "img_001.webp").write_bytes(b"fake-webp")
    out = docx_image_insert.invoke({"dest": rel, "image": "knowledge/parse/证书/images/img_001.webp"})
    assert out.startswith("[插图失败]") and "webp" in out
    # docx 原件不作图源
    _tender_source(env)
    out = docx_image_insert.invoke({"dest": rel, "image": "sources/招标文件.docx"})
    assert out.startswith("[插图失败]") and "docx" in out
    # 段落号超范围
    assert "超范围" in docx_image_insert.invoke(
        {"dest": rel, "image": _kb_image(), "after": "99"})
    # 目标节未创建
    assert "不存在" in docx_image_insert.invoke(
        {"dest": "body/没有建过.docx", "image": _kb_image()})


def test_image_insert_into_revised_section(env):
    """已有修订标记的节里插图：rev_id 续号、自校验（拒绝视角不变）依旧通过。"""
    rel = _make_section("技术部分/3.3 业绩.docx")
    r = docx_section_revise.invoke({"path": rel, "edits": json.dumps([
        {"para": 1, "action": "insert_after", "text": "公司近三年业绩一览。"},
    ])})
    assert r.startswith("[已修订]"), r
    r = docx_image_insert.invoke({"dest": rel, "image": _kb_image(), "after": "2"})
    assert r.startswith("[已插图]"), r
    # 修订过的节拒绝视角：文本段保留（w:ins 插段整段消失）、图片段消失，无空行
    assert _flatten_rejected(Document(str(_abs(env, rel)))) == "3.1 运维方案"


# ---------- 待办批注（docx_comment_add：缺料/待澄清的正规落点） ----------


def test_comment_add_anchor_view_and_errors(env):
    """批注锚定指定段/默认节末；读视图行尾可见、终稿投影干净；错误路径人话。"""
    rel = "body/技术部分/3.3 项目团队.docx"
    docx_section_create.invoke({
        "path": rel, "title": "3.3 项目团队",
        "paragraphs": "团队拟投入 5 人。\n项目经理持一级建造师证书。",
    })
    r = docx_comment_add.invoke({
        "path": rel, "after": "2", "text": "项目经理证书编号缺失，需向用户确认后回填",
    })
    assert r.startswith("[已加批注]") and "P2" in r and "共 1 条" in r, r
    r2 = docx_comment_add.invoke({"path": rel, "text": "驻场人数是否含后台待澄清"})
    assert r2.startswith("[已加批注]") and "P3" in r2 and "共 2 条" in r2, r2

    view = docx_section_read.invoke({"path": rel})
    assert "待办批注 2 条" in view
    assert "〔批注：项目经理证书编号缺失，需向用户确认后回填〕" in view
    # 终稿视角（接受修订后评委看到的文本）不含批注内容——批注不是正文
    doc = Document(str(_abs(env, rel)))
    assert not any("证书编号缺失" in t or "待澄清" in t for t in section_text_lines(doc))
    # 加批注后再修订：自校验（拒绝视角）不漂移、批注保留
    assert docx_section_revise.invoke({"path": rel, "edits": json.dumps([
        {"para": 2, "action": "insert_after", "text": "证书编号见附件。"},
    ])}).startswith("[已修订]")
    assert "待办批注 2 条" in docx_section_read.invoke({"path": rel})

    # 错误路径
    assert docx_comment_add.invoke({"path": rel, "text": ""}).startswith("[批注失败]")
    assert "段落号超范围" in docx_comment_add.invoke({"path": rel, "after": "99", "text": "x"})
    assert "after 须为段落号" in docx_comment_add.invoke({"path": rel, "after": "P", "text": "x"})
    assert "文件不存在" in docx_comment_add.invoke({"path": "body/无此节.docx", "text": "x"})
