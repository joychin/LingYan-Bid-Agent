"""REST DTO 契约模型（/api 各端点响应 item 的单一事实源）。

- 仅作声明 + 测试校验用（test_contract_dto.py 对真实端点响应 model_validate），
  **不绑 response_model**——绑了会改变 FastAPI 运行时序列化（过滤未声明字段），零行为
  变化优先。extra="forbid" 同理只在测试校验侧生效：响应多出未声明键（如 SQL 加列
  忘同步契约）时 model_validate 直接挂，测得出「新增键」漂移，运行时零影响。
- scripts/gen_ts_types.py 生成 frontend/src/api/dto.gen.ts，client.ts 的手写 interface
  全部替换为生成类型 re-export。
- 字段镜像 api/*._to_api 与 db 行的现状；改端点响应形状 = 改这里 + 重新生成。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .events import InterruptRequestPayload, RunStatus, TodoItemPayload


class _ContractModel(BaseModel):
    """全部 DTO 的基类：extra="forbid"（见模块 docstring）。"""

    model_config = ConfigDict(extra="forbid")


class Task(_ContractModel):
    id: str
    title: str
    progress_note: str
    created_at: str


class Conversation(_ContractModel):
    id: str
    task_id: str | None = None
    title: str
    created_at: str


class Message(_ContractModel):
    """GET /messages 的 assistant 消息；tools/todos 是 run_traces 快照（嵌套树，松散 dict，
    键序与前端 ToolStep 同构——前端用客户端类型标注，见 client.ts）。"""

    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    # 所属 run（additive）：同一 run 的暂停段+续跑段消息共享，前端据此聚合成单回合；
    # 旧行/无 run 语境为 NULL
    run_id: str | None = None
    tools: list[dict] | None = None
    todos: list[TodoItemPayload] | None = None
    durationMs: int | None = None
    reasoning: str | None = None


class SendMessageResult(_ContractModel):
    message_id: str
    run_id: str


class RunInfo(_ContractModel):
    id: str
    conversation_id: str
    status: RunStatus
    error: str | None = None
    created_at: str
    requests: list[InterruptRequestPayload] | None = None
    last_seq: int | None = None


class ActiveRun(_ContractModel):
    """GET /runs/active 条目：占用中（running/waiting_input）的 run——侧栏跨会话
    「输出中」指示与任务级「等待确认」聚合的轮询数据源。"""

    id: str
    conversation_id: str
    status: Literal["running", "waiting_input"]


class RunTraceSnapshot(_ContractModel):
    """GET /runs/{rid}/snapshot：运行中过程快照（SSE 断线/页面重挂对账用）。

    tools 是 trace 步骤树（松散 dict，键序与前端 ToolStep 同构）；live 快照来自
    sidecar 进程内存，无 live 时回退 run_traces 落库快照（last_seq 为 None）。
    只读对账，不产生消息、不改变 run 状态。"""

    run_id: str
    conversation_id: str
    status: RunStatus
    last_seq: int | None = None
    tools: list[dict] = Field(default_factory=list)
    todos: list[TodoItemPayload] = Field(default_factory=list)
    reasoning: str = ""


class ModelProfile(_ContractModel):
    """一个已配置的模型接入（多 profile：任意供应商任意个；key 只回布尔）。"""

    id: str
    name: str
    base_url: str
    model: str
    image_support: bool
    key_configured: bool


class OcrSettings(_ContractModel):
    """百度云文档解析（PaddleOCR-VL）——凭证只认 env，对外只回是否已配置。"""

    configured: bool


class SettingsPaths(_ContractModel):
    data_dir: str
    log_file: str


class BackgroundRoles(_ContractModel):
    """后台任务角色 → profile id（空串=跟随缺省：extract 回 default，vision 自动解析）。"""

    extract: str = ""
    vision: str = ""


class Settings(_ContractModel):
    models: list[ModelProfile]
    default_model: str
    background_roles: BackgroundRoles
    ocr: OcrSettings
    paths: SettingsPaths


class FileItem(_ContractModel):
    name: str
    size: int
    modified_at: str


class UploadResult(_ContractModel):
    name: str
    size: int
    overwritten: bool


class ArtifactSource(_ContractModel):
    thread_id: str | None = None
    run_id: str | None = None


class Artifact(_ContractModel):
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


class ArtifactContract(_ContractModel):
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


class KbFieldType(_ContractModel):
    code: str
    name: str
    fields: list[str]


class KbFieldSource(_ContractModel):
    value: str
    source: str | None = None


class KbMetadata(_ContractModel):
    doc_type: str
    confidence: float | None = None
    fields: dict[str, KbFieldSource] | None = None
    extra: dict[str, KbFieldSource] | None = None
    summary: str | None = None


class KbItem(_ContractModel):
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


class KbParseMeta(_ContractModel):
    conversion: str
    conversion_label: str
    chars: int | None = None
    headings: int | None = None
    tables: int | None = None
    warnings: list[str]
    pages: int | None = None
    scanned_pages: list[int] | None = None
    top_sections: list[str]
