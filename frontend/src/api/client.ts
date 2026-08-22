/**
 * sidecar 通信层：地址与 token 解析 + fetch 封装。
 *
 * 地址/鉴权来源：
 *  - Tauri 环境优先从 command `get_sidecar_info()` 获取（端口 + 随机 token）
 *  - 浏览器开发模式回退 VITE_SIDECAR_URL / VITE_SIDECAR_TOKEN 环境变量
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
  return { baseURL: ENV_URL ?? 'http://127.0.0.1:8765', token: ENV_TOKEN ?? null }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { baseURL, token } = await getSidecarInfo()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
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

export function listMessages(convId: string): Promise<{ messages: Message[] }> {
  return request(`/conversations/${convId}/messages`)
}

export function sendMessage(convId: string, content: string): Promise<SendMessageResult> {
  return request(`/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

export function getSettings(): Promise<Settings> {
  return request('/settings')
}

export function putSettings(base_url: string, model: string): Promise<{ ok: boolean }> {
  return request('/settings', { method: 'PUT', body: JSON.stringify({ base_url, model }) })
}
