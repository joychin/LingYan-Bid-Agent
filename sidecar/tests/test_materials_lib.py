"""写作素材库域（v2 手工构建）：上传解析、目录树、建块（多区间/嵌套去重）、
备注进检索、CRUD、删文件清段、事实检索不受素材段污染。"""


from app import db
from app.knowledge import fts
from app.knowledge import materials_lib as mlib
from app.knowledge.materials_lib import run_parse
from tests.util import init_env


def _setup(tmp_path, monkeypatch):
    init_env(tmp_path, monkeypatch)
    mlib.ensure_dirs()


def _body(chapters=3, sections_per=2, lines_per=6) -> str:
    """两级结构正文（供解析出目录树）。"""
    lines = []
    for c in range(1, chapters + 1):
        lines.append(f"# 第{c}章 服务方案")
        lines.append("")
        for s in range(1, sections_per + 1):
            lines.append(f"## {c}.{s} 能力模块{c}{s}")
            lines.append("")
            lines += [f"第{c}.{s}节运维能力说明文本第{i}条补充。" for i in range(lines_per)]
            lines.append("")
    return "\n".join(lines)


def _upload(name: str, content: str) -> str:
    import hashlib

    src = mlib.mt_files_dir() / name
    src.write_text(content, encoding="utf-8")
    f = db.mt_insert_file(file_name=name, file_hash=hashlib.sha256(content.encode()).hexdigest())
    run_parse(f["id"])
    return f["id"]


def test_parse_produces_outline(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fid = _upload("参考标书.md", _body())
    f = db.mt_get_file(fid)
    assert f["parse_status"] == "ready"
    outline = mlib.read_outline(fid)
    tops = [n["标题"] for n in outline]
    assert tops == [f"第{c}章 服务方案" for c in range(1, 4)]
    assert outline[0]["children"] and outline[0]["children"][0]["标题"].startswith("1.1")


def test_parse_unstructured_file_flags_error(tmp_path, monkeypatch):
    """无标题文件：ready 但带警示——无法挑章节的诚实提示。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("散文.txt", "没有标题的散文内容。" * 20)
    f = db.mt_get_file(fid)
    assert f["parse_status"] == "ready"
    assert f["error"] and "目录" in f["error"]
    assert mlib.read_outline(fid) == []


def test_create_block_multi_ranges_and_nesting(tmp_path, monkeypatch):
    """建块：多区间（勾选不连续章节）；嵌套勾选（父子）被包含区间去重。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("参考标书.md", _body())
    outline = mlib.read_outline(fid)
    ch1, ch2 = outline[0], outline[1]           # 第1章 / 第2章
    sec11 = ch1["children"][0]                   # 1.1（ch1 区间内）
    # 勾了第1章整章 + 1.1 子节（嵌套）+ 第2章整章（不连续 → 多区间）
    ranges = [
        [ch1["start_line"], ch1["end_line"]],
        [sec11["start_line"], sec11["end_line"]],
        [ch2["start_line"], ch2["end_line"]],
    ]
    block = mlib.create_block(fid, "核心能力章", "政务云写法，最成熟", ranges)
    assert block is not None
    # 1.1 被 ch1 区间包含 → 去重后只剩两段
    assert block["ranges"] == [
        [ch1["start_line"], ch1["end_line"]],
        [ch2["start_line"], ch2["end_line"]],
    ]
    assert block["chars"] > 0
    assert db.mt_list_blocks(fid)[0]["title"] == "核心能力章"


def test_invalid_ranges_rejected(tmp_path, monkeypatch):
    """全无效区间（越界/空）拒绝建块。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("参考标书.md", _body())
    assert mlib.create_block(fid, "x", "", [[500, 900]]) is None
    assert mlib.create_block(fid, "x", "", []) is None
    assert db.mt_list_blocks(fid) == []


def test_block_note_searchable(tmp_path, monkeypatch):
    """备注进检索段：搜备注词命中素材块（用户语义索引的落地）。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("参考标书.md", _body())
    outline = mlib.read_outline(fid)
    ch1 = outline[0]
    mlib.create_block(fid, "表单管理方案", "政务云表单章，写法成熟",
                      [[ch1["start_line"], ch1["end_line"]]])
    # 搜备注独有词「政务云」（正文没有这个词）
    hits = db.kb_search_segments(fts.build_match_expr("政务云"), limit=5)
    assert any(h["item_id"] == fid and h.get("material_id") for h in hits)
    # 搜正文词也命中
    hits2 = db.kb_search_segments(fts.build_match_expr("运维能力"), limit=5)
    assert any(h["item_id"] == fid for h in hits2)


def test_update_delete_block_and_file(tmp_path, monkeypatch):
    """改备注/删块/删文件（索引与检索段联动清理）。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("参考标书.md", _body())
    outline = mlib.read_outline(fid)
    ch1 = outline[0]
    b = mlib.create_block(fid, "章一", "", [[ch1["start_line"], ch1["end_line"]]])
    # 改备注 → 检索段更新
    mlib.update_block(b["id"], note="更新后的备注词XYZ")
    assert db.mt_get_block(b["id"])["note"] == "更新后的备注词XYZ"
    assert db.kb_search_segments(fts.build_match_expr("XYZ"), limit=3)
    # 删块 → 段清
    assert mlib.delete_block(b["id"])
    assert db.mt_list_blocks(fid) == []
    assert not any(h["item_id"] == fid for h in db.kb_search_segments(fts.build_match_expr("运维能力"), limit=5))
    # 再建一块 → 删文件连带块与段与磁盘
    mlib.create_block(fid, "章二", "", [[ch1["start_line"], ch1["end_line"]]])
    assert mlib.delete_file(fid)
    assert db.mt_get_file(fid) is None
    assert db.mt_list_blocks(fid) == []
    assert not (mlib.mt_files_dir() / "参考标书.md").exists()
    assert not mlib.mt_parse_dir("参考标书.md").exists()


def test_material_segments_not_in_fact_search(tmp_path, monkeypatch):
    """素材段（mt_ 前缀）不进事实检索：search_company_assets 按 kb_items 映射过滤。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("参考标书.md", _body())
    outline = mlib.read_outline(fid)
    ch1 = outline[0]
    mlib.create_block(fid, "资质章", "含 ISO9001 认证",
                      [[ch1["start_line"], ch1["end_line"]]])
    from app.tools.search_knowledge import search_company_assets, search_references

    out = search_company_assets.invoke({"query": "ISO9001"})
    assert "参考标书" not in out  # 素材段不出现
    # 写法检索命中素材块（含备注）
    out2 = search_references.invoke({"query": "ISO9001 认证"})
    assert "《资质章》" in out2 and "ISO9001 认证" in out2
    assert "素材块全景" in out2 and "备注：含 ISO9001 认证" in out2


def test_search_references_empty_hint(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from app.tools.search_knowledge import search_references

    out = search_references.invoke({"query": "不存在的词xyzzy"})
    assert "写作素材无命中" in out and "素材库还是空的" in out


# ---------- 完善批（2026-09-07）：节点字数 / 块内容 / 引用打点 / 检索 ----------

def test_outline_nodes_carry_chars(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fid = _upload("字数.md", _body())
    outline = mlib.read_outline(fid)
    top = outline[0]
    assert top["chars"] > 0
    # 子节区间是父区间的子集 → 父字数 ≥ 首子节字数
    assert top["chars"] >= top["children"][0]["chars"] > 0


def test_block_content_sections(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fid = _upload("内容.md", _body())
    b = mlib.create_block(fid, "两段块", "", ranges=[[1, 8], [20, 30]])
    content = mlib.block_content(b["id"])
    assert content["id"] == b["id"] and len(content["sections"]) == 2
    assert content["sections"][0]["start"] == 1 and content["sections"][0]["end"] == 8
    assert "能力模块" in content["sections"][0]["text"]
    assert content["chars"] > 0
    assert mlib.block_content("blk_nope") is None


def test_search_block_ids_matches_body(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fid = _upload("检索.md", _body())
    b1 = mlib.create_block(fid, "检索块", "备注", ranges=[[1, 8]])
    assert mlib.search_block_ids("运维能力说明") == {b1["id"]}
    assert mlib.search_block_ids("绝不存在的词组xyzzy") == set()


def test_touch_and_replace_preserve_usage(tmp_path, monkeypatch):
    """引用打点入列；_sync_blocks 全量重建（建/改块都触发）不打丢。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("保列.md", _body())
    b1 = mlib.create_block(fid, "块一", "备注一", ranges=[[1, 8]])
    db.mt_touch_blocks([b1["id"]])
    t1 = db.mt_get_block(b1["id"])
    assert t1["use_count"] == 1 and t1["last_used_at"]
    mlib.create_block(fid, "块二", "", ranges=[[20, 25]])
    mlib.update_block(b1["id"], note="改后备注")
    t2 = db.mt_get_block(b1["id"])
    assert t2["use_count"] == 1 and t2["last_used_at"] == t1["last_used_at"]
    assert t2["created_at"] == t1["created_at"]
    db.mt_touch_blocks([b1["id"]])
    assert db.mt_get_block(b1["id"])["use_count"] == 2


def test_recover_stale_mt_marks_interrupted(tmp_path, monkeypatch):
    """启动对账：残留 pending/parsing → failed（失败行有重试入口）；终态不动、
    已有 error 保留（COALESCE）。"""
    _setup(tmp_path, monkeypatch)
    a = db.mt_insert_file(file_name="中断.md", file_hash="h1")
    db.mt_update_file(a["id"], parse_status="parsing")
    b = db.mt_insert_file(file_name="排队.md", file_hash="h2")  # 默认 pending
    c = db.mt_insert_file(file_name="完成.md", file_hash="h3")
    db.mt_update_file(c["id"], parse_status="ready")
    d = db.mt_insert_file(file_name="带原因.md", file_hash="h4")
    db.mt_update_file(d["id"], parse_status="parsing", error="解析失败：xxx")
    assert db.recover_stale_mt() == 3
    assert db.mt_get_file(a["id"])["parse_status"] == "failed"
    assert db.mt_get_file(a["id"])["error"] == "解析中断，请重试"
    assert db.mt_get_file(b["id"])["parse_status"] == "failed"
    assert db.mt_get_file(c["id"])["parse_status"] == "ready"
    assert db.mt_get_file(d["id"])["error"] == "解析失败：xxx"


# ---------- 图片可见性批（2026-09-08）：占位行计数 / 重解析同步 / 漂移提示 ----------

def test_block_image_count_and_search_visibility(tmp_path, monkeypatch):
    """块级图片段计数（占位行口径）；检索命中行与块清单骨架都透出「含图 N 处」。"""
    _setup(tmp_path, monkeypatch)
    lines = [
        "# 第一章 平台介绍", "",
        "架构总览：", "![](图片)", "实施流程：", "![](图片)",
        "纯文字说明。", "",
    ]
    fid = _upload("带图方案.md", "\n".join(lines))
    assert mlib.block_image_count("带图方案.md", [[1, 7]]) == 2
    assert mlib.block_image_count("带图方案.md", [[7, 8]]) == 0
    assert mlib.block_image_count("不存在的文件.md", [[1, 7]]) == 0
    mlib.create_block(fid, "平台架构块", "低代码平台架构参考", [[1, 7]])
    from app.tools.search_knowledge import search_references

    out = search_references.invoke({"query": "低代码平台架构"})
    assert "含图 2 处" in out  # 命中行
    assert out.count("含图 2 处") >= 2  # 块清单骨架同样标注
    assert "必须走 docx_material_inject" in out  # 精读指引硬话


def test_reparse_resyncs_blocks_without_drift(tmp_path, monkeypatch):
    """重解析（行数不变）：块索引字数与检索段跟随新 md 重建，无漂移警告。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("重解析.md", _body())
    ch1 = mlib.read_outline(fid)[0]
    b = mlib.create_block(fid, "章一块", "", [[ch1["start_line"], ch1["end_line"]]])
    old_chars = db.mt_get_block(b["id"])["chars"]
    src = mlib.mt_files_dir() / "重解析.md"
    new_body = _body().replace("运维能力说明文本", "全新内容关键词说明文本")
    src.write_text(new_body, encoding="utf-8")
    run_parse(fid)
    f = db.mt_get_file(fid)
    assert f["parse_status"] == "ready" and f["error"] is None
    assert db.mt_get_block(b["id"])["chars"] > old_chars  # 索引字数已跟随新 md
    assert db.kb_search_segments(fts.build_match_expr("全新内容关键词"), limit=5)


def test_reparse_line_drift_warns_only_with_blocks(tmp_path, monkeypatch):
    """重解析行数变化：有块的文件给 ready+error 漂移提示（块保留待复核）；
    无块文件不打扰。"""
    _setup(tmp_path, monkeypatch)
    fid = _upload("漂移.md", _body())
    ch1 = mlib.read_outline(fid)[0]
    b = mlib.create_block(fid, "章一块", "", [[ch1["start_line"], ch1["end_line"]]])
    (mlib.mt_files_dir() / "漂移.md").write_text(_body(lines_per=10), encoding="utf-8")
    run_parse(fid)
    f = db.mt_get_file(fid)
    assert f["parse_status"] == "ready"
    assert f["error"] and "行号有变化" in f["error"]
    assert db.mt_get_block(b["id"]) is not None  # 块不删，提示用户复核区间
    fid2 = _upload("无块.md", _body())
    (mlib.mt_files_dir() / "无块.md").write_text(_body(lines_per=10), encoding="utf-8")
    run_parse(fid2)
    assert db.mt_get_file(fid2)["error"] is None
