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
