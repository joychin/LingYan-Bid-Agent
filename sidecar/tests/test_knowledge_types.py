"""类型注册表（v3 章节块模型）：策略源完整性、角色驱动建块、payload、文件名提示。"""

from app.knowledge import types as kt


def test_registry_roles_and_chapter_policy():
    # 事实类 9 个（含 other 兜底）→ 不建章节块
    for code in (
        "business_license", "qualification_certificate", "personnel_certificate", "contract_case",
        "acceptance_report", "financial_report", "company_profile", "honor_ip", "other",
    ):
        t = kt.TYPES[code]
        assert t.role == "fact", code
        assert not kt.builds_chapters(code), code
    # 写法类 3 个 → 建章节块（无 decompose/extract_images 字段——策略由 role 驱动）
    for code in ("past_proposal", "reference_doc", "technical_doc"):
        assert kt.TYPES[code].role == "writing", code
        assert kt.builds_chapters(code), code
    assert not hasattr(kt.TYPES["past_proposal"], "decompose")
    assert not hasattr(kt.TYPES["past_proposal"], "extract_images")


def test_role_of_fallback_fact():
    assert kt.role_of("past_proposal") == "writing"
    assert kt.role_of(None) == "fact"   # 未判定归事实类兜底
    assert kt.role_of("nope") == "fact"
    assert not kt.builds_chapters(None)


def test_time_field_anchors():
    # 机器消费锚点：时间字段 + 身份字段（project_name/client）
    assert set(kt.TYPES["qualification_certificate"].time_fields) == {"valid_from", "valid_until"}
    for code in ("valid_until", "sign_date", "period", "doc_date", "project_name", "client"):
        assert code in kt.FIELD_LABELS


def test_guess_type_order():
    assert kt.guess_type_by_filename("智慧园区投标文件.docx") == "past_proposal"
    assert kt.guess_type_by_filename("技术方案模板.docx") == "reference_doc"  # reference 在 technical 前
    assert kt.guess_type_by_filename("某项目投标合同.pdf") == "contract_case"
    assert kt.guess_type_by_filename("随便什么.docx") is None


def test_types_payload_shape():
    payload = kt.types_payload()
    by = {p["code"]: p for p in payload}
    assert by["past_proposal"]["role"] == "writing"
    assert "decompose" not in by["past_proposal"]  # 策略字段已删（role 驱动）
    assert "extract_images" not in by["financial_report"]
    assert by["qualification_certificate"]["time_fields"] == ["valid_from", "valid_until"]
