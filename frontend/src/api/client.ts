/**
 * sidecar 通信层：地址与 token 解析 + fetch 封装。
 *
 * 地址/鉴权来源：
 *  - Tauri 环境优先从 command `get_sidecar_info()` 获取（端口 + 随机 token）
 *  - 浏览器开发模式默认走 Vite dev proxy（vite.config.ts `server.proxy`，/api → 8765）的
 *    同源相对路径，不需要知道 sidecar 地址、也没有 CORS 问题；需要直连时用
 *    `VITE_SIDECAR_URL` / `VITE_SIDECAR_TOKEN` 覆盖为绝对地址
 */

import type { TodoItem, ToolStep } from './sse'
import { normalizeToolSteps } from '@/lib/toolSteps'
import type {
  ActiveRun,
  Artifact,
  ArtifactContract,
  ArtifactMeta,
  ArtifactSource,
  Conversation,
  FileItem,
  KbFieldSource,
  KbFreshness,
  KbItem,
  KbMetadata,
  KbParseMeta,
  KbTypePayload,
  Message as MessageDto,
  ModelProfile,
  MtBlock,
  MtFile,
  MtOutlineNode,
  RestyleReport,
  RestyleResult,
  RunInfo,
  RunTraceSnapshot as RunTraceSnapshotDto,
  SendMessageResult,
  Settings,
  Task,
  TemplateInfo,
  UploadResult,
} from './dto.gen'

// ---- REST DTO 类型单一事实源：sidecar app/contracts/dto.py 的 pydantic 模型经
// scripts/gen_ts_types.py 生成 dto.gen.ts；这里 re-export 保持既有 import 路径不变。----
export type {
  ActiveRun,
  Artifact,
  ArtifactContract,
  ArtifactSource,
  Conversation,
  FileItem,
  KbFieldSource,
  KbFreshness,
  KbItem,
  KbMetadata,
  KbParseMeta,
  KbTypePayload,
  ModelProfile,
  MtBlock,
  MtFile,
  MtOutlineNode,
  RestyleReport,
  RestyleResult,
  RunInfo,
  SendMessageResult,
  Settings,
  Task,
  TemplateInfo,
  UploadResult,
}

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

/** 消息行（过程快照瘦身 2026-09-08 reshape）：列表只带 traceSteps/tracePaused
 *  摘要与 files/durationMs；完整 tools/todos/reasoning 走 fetchMessageTrace 按需取。 */
export type Message = MessageDto

/** HITL 裁决（与 sidecar/langchain 的 Decision 形状一致；edit 为 API 保留、UI 暂不提供）。 */
export type HitlDecision =
  | { type: 'approve' }
  | { type: 'reject'; message?: string }
  | { type: 'respond'; message: string }
  | { type: 'edit'; edited_action: { name: string; args: Record<string, unknown> } }

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

/** 占用中的 run（running/waiting_input）：侧栏跨会话状态指示轮询用。 */
export function fetchActiveRuns(): Promise<{ runs: ActiveRun[] }> {
  return request('/runs/active')
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

export async function listMessages(convId: string): Promise<{ messages: Message[] }> {
  // 过程快照瘦身（2026-09-08）：列表不再带 tools/todos/reasoning（标书会话 11.4MB
  // 随历史线性涨、每次 invalidate 全量重拉），历史过程区点开时按需取
  const res = await request<{ messages: Message[] }>(`/conversations/${convId}/messages`)
  return { messages: res.messages }
}

/** 思考档位（标准 reasoning_effort 三档；模型默认开思考，无关闭项） */
export type ThinkingLevel = 'low' | 'medium' | 'high'

export function sendMessage(
  convId: string,
  content: string,
  thinking: ThinkingLevel = 'low',
  model?: string,
): Promise<SendMessageResult> {
  const body: Record<string, unknown> = { content, thinking }
  if (model) body.model = model
  return request(`/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** 最新 run 状态：SSE 断线期间 run 结束时据此收敛 running 态。 */
export function getLatestRun(convId: string): Promise<{ run: RunInfo | null }> {
  return request(`/conversations/${convId}/runs/latest`)
}

/** 运行中过程快照：SSE 断线/页面重挂对账恢复 task 卡。基础字段来自 dto.gen；
 *  tools 是 trace 步骤树（键序与 ToolStep 同构），前端用客户端类型标注。 */
export interface RunSnapshot extends Omit<RunTraceSnapshotDto, 'tools' | 'todos'> {
  tools: ToolStep[]
  todos: TodoItem[]
}

export async function getRunSnapshot(rid: string): Promise<RunSnapshot> {
  const snap = await request<RunSnapshot>(`/runs/${rid}/snapshot`)
  return { ...snap, tools: normalizeToolSteps(snap.tools), todos: Array.isArray(snap.todos) ? snap.todos : [] }
}

/** 单条消息的完整执行过程（按需，2026-09-08 messages 瘦身）：历史过程区点开时取；
 *  出口套与快照路径相同的防御归一（旧快照缺键不打崩渲染层）。 */
export interface MessageTrace {
  tools: ToolStep[]
  todos: TodoItem[]
  reasoning: string
}

export async function fetchMessageTrace(convId: string, messageId: string): Promise<MessageTrace> {
  const res = await request<{ tools: unknown; todos: TodoItem[]; reasoning: string }>(
    `/conversations/${convId}/messages/${messageId}/trace`,
  )
  return {
    tools: normalizeToolSteps(res.tools),
    todos: Array.isArray(res.todos) ? res.todos : [],
    reasoning: res.reasoning ?? '',
  }
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

/** 模型 profile 请求体（id 前端生成 crypto.randomUUID，一旦生成不可变）。 */
export interface ModelBody {
  id: string
  name?: string
  base_url?: string
  model?: string
  image_support?: boolean
  /** 上下文窗口（token；不传=未知/自动，仅压缩触发档位用） */
  context_window?: number
}

/** 后台任务角色（空串=跟随缺省：抽取回默认模型，视觉走自动解析）。 */
export interface BackgroundRolesBody {
  extract?: string
  vision?: string
}

/** 全量覆盖写模型列表 + 默认模型（真值在 sidecar app.db，前端是唯一写者）。
 *  background_roles 可选：不传=服务端保留现值（模型弹窗保存不碰角色）。 */
export function putModels(
  models: ModelBody[],
  defaultModel: string,
  backgroundRoles?: BackgroundRolesBody,
): Promise<{ ok: boolean }> {
  const body: Record<string, unknown> = { models, default_model: defaultModel }
  if (backgroundRoles) body.background_roles = backgroundRoles
  return request('/settings/models', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

/** 保存模型 API Key 到本地库（只写不读；即时生效无需重启）。 */
export function putModelKey(modelId: string, apiKey: string): Promise<{ ok: boolean }> {
  return request('/settings/keys', {
    method: 'PUT',
    body: JSON.stringify({ model_id: modelId, api_key: apiKey }),
  })
}

/** 保存百度云文档解析 AK/SK 到本地库（只写不读；token 缓存即作废）。 */
export function putOcrKeys(apiKey: string, secretKey: string): Promise<{ ok: boolean }> {
  return request('/settings/ocr-keys', {
    method: 'PUT',
    body: JSON.stringify({ api_key: apiKey, secret_key: secretKey }),
  })
}

/** 设置「测试」按钮：model=<profile id> 发最小 chat；ocr 用 AK/SK 换一次 access_token 探活。
 *  X-Sidecar-Ping 自定义头为 sidecar 侧要求：跨站触发会被 CORS 预检挡住（防任意
 *  网页静默触发带 Key 的出站请求）。 */
export function testModelConnection(
  target: { model: string } | { role: 'ocr' },
): Promise<{ ok: boolean }> {
  const qs =
    'model' in target ? `model=${encodeURIComponent(target.model)}` : `role=${target.role}`
  return request(`/settings/test?${qs}`, { headers: { 'X-Sidecar-Ping': '1' } })
}

export function artifactKey(a: Pick<Artifact, 'kind' | 'schema_id' | 'schema_version'>): string {
  return `${a.kind}/${a.schema_id}@${a.schema_version}`
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

/** 列产物：可按任务（全部）或会话（provenance 来源）过滤，无参 = 全部。 */
export function listArtifacts(scope?: { task_id?: string; conversation_id?: string }): Promise<{
  artifacts: Artifact[]
}> {
  const params = new URLSearchParams()
  if (scope?.task_id) params.set('task_id', scope.task_id)
  if (scope?.conversation_id) params.set('conversation_id', scope.conversation_id)
  const qs = params.toString()
  return request(`/artifacts${qs ? `?${qs}` : ''}`)
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

/** 轻量探测：编辑器轮询外部更新只比版本号（不拉全量列表）。 */
export function getArtifactMeta(id: string): Promise<ArtifactMeta> {
  return request(`/artifacts/${id}/meta`)
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

export function listKbTypes(): Promise<{ types: KbTypePayload[]; field_labels: Record<string, string> }> {
  return request('/kb/types')
}

export function getKbBadge(): Promise<{ pending: number }> {
  return request('/kb/badge')
}

export function listKbItems(params?: {
  review_status?: string
  doc_type?: string
  q?: string
  role?: 'fact' | 'writing'
}): Promise<{ items: KbItem[] }> {
  const search = new URLSearchParams()
  if (params?.review_status) search.set('review_status', params.review_status)
  if (params?.doc_type) search.set('doc_type', params.doc_type)
  if (params?.q) search.set('q', params.q)
  if (params?.role) search.set('role', params.role)
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

/** 本文档图片清单（知识库内容页折叠区；图片仅供查看，与素材无关）。 */
export function getKbItemImages(
  id: string,
): Promise<{ id: string; images: { name: string; size: number }[] }> {
  return request(`/kb/items/${id}/images`)
}

/** 确认元数据：fields 为 {字段code: 值}，保存即确认（review_status→confirmed）。 */
export function confirmKbMetadata(
  id: string,
  body: {
    doc_type: string
    statement?: string
    questions?: string[]
    fields: Record<string, string>
    extra?: Record<string, string>
  },
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
): Promise<{ id: string; file_name: string; size: number }> {
  return _uploadWithProgress('/api/kb/files', file, onProgress)
}

// ===== 写作素材库（用户手工构建：上传→目录树勾选→建块+备注；与知识库分离） =====

/** 上传到素材库（解析出目录树供挑章节）。 */
export function uploadMtFile(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ id: string; file_name: string; size: number }> {
  return _uploadWithProgress('/api/materials/files', file, onProgress)
}

function _uploadWithProgress<T = { id: string; file_name: string; size: number }>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    void getSidecarInfo().then(({ baseURL, token }) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${baseURL}${path}`)
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

// ===== 文档模板库（格式资产：上传/激活/预览/任务换装）=====

export function uploadTemplate(file: File): Promise<TemplateInfo> {
  return _uploadWithProgress<TemplateInfo>('/api/templates', file)
}

export function listTemplates(): Promise<TemplateInfo[]> {
  return request('/templates')
}

export function activateTemplate(key: string): Promise<{ ok: boolean }> {
  return request(`/templates/${encodeURIComponent(key)}/activate`, { method: 'POST' })
}

export function deleteTemplate(key: string): Promise<{ ok: boolean }> {
  return request(`/templates/${encodeURIComponent(key)}`, { method: 'DELETE' })
}

/** 模板原始字节（版式预览渲染用；同 workbench raw——rawFetch 无 15s 超时）。 */
export async function fetchTemplateRaw(key: string): Promise<Blob> {
  const res = await rawFetch(`/templates/${encodeURIComponent(key)}/raw`)
  if (!res.ok) throw new Error(`模板拉取失败（${res.status}）`)
  return res.blob()
}

/** 把当前生效模板应用到任务已有正文节（重建式换装；「整本-」派生物跳过）。 */
export function applyTemplate(taskId: string): Promise<RestyleReport> {
  return request('/templates/apply', { method: 'POST', body: JSON.stringify({ task_id: taskId }) })
}

export function listMtFiles(): Promise<{ files: MtFile[] }> {
  return request('/materials/files')
}

export function getMtOutline(
  id: string,
): Promise<{ id: string; outline: MtOutlineNode[]; parse_status: string; error: string | null }> {
  return request(`/materials/files/${id}/outline`)
}

export function deleteMtFile(id: string): Promise<{ ok: boolean }> {
  return request(`/materials/files/${id}`, { method: 'DELETE' })
}

/** 重新解析（失败重试；ready 也可重触发，解析幂等）。 */
export function reparseMtFile(id: string): Promise<{ ok: boolean }> {
  return request(`/materials/files/${id}/reparse`, { method: 'POST' })
}

export function listMtBlocks(q?: string): Promise<{ blocks: MtBlock[] }> {
  return request(`/materials/blocks${q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`)
}

/** 块内容（预览用）：分节切片，节=区间标签+正文。 */
export interface MtBlockSection {
  start: number
  end: number
  text: string
}
export interface MtBlockContent {
  id: string
  title: string
  chars: number
  sections: MtBlockSection[]
}

export function getMtBlockContent(id: string): Promise<MtBlockContent> {
  return request(`/materials/blocks/${id}/content`)
}

export function createMtBlock(
  fileId: string,
  body: { title: string; note: string; ranges: [number, number][] },
): Promise<MtBlock> {
  return request(`/materials/files/${fileId}/blocks`, { method: 'POST', body: JSON.stringify(body) })
}

export function updateMtBlock(id: string, body: { title?: string; note?: string }): Promise<MtBlock> {
  return request(`/materials/blocks/${id}`, { method: 'PUT', body: JSON.stringify(body) })
}

export function deleteMtBlock(id: string): Promise<{ ok: boolean }> {
  return request(`/materials/blocks/${id}`, { method: 'DELETE' })
}

/** 原件二进制（图片条目预览）：带鉴权 fetch blob → objectURL（用完 revoke）。 */
export async function fetchKbItemRaw(id: string): Promise<string> {
  const { baseURL, token } = await getSidecarInfo()
  const resp = await fetch(`${baseURL}/api/kb/items/${id}/raw`, {    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!resp.ok) throw new Error(`原件获取失败（${resp.status}）`)
  const blob = await resp.blob()
  return URL.createObjectURL(blob)
}

// ---- 任务工作台（work/）：任务级共享的过程产物（parse/analysis/outline 的 md）----

export interface WorkbenchFile {
  path: string // 相对 work/ 的 posix 路径，如 "analysis/disqualification.md"
  abs_path: string // 绝对路径（面板右键「打开文件夹」用）
  mtime: string
  size: number
  /** 首行头部注释含「修订=用户」：人工改过，模型重跑前会提示 */
  revised: boolean
  /** 只读=parse/（引用行号的证据基准）或 .docx（渲染器不显示修订标记，正文节在 Word 中改） */
  editable: boolean
  /** 恢复点栈非空（restorepoints/ 保留 3 个；旧 .bak 未收编时也算） */
  has_restore: boolean
}

export interface WorkbenchContent {
  content: string
  hash: string
  revised: boolean
  editable: boolean
  has_restore: boolean
}

/** 轻量探测：编辑器轮询外部更新只比哈希（不拉全文）。 */
export function getWorkbenchMeta(
  taskId: string,
  path: string,
): Promise<Omit<WorkbenchContent, 'content'>> {
  const qs = new URLSearchParams({ task_id: taskId, path })
  return request(`/workbench/meta?${qs}`)
}

/** 列出任务 out/ 全部 markdown（json/隐藏文件服务端已排除）。 */
export function listWorkbench(taskId: string): Promise<{ files: WorkbenchFile[] }> {
  return request(`/workbench?task_id=${encodeURIComponent(taskId)}`)
}

export function getWorkbenchContent(taskId: string, path: string): Promise<WorkbenchContent> {
  const qs = new URLSearchParams({ task_id: taskId, path })
  return request(`/workbench/content?${qs}`)
}

/** 编辑保存：非 force 时 409 = 文件已被外部更新（模型重跑）；force = 「保留我的版本」。 */
export function putWorkbenchContent(
  taskId: string,
  path: string,
  content: string,
  baseHash: string,
  force = false,
): Promise<{ ok: boolean; hash: string }> {
  return request(`/workbench/content`, {
    method: 'PUT',
    body: JSON.stringify({ task_id: taskId, path, content, base_hash: baseHash, force }),
  })
}

/** 恢复上一版（当前内容先入恢复点栈，可再次恢复=撤销恢复；栈深 3）。 */
export function restoreWorkbench(taskId: string, path: string): Promise<WorkbenchContent> {
  return request(`/workbench/restore`, {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId, path }),
  })
}

/** docx 正文只读文本视图：段落编号+样式+表格概览（与模型侧 docx_section_read 同一序列化）。
 *  abs_path 供「在文件夹中显示」唤起 Word（看格式/审修订标记）。 */
export interface WorkbenchDocxView {
  lines: string[]
  abs_path: string
}

export function getWorkbenchDocxView(taskId: string, path: string): Promise<WorkbenchDocxView> {
  const qs = new URLSearchParams({ task_id: taskId, path })
  return request(`/workbench/docx-view?${qs}`)
}

/** docx 原始字节（面板版式预览）：浏览器本地渲染、文件不出本机；本机回环传输，
 *  不走 request() 的 15s 挂死防护（大合册可能明显更慢，rawFetch 无超时正合适）。 */
export async function fetchWorkbenchRaw(taskId: string, path: string): Promise<Blob> {
  const qs = new URLSearchParams({ task_id: taskId, path })
  const res = await rawFetch(`/workbench/raw?${qs}`)
  return res.blob()
}

/** 来源原件原始字节（pdf/docx/图片预览，前端按扩展名分流渲染器）。 */
export async function fetchSourceRaw(taskId: string, name: string): Promise<Blob> {
  const res = await rawFetch(
    `/files/${encodeURIComponent(name)}/raw?task_id=${encodeURIComponent(taskId)}`,
  )
  return res.blob()
}

// ==== sidecar 进程监管（Tauri 壳命令；浏览器开发模式一律返回空值） ====

/** Rust supervisor 记录的最近一次失败（kind 供前端分组文案，detail 已是中文人话）。 */
export interface SidecarFailure {
  kind: 'spawn_failed' | 'boot_timeout' | 'crashed' | 'exited'
  detail: string
}

/** 红态「重试」：清零熔断计数并请求 supervisor 重新拉起进程（仅 Tauri）。 */
export async function restartSidecar(): Promise<void> {
  if (!isTauri() || !window.__TAURI_INTERNALS__) return
  await window.__TAURI_INTERNALS__.invoke('restart_sidecar')
}

/** 最近一次 sidecar 失败原因；无记录/非 Tauri 返回 null。 */
export async function getSidecarFailure(): Promise<SidecarFailure | null> {
  if (!isTauri() || !window.__TAURI_INTERNALS__) return null
  try {
    const failure = (await window.__TAURI_INTERNALS__.invoke('get_sidecar_failure')) as
      | SidecarFailure
      | null
    return failure ?? null
  } catch {
    return null
  }
}

/** 导出诊断报告 txt（应用信息+失败原因+三路日志尾部），返回文件路径（仅 Tauri）。 */
export async function exportDiagnostics(): Promise<string | null> {
  if (!isTauri() || !window.__TAURI_INTERNALS__) return null
  const timestamp = new Date().toLocaleString('zh-CN', { hour12: false })
  const path = (await window.__TAURI_INTERNALS__.invoke('export_diagnostics', {
    timestamp,
  })) as string
  return path ?? null
}

/** 在文件管理器中打开 sidecar 日志目录（sidecar.log / sidecar-boot.log / 诊断报告）。 */
export async function revealSidecarLogs(): Promise<void> {
  if (!isTauri() || !window.__TAURI_INTERNALS__) return
  await window.__TAURI_INTERNALS__.invoke('reveal_sidecar_logs')
}
