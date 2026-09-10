"""首个契约：tender.directory / tender-response-docs@1（投标目录）。

模型按 tender-toc skill 产出的 tender-response-docs.json 真实结构宽松建模
（SKILL.md §lineage schema）：字段可缺省，保证历史/未来轻微变化不被误拒；
结构性错误（缺 response_documents、directory 非列表等）会拒绝发布。
"""

from typing import Literal

from pydantic import BaseModel, Field

from . import ContractDef

# 章节编号格式（合册 docx_assemble_volume 按树序生成标题编号时读取）：
# chapter=第X章+1.1（缺省） decimal=1+1.1 gov=一、（一）1. none=不加编号。
# 编号是树位置的纯函数、只在合册发标题那一刻生成——对账/派发/检索全用裸节点名。
NumberingScheme = Literal["chapter", "decimal", "gov", "none"]


class TocNode(BaseModel):
    """目录节点：树形递归，标注字段全部可缺省（宽容解析，Processor 防御性渲染）。"""

    model_config = {"extra": "allow"}

    目录名称: str
    level: int = 1
    children: list["TocNode"] = Field(default_factory=list)
    来源: list[str] = Field(default_factory=list)
    来源位置: list[str] = Field(default_factory=list)
    交付形态: str = ""
    归位理由: str = ""
    理由来源: list[str] = Field(default_factory=list)
    节点概述: str = ""


class ResponseDocument(BaseModel):
    model_config = {"extra": "allow"}

    name: str
    scope: str = ""
    directory: list[TocNode] = Field(default_factory=list)


class RegistryEntry(BaseModel):
    """来源登记条目：MAND/TPL/REQ/SCORE ID → 原文信息。"""

    model_config = {"extra": "allow"}

    type: str = ""
    text: str = ""
    出处: str = ""


class LineageCheck(BaseModel):
    unused_ids: list[str] = Field(default_factory=list)
    dangling_ids: list[str] = Field(default_factory=list)


class TenderDirectoryModel(BaseModel):
    model_config = {"extra": "allow"}

    response_documents: list[ResponseDocument]
    registry: dict[str, RegistryEntry] = Field(default_factory=dict)
    meta: dict[str, str] = Field(default_factory=dict)
    lineage_check: LineageCheck = Field(default_factory=LineageCheck)
    # 空目录守卫：脚本在未解析出目录时写入 warning 字段
    warning: str | None = None
    # 章节编号格式（缺省 None=chapter；目录编辑界面可改，合册每次现读）
    numbering: NumberingScheme | None = None


TENDER_DIRECTORY = ContractDef(
    kind="tender.directory",
    schema_id="tender-response-docs",
    schema_version=1,
    cardinality="task-single",
    llm_write_mode="suggest",
    editable=True,
    default_display_name="投标目录",
    model=TenderDirectoryModel,
)
