"""锚点回文核对（程序机械层，2026-09-08 两主人模型）：纯函数规则 + 启动回扫。
管线接线（自动确认/降级/人工免疫）见 test_knowledge_ingest.py。"""

import json

from app import db
from app.knowledge import store
from app.knowledge.autocheck import autocheck_sweep, run_anchor_check
from app.knowledge.types import get_type
from tests.util import init_env

MD = (
    "# 证书\n\nXX 建设银行数据中心项目 ISO9001 质量管理体系认证，证书编号 CN-001。\n"
    "有效期自 2023 年 5 月 1 日起，至 2028-06-30 止。落款日期：2023.5.1。\n"
)


def _check(fields, md=MD, doc_type="qualification_certificate"):
    return run_anchor_check(
        {"doc_type": doc_type, "fields": fields}, md, get_type(doc_type),
    )


def _fail_fields(result):
    return {x["field"]: x for x in result["results"] if not x["ok"]}


# ---------- 纯函数：时间锚点 ----------

def test_date_format_variants_hit():
    """同一日期的四种印法（含全角）都算原文命中。"""
    for val in ("2023-05-01", "2023年5月1日", "2023.5.1", "２０２３／５／１"):
        assert _check({"valid_from": {"value": val}})["status"] == "pass", val


def test_fabricated_date_fail():
    r = _check({"valid_until": {"value": "2099-01-01"}})
    assert r["status"] == "fail"
    item = _fail_fields(r)["valid_until"]
    assert "未在原文找到该日期" in item["detail"]


def test_unparseable_date_fail():
    r = _check({"valid_until": {"value": "长期有效"}})
    assert "日期格式无法解析" in _fail_fields(r)["valid_until"]["detail"]


def test_valid_until_before_valid_from():
    r = _check({"valid_from": {"value": "2030-01-01"}, "valid_until": {"value": "2028-06-30"}})
    assert "有效期至早于有效期自" in _fail_fields(r)["_consistency"]["detail"]


def test_period_year():
    good = run_anchor_check(
        {"doc_type": "financial_report", "fields": {"period": {"value": "2023 年度"}}},
        MD, get_type("financial_report"),
    )
    assert good["status"] == "pass"
    bad = run_anchor_check(
        {"doc_type": "financial_report", "fields": {"period": {"value": "1999 年度"}}},
        MD, get_type("financial_report"),
    )
    assert bad["status"] == "fail"


# ---------- 纯函数：身份锚点 ----------

def test_name_hit_with_fullwidth_and_spaces():
    """值侧全角/空白归一后命中（值「建 设 银 行」↔ 原文「建设银行」）。"""
    r = _check({"client": {"value": "建 设 银 行"}}, doc_type="company_profile")
    assert r["status"] == "pass"


def test_fabricated_name_fail():
    r = _check({"project_name": {"value": "从未出现的项目名"}})
    item = _fail_fields(r)["project_name"]
    assert "疑似抽取编造" in item["detail"]


# ---------- 纯函数：零锚点规则 ----------

def test_fact_type_zero_time_anchors_fail():
    """事实类应有时间锚点却一个没抽到 → 可疑（时效计算将不可用）。"""
    r = _check({}, doc_type="qualification_certificate")
    item = _fail_fields(r)["_anchors"]
    assert "未识别到时间锚点" in item["detail"]


def test_no_time_fields_types_pass_on_zero_anchors():
    """公司介绍/其他/写法类零锚点=平凡通过。"""
    for code in ("company_profile", "other", "past_proposal"):
        r = run_anchor_check({"doc_type": code, "fields": {}}, MD, get_type(code))
        assert r["status"] == "pass", code


# ---------- 启动回扫 ----------

def _mk_item(name, md, suggested, review="pending_review", business=None, extract="done"):
    md_path, _, _, _ = store.kb_parse_paths(name)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    item = db.kb_insert_item(file_name=name, file_hash="h-" + name, title=name, ext=".md")
    db.kb_update_item(
        item["id"], parse_status="ready", extract_status=extract, review_status=review,
        suggested_metadata=json.dumps(suggested, ensure_ascii=False),
        business_metadata=json.dumps(business, ensure_ascii=False) if business else None,
    )
    return item["id"]


def test_sweep_autoconfirms_flags_and_is_idempotent(tmp_path, monkeypatch):
    """回扫：全过自动确认（business 带 auto 标记）、有败点名原因、人工/失败不碰、幂等。"""
    init_env(tmp_path, monkeypatch)
    store.ensure_dirs()
    ok = _mk_item("好证书.md", MD, {
        "doc_type": "qualification_certificate",
        "fields": {"valid_until": {"value": "2028-06-30"}, "client": {"value": "建设银行"}},
    })
    bad = _mk_item("坏证书.md", MD, {
        "doc_type": "qualification_certificate",
        "fields": {"valid_until": {"value": "2099-01-01"}},
    })
    human = _mk_item("人工.md", MD, {"doc_type": "company_profile", "fields": {}},
                     review="confirmed", business={"doc_type": "company_profile", "fields": {}})
    failed = _mk_item("失败.md", MD, {"doc_type": "company_profile", "fields": {}}, extract="failed")

    assert autocheck_sweep() == (2, 1, 1)

    a = db.kb_get_item(ok)
    assert a["review_status"] == "confirmed"
    biz = json.loads(a["business_metadata"])
    assert biz["confirmed_by"] == "auto"
    assert json.loads(a["check_result"])["status"] == "pass"

    b = db.kb_get_item(bad)
    assert b["review_status"] == "pending_review" and not b["business_metadata"]
    assert any(not x["ok"] for x in json.loads(b["check_result"])["results"])

    assert db.kb_get_item(human)["check_result"] is None  # 人工确认不碰
    assert db.kb_get_item(failed)["review_status"] == "pending_review"  # 抽取失败不在范围

    assert autocheck_sweep() == (0, 0, 0)  # 幂等：第二遍范围自然为空
