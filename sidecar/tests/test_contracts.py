"""契约目录：注册表查找 + tender.directory 模型校验。"""

from app.contracts import get_contract, list_contracts


def test_registry_has_directory_contract():
    c = get_contract("tender.directory/tender-response-docs@1")
    assert c is not None
    assert c.kind == "tender.directory"
    assert c.cardinality == "task-single"
    assert c.llm_write_mode == "suggest"
    assert c.editable is True
    assert c.default_display_name == "投标目录"
    assert get_contract("tender.directory/tender-response-docs@2") is None
    assert get_contract("no.such/contract@1") is None
    assert any(c.key == "tender.directory/tender-response-docs@1" for c in list_contracts())


def test_directory_model_accepts_real_shape():
    model = get_contract("tender.directory/tender-response-docs@1").model
    data = {
        "response_documents": [
            {
                "name": "技术部分",
                "scope": "覆盖技术评审全部维度",
                "directory": [
                    {
                        "目录名称": "技术方案",
                        "level": 1,
                        "children": [
                            {
                                "目录名称": "需求理解",
                                "level": 2,
                                "children": [],
                                "来源位置": ["REQ-11"],
                                "交付形态": "正文编写",
                            }
                        ],
                        "来源": ["招标文件规定"],
                        "来源位置": ["MAND-03", "REQ-11"],
                        "交付形态": "混合",
                        "归位理由": "评分项要求",
                        "理由来源": ["MAND-03"],
                        "节点概述": "总体技术方案",
                    }
                ],
            }
        ],
        "registry": {"MAND-03": {"type": "必须章节", "text": "…", "出处": "第五章"}},
        "meta": {"项目名称": "测试项目"},
        "lineage_check": {"unused_ids": [], "dangling_ids": []},
    }
    m = model.model_validate(data)
    assert m.response_documents[0].directory[0].children[0].目录名称 == "需求理解"

    # 标注字段全部可缺省（宽容解析）
    minimal = {"response_documents": [{"name": "整册"}]}
    assert model.model_validate(minimal).response_documents[0].scope == ""


def test_directory_model_rejects_structural_garbage():
    import pytest
    from pydantic import ValidationError

    model = get_contract("tender.directory/tender-response-docs@1").model
    with pytest.raises(ValidationError):
        model.model_validate({})  # 缺 response_documents
    with pytest.raises(ValidationError):
        model.model_validate({"response_documents": "不是列表"})
    with pytest.raises(ValidationError):
        model.model_validate({"response_documents": [{"name": "x", "directory": "不是列表"}]})
    with pytest.raises(ValidationError):
        model.model_validate({"response_documents": [{"name": "x", "directory": [{"level": 1}]}]})  # 缺目录名称
