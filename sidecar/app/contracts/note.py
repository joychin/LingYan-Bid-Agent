"""通用笔记契约：doc.note / note-md@1。

未登记类型的统一收拢形态（P4）：LLM 在执行中想保存任何未注册类型的中间
成果时，一律以「笔记文档」保存（title + markdown 正文），保证任务上下文与
记忆可持续；类型系统保持平台封闭注册。客户端用通用文档 Processor 打开编辑。
"""

from pydantic import BaseModel

from . import ContractDef


class NoteModel(BaseModel):
    title: str = ""
    body_md: str = ""


DOC_NOTE = ContractDef(
    kind="doc.note",
    schema_id="note-md",
    schema_version=1,
    cardinality="task-multi",
    llm_write_mode="direct-on-request",
    editable=True,
    default_display_name="笔记",
    model=NoteModel,
)
