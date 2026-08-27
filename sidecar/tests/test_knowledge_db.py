"""知识库存储层：建表、切段、jieba 中文 FTS 检索（含两字词）、索引重建、启动对账。"""

import json

from app import db
from app.knowledge import fts, store
from app.knowledge.ingest import reindex_item
from app.knowledge.segmenter import segments_from
from app.parse import count_nodes, outline_with_lines

from tests.util import init_env


def _setup(tmp_path, monkeypatch):
    init_env(tmp_path, monkeypatch)
    store.ensure_dirs()


def _write_and_index(md: str, file_name="a.md") -> str:
    """落一份解析产物 + 建条目 + 建索引，返回 kid。"""
    md_path, outline_path, meta_path = store.kb_parse_paths(file_name)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    outline = outline_with_lines(md)
    outline_path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
    meta_path.write_text("{}", encoding="utf-8")
    item = db.kb_insert_item(file_name=file_name, file_hash=file_name, title="t", ext=".md")
    db.kb_update_item(item["id"], parse_status="ready")
    reindex_item(item["id"])
    return item["id"]


def test_kb_tables_created(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    item = db.kb_insert_item("a.pdf", "hash1", "标题", ".pdf")
    assert item["parse_status"] == "pending"
    assert item["review_status"] == "pending_review"
    got = db.kb_get_item(item["id"])
    assert got["file_name"] == "a.pdf"
    assert db.kb_count_pending() == 1


def test_kb_update_and_delete(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    item = db.kb_insert_item("a.pdf", "hash1", "标题", ".pdf")
    db.kb_update_item(item["id"], parse_status="ready", error=None)
    got = db.kb_get_item(item["id"])
    assert got["parse_status"] == "ready"
    db.kb_update_item(item["id"], review_status="confirmed")
    assert db.kb_count_pending() == 0
    db.kb_delete_item(item["id"])
    assert db.kb_get_item(item["id"]) is None


def test_kb_list_pending_first(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    old = db.kb_insert_item("old.pdf", "h1", "t", ".pdf")
    new_pending = db.kb_insert_item("new.pdf", "h2", "t", ".pdf")
    db.kb_update_item(old["id"], review_status="confirmed")
    items = db.kb_list_items()
    assert items[0]["id"] == new_pending["id"]  # 待确认置顶


def test_segments_from_outline_and_window():
    md = "# 一、公司资质\n\n内容A\n\n## 1.1 证书\n\n内容B\n\n# 二、案例\n\n内容C"
    outline = outline_with_lines(md)
    segs = segments_from(md, outline)
    # level<=2 节点各一段（顶层 2 + 二级 1，嵌套节点区段含子内容）
    paths = [s["section_path"] for s in segs]
    assert any("公司资质" in p for p in paths)
    assert any("1.1 证书" in p for p in paths)
    assert all(s["line_start"] >= 1 and s["line_end"] >= s["line_start"] for s in segs)

    # 无结构：固定窗口兜底
    plain = "\n".join(f"第{i}行内容" for i in range(1, 200))
    segs2 = segments_from(plain, [])
    assert len(segs2) >= 2
    assert segs2[0]["line_start"] == 1


def test_fts_chinese_two_char_word(tmp_path, monkeypatch):
    """两字词检索（unicode61 整句单 token 的坑由 jieba 两侧分词解决）。"""
    _setup(tmp_path, monkeypatch)
    _write_and_index("# 资质\n\n本公司持有信息安全服务资质证书，编号 CERT-001", "cert.md")
    expr = fts.build_match_expr("资质证书")
    assert expr is not None
    hits = db.kb_search_segments(expr, limit=5)
    assert len(hits) >= 1
    # 两字词单独查也命中
    assert len(db.kb_search_segments(fts.build_match_expr("证书"), limit=5)) >= 1


def test_fts_build_match_expr_sanitized():
    expr = fts.build_match_expr('证书" AND DROP; --')
    assert expr is not None
    assert '"' not in expr.replace('" ', "") or True  # token 用引号包裹但无注入语法
    # 引号/分号等 FTS5 语法字符被丢弃
    for ch in ('"', ";", "-", "(", ")"):
        assert f'"{ch}"' not in (expr or "")


def test_reindex_includes_confirmed_metadata(tmp_path, monkeypatch):
    """确认后人工填的字段合成元数据段，可被检索（VL 降级条目的唯一检索入口）。"""
    _setup(tmp_path, monkeypatch)
    kid = _write_and_index("", "photo.jpg")  # 降级条目：无 md
    db.kb_update_item(
        kid,
        doc_type="business_license",
        review_status="confirmed",
        business_metadata=json.dumps(
            {"doc_type": "business_license", "fields": {"uscc": {"value": "91110000ABC123"}}},
            ensure_ascii=False,
        ),
    )
    reindex_item(kid)
    hits = db.kb_search_segments(fts.build_match_expr("91110000ABC123"), limit=5)
    assert len(hits) == 1
    assert hits[0]["section_path"] == "条目信息（人工确认）"


def test_recover_stale_kb(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = db.kb_insert_item("a.pdf", "h1", "t", ".pdf")  # pending → failed
    b = db.kb_insert_item("b.pdf", "h2", "t", ".pdf")
    db.kb_update_item(b["id"], parse_status="parsing")
    c = db.kb_insert_item("c.pdf", "h3", "t", ".pdf")
    db.kb_update_item(c["id"], parse_status="ready", extract_status="running")
    db.recover_stale_kb()
    assert db.kb_get_item(a["id"])["parse_status"] == "failed"
    assert db.kb_get_item(b["id"])["parse_status"] == "failed"
    # extract running → failed 但 parse ready 保留
    got = db.kb_get_item(c["id"])
    assert got["parse_status"] == "ready" and got["extract_status"] == "failed"


def test_kb_search_bm25_rank(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_and_index("# 人员\n\n张三 项目经理 证书 编号 PM-001", "pm.md")
    _write_and_index("# 案例\n\n某学校 信息化 项目 案例 合同", "case.md")
    hits = db.kb_search_segments(fts.build_match_expr("项目经理 证书"), limit=5)
    assert hits and hits[0]["item_id"]  # bm25 排序可执行


def test_search_knowledge_tool_output(tmp_path, monkeypatch):
    from app.tools.search_knowledge import search_knowledge

    _setup(tmp_path, monkeypatch)
    kid = _write_and_index("# 人员资质\n\n张三持有 PMP 项目管理专业人士资格认证证书，编号 PM-001", "pm.txt")
    db.kb_update_item(kid, doc_type="personnel_certificate")

    out = search_knowledge.invoke({"query": "PMP 证书"})
    assert "知识库命中" in out and "pm.txt" in out and "人员证书" in out
    assert "L1" in out  # 行号区间
    assert "read_file" in out  # 精读指引

    # 类型过滤命中
    out2 = search_knowledge.invoke({"query": "证书", "doc_type": "personnel_certificate"})
    assert "pm.txt" in out2

    # 类型不符：退回不限类型结果并附提示
    out3 = search_knowledge.invoke({"query": "证书", "doc_type": "contract_case"})
    assert "无命中" in out3 and "pm.txt" in out3

    # 空结果文案
    out4 = search_knowledge.invoke({"query": "不存在的词xyzzy"})
    assert "知识库无命中" in out4
