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
    # 阶段（task_stage.py 机械推导，零 LLM）：new/parsed/analyzed/outlined/drafting/
    # delivered——首页列表的「这个标走到哪」；last_activity_at=创建/最近run/最近产物
    # 三者最大值，供首页按最近活动排序（后端 GET /tasks 排序不动，侧栏保持创建序）
    stage: str
    last_activity_at: str


class Conversation(_ContractModel):
    id: str
    task_id: str | None = None
    title: str
    created_at: str


class RunFilePayload(_ContractModel):
    """本轮文件（run_files 起止 diff）：path 相对 <task>/work/（WorkbenchFile.path
    同约定，前端 chip 直接透传工作台查看器）；op = created（本轮新建）/modified。"""

    path: str
    op: Literal["created", "modified"]


class Message(_ContractModel):
    """GET /messages 的消息行。过程快照瘦身（2026-09-08，reshape）：tools/todos/
    reasoning 不再随列表下发（标书会话 11.4MB 随历史线性涨），改 GET
    /conversations/{cid}/messages/{mid}/trace 按需取；列表只带折叠头所需的轻量
    摘要（traceSteps/tracePaused）与 durationMs/files。"""

    id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    # 所属 run（additive）：同一 run 的暂停段+续跑段消息共享，前端据此聚合成单回合；
    # 旧行/无 run 语境为 NULL
    run_id: str | None = None
    # 过程摘要（assistant 且有 run_traces 行才有）
    traceSteps: int | None = None
    tracePaused: bool | None = None
    durationMs: int | None = None
    # 本轮 work/ 变更（additive，SSE 零改动--completed 后前端重取消息获得）；
    # 旧 run 无探测，恒 []
    files: list[RunFilePayload] | None = None


class MessageTrace(_ContractModel):
    """GET /conversations/{cid}/messages/{mid}/trace：单条消息的完整执行过程
    （点开过程区按需取；tools 是嵌套树松散 dict，键序与前端 ToolStep 同构）。"""

    tools: list[dict]
    todos: list[TodoItemPayload]
    reasoning: str


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
    # 本 run 模型用量快照（additive，2026-09-06）：JSON 文本 {input,output,cached,
    # reasoning}，旧 run / 进行中为 None；前端展示下一批接
    token_usage: str | None = None
    # 错误定性（additive，2026-09-08，取值域同事件契约 AgentError.code）：error 终态
    # 时非空；completed / 旧 run 为 None。前端错误卡据此选人话文案与操作入口
    error_code: str | None = None


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
    # 上下文窗口（token；null=未知/自动，仅压缩触发档位用）
    context_window: int | None = None
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
    abs_path: str
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
    task_id: str | None = None
    conversation_id: str | None = None
    path: str


class ArtifactMeta(_ContractModel):
    """单产物轻量探测（GET /artifacts/{aid}/meta）：编辑器轮询外部更新
    只取版本号，不再拉全量列表。"""

    artifact_id: str
    content_seq: int


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
# v3 内容角色（由 doc_type 派生，废除 v2 bucket）
KbRole = Literal["fact", "writing"]
KbCapability = Literal["stored", "searchable", "typed"]


class KbTypePayload(_ContractModel):
    """类型注册表行（GET /kb/types）：role=浏览分组语义（知识库只做事实检索，
    章节拆分/写作素材在独立素材库）。"""

    code: str
    name: str
    role: KbRole
    time_fields: list[str] = Field(default_factory=list)


class KbFieldSource(_ContractModel):
    value: str
    source: str | None = None


class KbMetadata(_ContractModel):
    """suggested（AI 建议）/ business（人工确认）共用形状：类型 + 内容说明
    statement（带出处锚点，不预设内容字段）+ 检索问题 questions（「用户会怎么问」
    的短问句，独立 §questions 检索段）+ 锚点字段 + 自由字段。
    business 侧另有 confirmed_by="auto"=程序核对自动确认（人工保存后标记消失）。"""

    doc_type: str
    statement: str | None = None
    questions: list[str] | None = None
    confidence: float | None = None
    fields: dict[str, KbFieldSource] | None = None
    extra: dict[str, KbFieldSource] | None = None
    confirmed_by: Literal["auto"] | None = None


class KbAnchorCheckItem(_ContractModel):
    """单项核对结果：field=注册字段 code 或伪字段（_consistency/_anchors），
    detail 为后端拼好的中文依据/原因。"""

    field: str
    label: str
    ok: bool
    detail: str


class KbAnchorCheck(_ContractModel):
    """锚点回文核对结果（抽取收尾跑，LLM 抽出的锚点回原文验证）：
    pass=全部命中可自动确认；fail=留待人工确认（results 点名原因）。"""

    status: Literal["pass", "fail"]
    results: list[KbAnchorCheckItem] = Field(default_factory=list)


class KbFreshness(_ContractModel):
    """时间边界警示（sidecar 从锚点字段动态计算，治理内部化）：
    expired 已过期 / expiring 即将到期（90 天内）/ stale 资料较旧（3 年以上）。"""

    kind: Literal["expired", "expiring", "stale"]
    label: str


class KbItem(_ContractModel):
    id: str
    file_name: str
    file_hash: str
    title: str
    ext: str
    doc_type: str | None = None
    doc_type_name: str
    role: KbRole
    capability: KbCapability
    parse_status: KbParseStatus
    extract_status: KbExtractStatus
    review_status: KbReviewStatus
    progress: str | None = None
    suggested: KbMetadata | None = None
    business: KbMetadata | None = None
    check_result: KbAnchorCheck | None = None
    freshness: list[KbFreshness] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str
    md_ready: bool


class MtFile(_ContractModel):
    """素材库文件（用户上传、后台纯机械解析出目录树；无 LLM）。"""

    id: str
    file_name: str
    file_hash: str
    parse_status: KbParseStatus
    error: str | None = None
    created_at: str
    updated_at: str
    block_count: int | None = None


class MtOutlineNode(_ContractModel):
    """目录树节点（勾选界面数据源；children 递归；chars=区间实算字数）。"""

    标题: str = ""
    start_line: int | None = None
    end_line: int | None = None
    level: int | None = None
    chars: int | None = None
    children: list["MtOutlineNode"] = Field(default_factory=list)


class MtBlock(_ContractModel):
    """素材块：用户在目录树勾选的章节区间集合 + 备注（多区间；chars 服务端实算）。"""

    id: str
    file_id: str
    title: str
    note: str = ""
    ranges: list[list[int]] = Field(default_factory=list)
    chars: int = 0
    created_at: str
    # 块列表端点附带来源文件名
    file_name: str | None = None
    # AI 引用打点（search_references 命中 + docx_material_inject 注入各计一次）
    use_count: int = 0
    last_used_at: str | None = None


class KbParseMeta(_ContractModel):
    conversion: str
    conversion_label: str
    chars: int | None = None
    headings: int | None = None
    tables: int | None = None
    image_count: int | None = None
    warnings: list[str]
    pages: int | None = None
    scanned_pages: list[int] | None = None
    top_sections: list[str]


class TemplateInfo(_ContractModel):
    """版式文件（格式资产，与素材=内容资产分离）：内置基准或用户上传 .docx，
    全局一个默认版式位（active=当前默认）。"""

    name: str  # 显示名（文件名主干；内置=「内置标书基准版式」）
    key: str  # 寻址键（用户版式=文件名；内置="__builtin__"）
    builtin: bool = False
    active: bool = False
    size: int = 0
    mtime: float = 0.0
