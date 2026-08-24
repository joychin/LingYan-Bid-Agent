/**
 * sidecar 通信层：地址与 token 解析 + fetch 封装。
 *
 * 地址/鉴权来源：
 *  - Tauri 环境优先从 command `get_sidecar_info()` 获取（端口 + 随机 token）
 *  - 浏览器开发模式默认走 Vite dev proxy（vite.config.ts `server.proxy`，/api → 8765）的
 *    同源相对路径，不需要知道 sidecar 地址、也没有 CORS 问题；需要直连时用
 *    `VITE_SIDECAR_URL` / `VITE_SIDECAR_TOKEN` 覆盖为绝对地址
 */

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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await rawFetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string> | undefined),
    },
  })
  return res.json() as Promise<T>
}

export interface Conversation {
  id: string
  title: string
  created_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface SendMessageResult {
  message_id: string
  run_id: string
}

export interface RunInfo {
  id: string
  conversation_id: string
  status: 'running' | 'completed' | 'error'
  error: string | null
  created_at: string
}

export interface Settings {
  base_url: string
  model: string
}

export function listConversations(): Promise<{ conversations: Conversation[] }> {
  return request('/conversations')
}

export function createConversation(title?: string): Promise<Conversation> {
  return request('/conversations', { method: 'POST', body: JSON.stringify({ title }) })
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

export function getSettings(): Promise<Settings> {
  return request('/settings')
}

export function putSettings(base_url: string, model: string): Promise<{ ok: boolean }> {
  return request('/settings', { method: 'PUT', body: JSON.stringify({ base_url, model }) })
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

export interface Artifact {
  id: string
  name: string
  type: 'html' | 'json' | 'md' | 'other'
  size: number
  created_at: string
  conversation_id: string | null
  /** 工作区内的绝对路径，供 reveal_in_folder 使用。 */
  path: string
}

export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  return rawFetch('/files', { method: 'POST', body: form }).then((r) => r.json())
}

export function listFiles(): Promise<{ files: FileItem[] }> {
  return request('/files')
}

export function deleteFile(name: string): Promise<{ ok: boolean }> {
  return request(`/files/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export function listArtifacts(): Promise<{ artifacts: Artifact[] }> {
  return request('/artifacts')
}

export async function getArtifactContent(id: string): Promise<{ content: string; contentType: string }> {
  const res = await rawFetch(`/artifacts/${id}/content`)
  return { content: await res.text(), contentType: res.headers.get('content-type') ?? '' }
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
