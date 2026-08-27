/**
 * sidecar 通信层：地址与 token 解析 + fetch 封装。
 *
 * 地址/鉴权来源：
 *  - Tauri 环境优先从 command `get_sidecar_info()` 获取（端口 + 随机 token）
 *  - 浏览器开发模式默认走 Vite dev proxy（vite.config.ts `server.proxy`，/api → 8765）的
 *    同源相对路径，不需要知道 sidecar 地址、也没有 CORS 问题；需要直连时用
 *    `VITE_SIDECAR_URL` / `VITE_SIDECAR_TOKEN` 覆盖为绝对地址
 */

import type { InterruptRequest, TodoItem, ToolStep } from './sse'

export interface SidecarInfo {
  baseURL: string
  token: string | null
}

/** 在 Tauri webview 中运行（有 __TAURI_INTERNALS__）时为 true。 */
export function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

declare global {
  interface Window {
    __TAURI_INTERNALS__?: {
      invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>
    }
  }
}

const ENV_URL = import.meta.env.VITE_SIDECAR_URL as string | undefined
const ENV_TOKEN = import.meta.env.VITE_SIDECAR_TOKEN as string | undefined

export async function getSidecarInfo(): Promise<SidecarInfo> {
  if (isTauri() && window.__TAURI_INTERNALS__) {
    try {
      const info = (await window.__TAURI_INTERNALS__.invoke('get_sidecar_info')) as {
        port: number
        token: string
      }
      return { baseURL: `http://127.0.0.1:${info.port}`, token: info.token }
    } catch {
      // command 不可用时回退环境变量
    }
  }
  // 浏览器模式默认 baseURL 为空字符串 → 相对路径 /api/...，由 Vite proxy 同源转发。
  return { baseURL: ENV_URL ?? '', token: ENV_TOKEN ?? null }
}

/** 底层 fetch：拼 baseURL + Bearer token，统一 !ok 错误处理。不强制 JSON 头（上传用 FormData）。 */
export async function rawFetch(path: string, init?: RequestInit): Promise<Response> {
  const { baseURL, token } = await getSidecarInfo()
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${baseURL}/api${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? body.error ?? detail
    } catch {
      /* 非 JSON 响应 */
    }
    const err = new Error(detail) as Error & { status?: number }
    err.status = res.status
    throw err
  }
  return res
}

export async function request<T>(
  path: string,
  init?: RequestInit,
  opts?: { timeoutMs?: number },
): Promise<T> {
  const res = await rawFetch(path, {
    ...init,
    // 挂死防护：sidecar 忙/代理异常时请求永不 settle，会让 mutation 永久 pending
    // （如「+」新建会话的 isPending 卡死）。上传（XHR）与 SSE 走各自的通道，不受影响
    signal: AbortSignal.timeout(opts?.timeoutMs ?? 15_000),
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string> | undefined),
    },
  })
  return res.json() as Promise<T>
}

/** 任务（P4）：一次投标 = 项目文件夹，会话与正式稿产物的容器。 */
export interface Task {
  id: string
  title: string
  /** 进度便签（任务白板，markdown；LLM 与用户共同维护） */
  progress_note: string
  created_at: string
}

export interface Conversation {
  id: string
  task_id: string | null
  title: string
  created_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  /** assistant 消息的执行过程快照（run_traces 落库回填；有 run 且成功落库时才有） */
  tools?: ToolStep[]
  todos?: TodoItem[]
  /** run 总耗时（ms，run_traces 回填） */
  durationMs?: number | null
  /** 主 agent 思考流整段（run_traces 回填，推理模型才有；历史「深度思考」数据源） */
  reasoning?: string
}

export interface SendMessageResult {
  message_id: string
  run_id: string
}

export interface RunInfo {
  id: string
  conversation_id: string
  status: 'running' | 'completed' | 'error' | 'waiting_input'
  error: string | null
  created_at: string
  /** status=waiting_input 时附带：待裁决动作清单（恢复审批/问答卡） */
  requests?: InterruptRequest[]
  last_seq?: number
}

/** HITL 裁决（与 sidecar/langchain 的 Decision 形状一致；edit 为 API 保留、UI 暂不提供）。 */
export type HitlDecision =
  | { type: 'approve' }
  | { type: 'reject'; message?: string }
  | { type: 'respond'; message: string }
  | { type: 'edit'; edited_action: { name: string; args: Record<string, unknown> } }

export interface RoleSettings {
  base_url: string
  model: string
  key_configured: boolean
}

/** 双角色模型设置（llm=对话模型；vlm=视觉模型，可选，用于知识库图片/扫描件识别） */
export interface Settings {
  llm: RoleSettings
  vlm: RoleSettings
}

export type ModelRole = 'llm' | 'vlm'

export function listTasks(): Promise<{ tasks: Task[] }> {
  return request('/tasks')
}

/** 建任务；默认连带第一个会话（侧栏入口，建完即聊），选择器就地新建传 false。 */
export function createTask(
  title: string,
  withConversation = true,
): Promise<{ task: Task; conversation: Conversation | null }> {
  return request('/tasks', {
    method: 'POST',
    body: JSON.stringify({ title, with_conversation: withConversation }),
  })
}

export function patchTask(
  id: string,
  body: { title?: string; progress_note?: string },
): Promise<Task> {
  return request(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteTask(id: string): Promise<{ ok: boolean }> {
  // 归档要搬走整个任务目录（rmtree threads + mv），大任务可能明显超过常规接口的 15s
  return request(`/tasks/${id}`, { method: 'DELETE' }, { timeoutMs: 60_000 })
}

export function listConversations(): Promise<{ conversations: Conversation[] }> {
  return request('/conversations')
}

export function createConversation(taskId: string, title?: string): Promise<Conversation> {
  return request('/conversations', {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId, title }),
  })
}

export function patchConversation(id: string, title: string): Promise<Conversation> {
  return request(`/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
}

export function deleteConversation(id: string): Promise<{ ok: boolean }> {
  return request(`/conversations/${id}`, { method: 'DELETE' })
}

export function listMessages(convId: string): Promise<{ messages: Message[] }> {
  return request(`/conversations/${convId}/messages`)
}

export function sendMessage(convId: string, content: string): Promise<SendMessageResult> {
  return request(`/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

/** 最新 run 状态：SSE 断线期间 run 结束时据此收敛 running 态。 */
export function getLatestRun(convId: string): Promise<{ run: RunInfo | null }> {
  return request(`/conversations/${convId}/runs/latest`)
}

/** HITL 裁决续跑：waiting_input 的 run 以 decisions 从 interrupt 处继续（202 后台执行）。 */
export function resumeRun(rid: string, decisions: HitlDecision[]): Promise<{ ok: boolean; run_id: string }> {
  return request(`/runs/${rid}/resume`, {
    method: 'POST',
    body: JSON.stringify({ decisions }),
  })
}

/** 用户主动停止：置位协作式取消，run 在下一个流事件边界以 error「任务已停止」收尾。 */
export function cancelRun(rid: string): Promise<{ ok: boolean; run_id: string }> {
  return request(`/runs/${rid}/cancel`, { method: 'POST' })
}

export function getSettings(): Promise<Settings> {
  return request('/settings')
}

/** 按角色 PUT；vlm.base_url 传空串 = 清除视觉模型配置。 */
export function putSettings(
  role: ModelRole,
  base_url: string,
  model: string,
): Promise<{ ok: boolean }> {
  return request('/settings', { method: 'PUT', body: JSON.stringify({ [role]: { base_url, model } }) })
}

/** 设置对话框「测试」按钮：向对应角色端点发最小请求，验证 endpoint+key+model。 */
export function testModelConnection(role: ModelRole): Promise<{ ok: boolean; role: string }> {
  return request(`/settings/test?role=${role}`)
}

export interface FileItem {
  name: string
  size: number
  modified_at: string
}

export interface UploadResult {
  name: string
  size: number
  overwritten: boolean
}

/** 类型化 Artifact（artifact-system-design.md）：kind/schema 决定用哪个 Processor 打开。 */
export interface Artifact {
  artifact_id: string
  display_name: string
  kind: string
  schema_id: string
  schema_version: number
  cardinality: 'task-single' | 'task-multi'
  editable: boolean
  content_type: string
  updated_at: string
  source: { thread_id: string | null; run_id: string | null }
  /** 内容版本号：外部更新探测基准 */
  content_seq: number
  /** 是否存在可恢复的历史版本（覆盖前自动留底的安全网） */
  restore_available: boolean
  /** 作用域（§16）：task=任务正式稿；conversation=会话过程稿 */
  scope: 'task' | 'conversation'
  task_id: string | null
  conversation_id: string | null
  /** AI 建议转正（过程稿标记，等用户确认） */
  promotion_proposed: boolean
  /** 工作区内绝对路径，供 reveal_in_folder 使用。 */
  path: string
}

export function artifactKey(a: Pick<Artifact, 'kind' | 'schema_id' | 'schema_version'>): string {
  return `${a.kind}/${a.schema_id}@${a.schema_version}`
}

export interface ArtifactContract {
  key: string
  kind: string
  schema_id: string
  schema_version: number
  cardinality: 'task-single' | 'task-multi'
  llm_write_mode: 'suggest' | 'direct-on-request'
  editable: boolean
  default_display_name: string
}

export async function uploadFile(file: File, taskId: string): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  return rawFetch(`/files?task_id=${encodeURIComponent(taskId)}`, { method: 'POST', body: form }).then(
    (r) => r.json(),
  )
}

/** 任务级文件区（§16）：列出指定任务 files/ 下的上传文件。 */
export function listFiles(taskId: string): Promise<{ files: FileItem[] }> {
  return request(`/files?task_id=${encodeURIComponent(taskId)}`)
}

export function deleteFile(name: string, taskId: string): Promise<{ ok: boolean }> {
  return request(`/files/${encodeURIComponent(name)}?task_id=${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  })
}

/** 列产物：可按任务（正式稿）或会话（过程稿）过滤，无参 = 全部。 */
export function listArtifacts(scope?: { task_id?: string; conversation_id?: string }): Promise<{
  artifacts: Artifact[]
}> {
  const params = new URLSearchParams()
  if (scope?.task_id) params.set('task_id', scope.task_id)
  if (scope?.conversation_id) params.set('conversation_id', scope.conversation_id)
  const qs = params.toString()
  return request(`/artifacts${qs ? `?${qs}` : ''}`)
}

/** 过程稿转正到任务正式稿（用户点头的那一下）：复制不移动，正式稿覆盖留恢复点。 */
export function promoteArtifact(id: string): Promise<{ ok: boolean; artifact: Artifact }> {
  return request(`/artifacts/${id}/promote`, { method: 'POST', body: '{}' })
}

export function listContracts(): Promise<{ contracts: ArtifactContract[] }> {
  return request('/contracts')
}

export async function getArtifactContent(id: string): Promise<{ content: string; contentType: string }> {
  const res = await rawFetch(`/artifacts/${id}/content`)
  return { content: await res.text(), contentType: res.headers.get('content-type') ?? '' }
}

/** 编辑保存：非 force 时 409 = 内容已被外部更新（探测信号）；force = 用户裁决「保留我的版本」无条件覆盖。 */
export function updateArtifactContent(
  id: string,
  content: unknown,
  baseContentSeq: number,
  force = false,
): Promise<{ ok: boolean; content_seq: number; updated_at: string }> {
  return request(`/artifacts/${id}/content`, {
    method: 'PUT',
    body: JSON.stringify({ content, base_content_seq: baseContentSeq, force }),
  })
}

/** 恢复上一版（恢复点安全网；恢复本身也留底，可再次撤销）。 */
export function restoreArtifact(id: string): Promise<{ ok: boolean; content_seq: number; updated_at: string }> {
  return request(`/artifacts/${id}/restore`, { method: 'POST', body: '{}' })
}

/** 在系统文件管理器中定位工作区产物（仅 Tauri 环境）。 */
export async function revealInFolder(path: string): Promise<void> {
  if (!isTauri() || !window.__TAURI_INTERNALS__) return
  await window.__TAURI_INTERNALS__.invoke('reveal_in_folder', { path })
}

/** 探活 sidecar；返回是否可达（供 §11 sidecar 状态机）。 */
export async function checkHealth(): Promise<boolean> {
  try {
    const res = await rawFetch('/healthz')
    return res.ok
  } catch {
    return false
  }
}

// ===== 知识库（跨任务共享的公司资料层） =====

export interface KbFieldType {
  code: string
  name: string
  fields: string[]
}

export interface KbFieldSource {
  value: string
  source?: string
}

export interface KbMetadata {
  doc_type: string
  confidence?: number
  fields?: Record<string, KbFieldSource>
  extra?: Record<string, KbFieldSource>
  summary?: string
}

export type KbParseStatus = 'pending' | 'parsing' | 'ready' | 'failed'
export type KbExtractStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'
export type KbReviewStatus = 'pending_review' | 'confirmed'

export interface KbItem {
  id: string
  file_name: string
  file_hash: string
  title: string
  ext: string
  doc_type: string | null
  doc_type_name: string
  parse_status: KbParseStatus
  extract_status: KbExtractStatus
  review_status: KbReviewStatus
  suggested_metadata: KbMetadata | null
  business_metadata: KbMetadata | null
  error: string | null
  created_at: string
  updated_at: string
  md_ready: boolean
}

/** 解析概况（GET /kb/items/{id}/content 附带；档位标签真值在 sidecar）。 */
export interface KbParseMeta {
  conversion: string
  conversion_label: string
  chars: number | null
  headings: number | null
  tables: number | null
  warnings: string[]
  pages?: number
  scanned_pages?: number[]
  top_sections: string[]
}

export function listKbTypes(): Promise<{ types: KbFieldType[]; field_labels: Record<string, string> }> {
  return request('/kb/types')
}

export function getKbBadge(): Promise<{ pending: number }> {
  return request('/kb/badge')
}

export function listKbItems(params?: {
  review_status?: string
  doc_type?: string
  q?: string
}): Promise<{ items: KbItem[] }> {
  const search = new URLSearchParams()
  if (params?.review_status) search.set('review_status', params.review_status)
  if (params?.doc_type) search.set('doc_type', params.doc_type)
  if (params?.q) search.set('q', params.q)
  const qs = search.toString()
  return request(`/kb/items${qs ? `?${qs}` : ''}`)
}

export function getKbItem(id: string): Promise<KbItem> {
  return request(`/kb/items/${id}`)
}

export function getKbItemContent(
  id: string,
): Promise<{ id: string; content: string; meta: KbParseMeta | null }> {
  return request(`/kb/items/${id}/content`)
}

/** 确认元数据：fields 为 {字段code: 值}，保存即确认（review_status→confirmed）。 */
export function confirmKbMetadata(
  id: string,
  body: { doc_type: string; fields: Record<string, string>; extra?: Record<string, string> },
): Promise<KbItem> {
  return request(`/kb/items/${id}/metadata`, { method: 'PUT', body: JSON.stringify(body) })
}

export function retriggerKbItem(id: string): Promise<{ ok: boolean }> {
  return request(`/kb/items/${id}/retrigger`, { method: 'POST' })
}

export function deleteKbItem(id: string): Promise<{ ok: boolean }> {
  return request(`/kb/items/${id}`, { method: 'DELETE' })
}

/** 上传到知识库（XHR 带进度；无 task_id，与任务文件上传独立）。返回 Promise<progress> */
export function uploadKbFile(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ id: string; file_name: string; size: number; parse_status: string }> {
  return new Promise((resolve, reject) => {
    void getSidecarInfo().then(({ baseURL, token }) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${baseURL}/api/kb/files`)
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new Error('响应解析失败'))
          }
        } else {
          let detail = `上传失败（${xhr.status}）`
          try {
            const j = JSON.parse(xhr.responseText)
            if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
          } catch {
            /* 保底文案 */
          }
          reject(new Error(detail))
        }
      }
      xhr.onerror = () => reject(new Error('网络错误'))
      const fd = new FormData()
      fd.append('file', file)
      xhr.send(fd)
    })
  })
}

/** 原件二进制（图片条目预览）：带鉴权 fetch blob → objectURL（用完 revoke）。 */
export async function fetchKbItemRaw(id: string): Promise<string> {
  const { baseURL, token } = await getSidecarInfo()
  const resp = await fetch(`${baseURL}/api/kb/items/${id}/raw`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!resp.ok) throw new Error(`原件获取失败（${resp.status}）`)
  const blob = await resp.blob()
  return URL.createObjectURL(blob)
}
