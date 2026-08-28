"""REST DTO 契约模型（/api 各端点响应 item 的单一事实源）。

- 仅作声明 + 测试校验用（test_contract_dto.py 对真实端点响应 model_validate），
  **不绑 response_model**——绑了会改变 FastAPI 运行时序列化（过滤未声明字段），零行为
  变化优先。
- scripts/gen_ts_types.py 生成 frontend/src/api/dto.gen.ts，client.ts 的手写 interface
  全部替换为生成类型 re-export。
- 字段镜像 api/*._to_api 与 db 行的现状；改端点响应形状 = 改这里 + 重新生成。
"""

from typing import Literal

from pydantic import BaseModel

from .events import InterruptRequestPayload, RunStatus, TodoItemPayload


class Task(BaseModel):
    id: str
    title: str
    progress_note: str
    created_at: str


class Conversation(BaseModel):
    id: str
    task_id: str | None = None
    title: str
    created_at: str


class Message(BaseModel):
    """GET /messages 的 assistant 消息；tools/todos 是 run_traces 快照（嵌套树，松散 dict，
    键序与前端 ToolStep 同构——前端用客户端类型标注，见 client.ts）。"""

    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    tools: list[dict] | None = None
    todos: list[TodoItemPayload] | None = None
    durationMs: int | None = None
    reasoning: str | None = None


class SendMessageResult(BaseModel):
    message_id: str
    run_id: str


class RunInfo(BaseModel):
    id: str
    conversation_id: str
    status: RunStatus
    error: str | None = None
    created_at: str
    requests: list[InterruptRequestPayload] | None = None
    last_seq: int | None = None


class RoleSettings(BaseModel):
    base_url: str
    model: str
    key_configured: bool


class LlmSettings(BaseModel):
    """llm 角色比 vlm 多 image_support（对话模型自报的图片输入能力，能力状态条消费）。"""

    base_url: str
    model: str
    key_configured: bool
    image_support: bool


class OcrSettings(BaseModel):
    """百度云文档解析（PaddleOCR-VL）——凭证只认 env，对外只回是否已配置。"""

    configured: bool


class SettingsPaths(BaseModel):
    data_dir: str
    log_file: str


class Settings(BaseModel):
    llm: LlmSettings
    vlm: RoleSettings
    ocr: OcrSettings
    paths: SettingsPaths


class FileItem(BaseModel):
    name: str
    size: int
    modified_at: str


class UploadResult(BaseModel):
    name: str
    size: int
    overwritten: bool


class ArtifactSource(BaseModel):
    thread_id: str | None = None
    run_id: str | None = None


class Artifact(BaseModel):
    artifact_id: str
    display_name: str
    kind: str
    schema_id: str
    schema_version: int
    cardinality: Literal["task-single", "task-multi"]
    editable: bool
    content_type: str
    updated_at: str
    source: ArtifactSource
    content_seq: int
    restore_available: bool
    scope: Literal["task", "conversation"]
    task_id: str | None = None
    conversation_id: str | None = None
    promotion_proposed: bool
    path: str


class ArtifactContract(BaseModel):
    key: str
    kind: str
    schema_id: str
    schema_version: int
    cardinality: Literal["task-single", "task-multi"]
    llm_write_mode: Literal["suggest", "direct-on-request"]
    editable: bool
    default_display_name: str


KbParseStatus = Literal["pending", "parsing", "ready", "failed"]
KbExtractStatus = Literal["pending", "running", "done", "failed", "skipped"]
KbReviewStatus = Literal["pending_review", "confirmed"]


class KbFieldType(BaseModel):
    code: str
    name: str
    fields: list[str]


class KbFieldSource(BaseModel):
    value: str
    source: str | None = None


class KbMetadata(BaseModel):
    doc_type: str
    confidence: float | None = None
    fields: dict[str, KbFieldSource] | None = None
    extra: dict[str, KbFieldSource] | None = None
    summary: str | None = None


class KbItem(BaseModel):
    id: str
    file_name: str
    file_hash: str
    title: str
    ext: str
    doc_type: str | None = None
    doc_type_name: str
    parse_status: KbParseStatus
    extract_status: KbExtractStatus
    review_status: KbReviewStatus
    suggested_metadata: KbMetadata | None = None
    business_metadata: KbMetadata | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    md_ready: bool


class KbParseMeta(BaseModel):
    conversion: str
    conversion_label: str
    chars: int | None = None
    headings: int | None = None
    tables: int | None = None
    warnings: list[str]
    pages: int | None = None
    scanned_pages: list[int] | None = None
    top_sections: list[str]
