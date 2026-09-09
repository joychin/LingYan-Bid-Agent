/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * GET /runs/active 条目：占用中（running/waiting_input）的 run——侧栏跨会话
 * 「输出中」指示与任务级「等待确认」聚合的轮询数据源。
 */
export interface ActiveRun {
  id: string;
  conversation_id: string;
  status: "running" | "waiting_input";
}
export interface Artifact {
  artifact_id: string;
  display_name: string;
  kind: string;
  schema_id: string;
  schema_version: number;
  cardinality: "task-single" | "task-multi";
  editable: boolean;
  content_type: string;
  updated_at: string;
  source: ArtifactSource;
  content_seq: number;
  restore_available: boolean;
  task_id?: string | null;
  conversation_id?: string | null;
  path: string;
}
export interface ArtifactSource {
  thread_id?: string | null;
  run_id?: string | null;
}
export interface ArtifactContract {
  key: string;
  kind: string;
  schema_id: string;
  schema_version: number;
  cardinality: "task-single" | "task-multi";
  llm_write_mode: "suggest" | "direct-on-request";
  editable: boolean;
  default_display_name: string;
}
/**
 * 单产物轻量探测（GET /artifacts/{aid}/meta）：编辑器轮询外部更新
 * 只取版本号，不再拉全量列表。
 */
export interface ArtifactMeta {
  artifact_id: string;
  content_seq: number;
}
/**
 * 后台任务角色 → profile id（空串=跟随缺省：extract 回 default，vision 自动解析）。
 */
export interface BackgroundRoles {
  extract?: string;
  vision?: string;
}
export interface Conversation {
  id: string;
  task_id?: string | null;
  title: string;
  created_at: string;
}
export interface FileItem {
  name: string;
  abs_path: string;
  size: number;
  modified_at: string;
}
/**
 * HITL 待裁决动作（run.interrupt / run.state(waiting_input) 附带）。
 */
export interface InterruptRequestPayload {
  tool: string;
  args: {
    [k: string]: unknown;
  };
  description?: string;
  allowed?: string[];
  interrupt_id?: string;
}
/**
 * 锚点回文核对结果（抽取收尾跑，LLM 抽出的锚点回原文验证）：
 * pass=全部命中可自动确认；fail=留待人工确认（results 点名原因）。
 */
export interface KbAnchorCheck {
  status: "pass" | "fail";
  results?: KbAnchorCheckItem[];
}
/**
 * 单项核对结果：field=注册字段 code 或伪字段（_consistency/_anchors），
 * detail 为后端拼好的中文依据/原因。
 */
export interface KbAnchorCheckItem {
  field: string;
  label: string;
  ok: boolean;
  detail: string;
}
export interface KbFieldSource {
  value: string;
  source?: string | null;
}
/**
 * 时间边界警示（sidecar 从锚点字段动态计算，治理内部化）：
 * expired 已过期 / expiring 即将到期（90 天内）/ stale 资料较旧（3 年以上）。
 */
export interface KbFreshness {
  kind: "expired" | "expiring" | "stale";
  label: string;
}
export interface KbItem {
  id: string;
  file_name: string;
  file_hash: string;
  title: string;
  ext: string;
  doc_type?: string | null;
  doc_type_name: string;
  role: "fact" | "writing";
  capability: "stored" | "searchable" | "typed";
  parse_status: "pending" | "parsing" | "ready" | "failed";
  extract_status: "pending" | "running" | "done" | "failed" | "skipped";
  review_status: "pending_review" | "confirmed";
  progress?: string | null;
  suggested?: KbMetadata | null;
  business?: KbMetadata | null;
  check_result?: KbAnchorCheck | null;
  freshness?: KbFreshness[];
  error?: string | null;
  created_at: string;
  updated_at: string;
  md_ready: boolean;
}
/**
 * suggested（AI 建议）/ business（人工确认）共用形状：类型 + 内容说明
 * statement（带出处锚点，不预设内容字段）+ 检索问题 questions（「用户会怎么问」
 * 的短问句，独立 §questions 检索段）+ 锚点字段 + 自由字段。
 * business 侧另有 confirmed_by="auto"=程序核对自动确认（人工保存后标记消失）。
 */
export interface KbMetadata {
  doc_type: string;
  statement?: string | null;
  questions?: string[] | null;
  confidence?: number | null;
  fields?: {
    [k: string]: KbFieldSource;
  } | null;
  extra?: {
    [k: string]: KbFieldSource;
  } | null;
  confirmed_by?: "auto" | null;
}
export interface KbParseMeta {
  conversion: string;
  conversion_label: string;
  chars?: number | null;
  headings?: number | null;
  tables?: number | null;
  image_count?: number | null;
  warnings: string[];
  pages?: number | null;
  scanned_pages?: number[] | null;
  top_sections: string[];
}
/**
 * 类型注册表行（GET /kb/types）：role=浏览分组语义（知识库只做事实检索，
 * 章节拆分/写作素材在独立素材库）。
 */
export interface KbTypePayload {
  code: string;
  name: string;
  role: "fact" | "writing";
  time_fields?: string[];
}
/**
 * GET /messages 的消息行。过程快照瘦身（2026-09-08，reshape）：tools/todos/
 * reasoning 不再随列表下发（标书会话 11.4MB 随历史线性涨），改 GET
 * /conversations/{cid}/messages/{mid}/trace 按需取；列表只带折叠头所需的轻量
 * 摘要（traceSteps/tracePaused）与 durationMs/files。
 */
export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  run_id?: string | null;
  traceSteps?: number | null;
  tracePaused?: boolean | null;
  durationMs?: number | null;
  files?: RunFilePayload[] | null;
}
/**
 * 本轮文件（run_files 起止 diff）：path 相对 <task>/work/（WorkbenchFile.path
 * 同约定，前端 chip 直接透传工作台查看器）；op = created（本轮新建）/modified。
 */
export interface RunFilePayload {
  path: string;
  op: "created" | "modified";
}
/**
 * GET /conversations/{cid}/messages/{mid}/trace：单条消息的完整执行过程
 * （点开过程区按需取；tools 是嵌套树松散 dict，键序与前端 ToolStep 同构）。
 */
export interface MessageTrace {
  tools: {
    [k: string]: unknown;
  }[];
  todos: TodoItemPayload[];
  reasoning: string;
}
export interface TodoItemPayload {
  content: string;
  status: "pending" | "in_progress" | "completed";
}
/**
 * 一个已配置的模型接入（多 profile：任意供应商任意个；key 只回布尔）。
 */
export interface ModelProfile {
  id: string;
  name: string;
  base_url: string;
  model: string;
  image_support: boolean;
  context_window?: number | null;
  key_configured: boolean;
}
/**
 * 素材块：用户在目录树勾选的章节区间集合 + 备注（多区间；chars 服务端实算）。
 */
export interface MtBlock {
  id: string;
  file_id: string;
  title: string;
  note?: string;
  ranges?: number[][];
  chars?: number;
  created_at: string;
  file_name?: string | null;
  use_count?: number;
  last_used_at?: string | null;
}
/**
 * 素材库文件（用户上传、后台纯机械解析出目录树；无 LLM）。
 */
export interface MtFile {
  id: string;
  file_name: string;
  file_hash: string;
  parse_status: "pending" | "parsing" | "ready" | "failed";
  error?: string | null;
  created_at: string;
  updated_at: string;
  block_count?: number | null;
}
/**
 * 目录树节点（勾选界面数据源；children 递归；chars=区间实算字数）。
 */
export interface MtOutlineNode {
  标题?: string;
  start_line?: number | null;
  end_line?: number | null;
  level?: number | null;
  chars?: number | null;
  children?: MtOutlineNode[];
}
/**
 * 百度云文档解析（PaddleOCR-VL）——凭证只认 env，对外只回是否已配置。
 */
export interface OcrSettings {
  configured: boolean;
}
export interface RunInfo {
  id: string;
  conversation_id: string;
  status: "running" | "completed" | "error" | "waiting_input";
  error?: string | null;
  created_at: string;
  requests?: InterruptRequestPayload[] | null;
  last_seq?: number | null;
  token_usage?: string | null;
  error_code?: string | null;
}
/**
 * GET /runs/{rid}/snapshot：运行中过程快照（SSE 断线/页面重挂对账用）。
 *
 * tools 是 trace 步骤树（松散 dict，键序与前端 ToolStep 同构）；live 快照来自
 * sidecar 进程内存，无 live 时回退 run_traces 落库快照（last_seq 为 None）。
 * 只读对账，不产生消息、不改变 run 状态。
 */
export interface RunTraceSnapshot {
  run_id: string;
  conversation_id: string;
  status: "running" | "completed" | "error" | "waiting_input";
  last_seq?: number | null;
  tools?: {
    [k: string]: unknown;
  }[];
  todos?: TodoItemPayload[];
  reasoning?: string;
}
export interface SendMessageResult {
  message_id: string;
  run_id: string;
}
export interface Settings {
  models: ModelProfile[];
  default_model: string;
  background_roles: BackgroundRoles;
  ocr: OcrSettings;
  paths: SettingsPaths;
}
export interface SettingsPaths {
  data_dir: string;
  log_file: string;
}
export interface Task {
  id: string;
  title: string;
  progress_note: string;
  created_at: string;
}
/**
 * 文档模板（格式资产，与素材=内容资产分离）：内置基准或用户上传 .docx，
 * 全局一个默认模板位（active=当前默认）。
 */
export interface TemplateInfo {
  name: string;
  key: string;
  builtin?: boolean;
  active?: boolean;
  size?: number;
  mtime?: number;
}
export interface UploadResult {
  name: string;
  size: number;
  overwritten: boolean;
}
