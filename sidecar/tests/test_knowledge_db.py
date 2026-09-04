"""知识库存储层（v3 事实层）：建表形状、说明段、索引重建、FTS；素材表见 test_materials_lib。"""

import json

from app import db
from app.knowledge import fts, store
from app.knowledge.ingest import reindex_item
from app.parse import outline_with_lines
from tests.util import init_env


def _setup(tmp_path, monkeypatch):
    init_env(tmp_path, monkeypatch)
    store.ensure_dirs()


def _write_md(name: str, md: str, doc_type: str | None = None, suggested: dict | None = None) -> str:
    import hashlib

    md_path, outline_path, meta_path, _ = store.kb_parse_paths(name)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    outline_path.write_text(json.dumps(outline_with_lines(md), ensure_ascii=False), encoding="utf-8")
    meta_path.write_text("{}", encoding="utf-8")
    item = db.kb_insert_item(file_name=name, file_hash=hashlib.sha256(md.encode()).hexdigest(),
                             title=name, ext=".md")
    db.kb_update_item(item["id"], parse_status="ready")
    if doc_type:
        db.kb_update_item(item["id"], doc_type=doc_type)
    if suggested:
        db.kb_update_item(item["id"], suggested_metadata=json.dumps(suggested, ensure_ascii=False))
    reindex_item(item["id"])
    return item["id"]


def test_kb_items_shape(tmp_path, monkeypatch):
    """v3 形状：无 bucket、有 progress 列。"""
    _setup(tmp_path, monkeypatch)
    item = db.kb_insert_item("a.pdf", "h1", "t", ".pdf")
    assert item["parse_status"] == "pending"
    assert "progress" in item and item["progress"] is None
    assert "bucket" not in item
    db.kb_update_item(item["id"], progress="章节裁定中", parse_status="ready")
    got = db.kb_get_item(item["id"])
    assert got["progress"] == "章节裁定中"
    db.kb_update_item(item["id"], progress=None)  # 可清空
    assert db.kb_get_item(item["id"])["progress"] is None
    assert db.kb_count_pending() == 1


def test_materials_table_removed(tmp_path, monkeypatch):
    """素材分离迁移：kb_materials 表已删（知识库块退役）。"""
    _setup(tmp_path, monkeypatch)
    conn = db._conn()
    try:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "kb_materials" not in tables
    assert {"mt_files", "mt_blocks"} <= tables


def test_statement_segment_searchable(tmp_path, monkeypatch):
    """内容说明进检索（§statement 段）——财报类正文的语义密度承担者。"""
    _setup(tmp_path, monkeypatch)
    kid = _write_md(
        "审计报告.md", "# 审计\n\n数字表格正文。",
        doc_type="financial_report",
        suggested={"doc_type": "financial_report",
                   "statement": "XYZ 公司 2024 年度审计报告：营业收入 12.7 亿元（第5页）；净资产 8.2 亿元（第7页）"},
    )
    reindex_item(kid)
    hits = db.kb_search_segments(fts.build_match_expr("净资产"), limit=5)
    assert hits and hits[0]["section_path"] == "§statement"


def test_reindex_no_material_segments(tmp_path, monkeypatch):
    """素材分离：知识库 reindex 只产 outline/说明/字段段，无任何块段/块表。"""
    _setup(tmp_path, monkeypatch)
    md = "# 一、方案\n\n" + "智慧园区总体架构正文内容。" * 20
    kid = _write_md("范文.md", md, doc_type="past_proposal")
    from app.knowledge.ingest import reindex_item

    reindex_item(kid)
    # 段只有 outline 段（无 material_id）
    hits = db.kb_search_segments(fts.build_match_expr("架构"), limit=10)
    assert hits and all(h.get("material_id") is None for h in hits)
    # 改类型重切：段重建、仍无块段（幂等）
    db.kb_update_item(kid, doc_type="financial_report")
    reindex_item(kid)
    hits2 = db.kb_search_segments(fts.build_match_expr("架构"), limit=10)
    assert all(h.get("material_id") is None for h in hits2)


def test_confirmed_fields_searchable(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    kid = _write_md("photo.md", "", doc_type="qualification_certificate")
    db.kb_update_item(
        kid, review_status="confirmed",
        business_metadata=json.dumps(
            {"doc_type": "qualification_certificate", "fields": {"valid_until": {"value": "2027-08-15"}}},
            ensure_ascii=False,
        ),
    )
    reindex_item(kid)
    hits = db.kb_search_segments(fts.build_match_expr("2027-08-15"), limit=3)
    assert hits and hits[0]["section_path"] == "条目信息（人工确认）"


def test_fts_chinese_two_char_word(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_md("cert.md", "# 资质\n\n本公司持有信息安全服务资质证书，编号 CERT-001",
              doc_type="qualification_certificate")
    assert db.kb_search_segments(fts.build_match_expr("资质证书"), limit=5)
    assert db.kb_search_segments(fts.build_match_expr("证书"), limit=5)


def test_recover_stale_clears_progress(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = db.kb_insert_item("a.pdf", "h1", "t", ".pdf")
    db.kb_update_item(a["id"], parse_status="parsing", progress="图片识别中 3/60 页")
    db.recover_stale_kb()
    got = db.kb_get_item(a["id"])
    assert got["parse_status"] == "failed" and got["progress"] is None
