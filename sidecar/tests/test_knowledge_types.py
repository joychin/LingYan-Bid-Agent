"""知识库类型注册表：封闭注册完整性、文件名提示、抽取 prompt 组装。"""

from app.knowledge import types as kt


def test_types_registry_complete():
    # 每个类型：code 唯一、有中文名、字段模板的 code 都有中文标签
    assert len(kt.TYPES) >= 10
    assert kt.TYPES["business_license"].name == "营业执照"
    for code, t in kt.TYPES.items():
        assert t.code == code
        assert t.name
        for f in t.fields:
            assert f in kt.FIELD_LABELS, f"{code}.{f} 缺中文标签"
    assert "other" in kt.TYPES


def test_type_name_fallback():
    assert kt.type_name("business_license") == "营业执照"
    assert kt.type_name("nope") == "nope"
    # 未登记类型与空类型统一兜底「其他」（与左栏分组名一致）
    assert kt.type_name(None) == "其他"


def test_guess_type_by_filename():
    assert kt.guess_type_by_filename("营业执照.jpg") == "business_license"
    assert kt.guess_type_by_filename("ISO27001证书.pdf") == "qualification_certificate"
    assert kt.guess_type_by_filename("2023年度审计报告.pdf") == "financial_report"
    assert kt.guess_type_by_filename("随便什么文件.docx") is None


def test_types_payload_shape():
    payload = kt.types_payload()
    assert all({"code", "name", "fields"} <= set(p) for p in payload)


def test_build_extract_prompt():
    prompt = kt.build_extract_prompt("营业执照.jpg", "统一社会信用代码：91110000XXX")
    # 类型枚举内联 + 文件名提示 + 截断保护
    assert "business_license" in prompt
    assert "禁止编造" in prompt
    assert "营业执照" in prompt  # 文件名提示
    # 字段模板给 code（标签）对 + 键必须用 code 的硬约束（防 LLM 输出中文键）
    assert "company_name（单位名称）" in prompt
    assert "禁止用中文标签做键" in prompt
    long = kt.build_extract_prompt("a.md", "字" * 30000)
    assert "中段省略" in long
    assert len(long) < 22000


def test_normalize_field_keys():
    # 中文标签键 → code
    assert kt.normalize_field_keys({"单位名称": 1, "有效期至": 2}) == {"company_name": 1, "valid_until": 2}
    # 已是 code 的保留
    assert kt.normalize_field_keys({"uscc": 1}) == {"uscc": 1}
    # 模板外自由键原样保留
    assert kt.normalize_field_keys({"成立时间": 1, "whatever": 2}) == {"成立时间": 1, "whatever": 2}
    assert kt.normalize_field_keys({}) == {}
