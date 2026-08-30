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
  scope: "task" | "conversation";
  task_id?: string | null;
  conversation_id?: string | null;
  promotion_proposed: boolean;
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
}
export interface KbFieldSource {
  value: string;
  source?: string | null;
}
export interface KbFieldType {
  code: string;
  name: string;
  fields: string[];
}
export interface KbItem {
  id: string;
  file_name: string;
  file_hash: string;
  title: string;
  ext: string;
  doc_type?: string | null;
  doc_type_name: string;
  parse_status: "pending" | "parsing" | "ready" | "failed";
  extract_status: "pending" | "running" | "done" | "failed" | "skipped";
  review_status: "pending_review" | "confirmed";
  suggested_metadata?: KbMetadata | null;
  business_metadata?: KbMetadata | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  md_ready: boolean;
}
export interface KbMetadata {
  doc_type: string;
  confidence?: number | null;
  fields?: {
    [k: string]: KbFieldSource;
  } | null;
  extra?: {
    [k: string]: KbFieldSource;
  } | null;
  summary?: string | null;
}
export interface KbParseMeta {
  conversion: string;
  conversion_label: string;
  chars?: number | null;
  headings?: number | null;
  tables?: number | null;
  warnings: string[];
  pages?: number | null;
  scanned_pages?: number[] | null;
  top_sections: string[];
}
/**
 * GET /messages 的 assistant 消息；tools/todos 是 run_traces 快照（嵌套树，松散 dict，
 * 键序与前端 ToolStep 同构——前端用客户端类型标注，见 client.ts）。
 */
export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  run_id?: string | null;
  tools?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  todos?: TodoItemPayload[] | null;
  durationMs?: number | null;
  reasoning?: string | null;
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
  key_configured: boolean;
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
export interface UploadResult {
  name: string;
  size: number;
  overwritten: boolean;
}
