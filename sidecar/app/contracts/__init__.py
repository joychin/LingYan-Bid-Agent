"""平台契约目录（artifact-system-design.md §3）。

每个 Contract 声明一个业务类型的完整定义：身份（kind/schema/version）、
行为（cardinality / llm_write_mode / editable）与内容校验模型（Pydantic）。
契约真值只在 sidecar，客户端仅做 kind+schema → Processor 映射。

新增契约按设计文档 §13 清单打包接入：契约定义 → SKILL.md 指导 →
客户端 Processor → 任务模板集合 → 全链路验收（当前任务层未落地，模板步骤后置）。
"""

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel


@dataclass(frozen=True)
class ContractDef:
    kind: str
    schema_id: str
    schema_version: int
    # task-single：任务内一份（重发布为更新当前内容）；task-multi：每次新建
    cardinality: str
    # suggest：LLM 修改走候选采纳；direct-on-request：用户明确委托时可直接改写
    llm_write_mode: str
    # 用户是否可手动编辑（只读契约为 False）
    editable: bool
    default_display_name: str
    # Pydantic 校验模型，发布时 model_validate 兜底结构合法性
    model: Type[BaseModel]

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.schema_id}@{self.schema_version}"


from .note import DOC_NOTE  # noqa: E402
from .tender_directory import TENDER_DIRECTORY  # noqa: E402  （避免循环导入，置于类定义后）

CONTRACTS: dict[str, ContractDef] = {
    TENDER_DIRECTORY.key: TENDER_DIRECTORY,
    DOC_NOTE.key: DOC_NOTE,
}


def get_contract(key: str) -> ContractDef | None:
    return CONTRACTS.get(key)


def list_contracts() -> list[ContractDef]:
    return list(CONTRACTS.values())
