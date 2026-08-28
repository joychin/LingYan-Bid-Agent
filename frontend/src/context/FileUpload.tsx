import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
import { getSidecarInfo } from '@/api/client'
import { useQueryClient } from '@tanstack/react-query'
import { useToast } from './Toast'

export interface UploadItem {
  id: string
  name: string
  size: number
  /** 归属任务（§16 任务级文件区）：freshFiles 按 taskScope 过滤，跨任务互不串扰 */
  taskId: string
  status: 'uploading' | 'done' | 'error'
  progress: number // 0-100；无 total 时为 -1（indeterminate）
  error?: string
  /** 失败时的 HTTP 状态码；缺省 = 网络层错误（无响应，可重试） */
  statusCode?: number
}

interface FileUploadContextValue {
  uploads: UploadItem[]
  /** 当前上传归属的任务 id（§16 任务级文件区）；null = 无任务上下文，上传被拒绝 */
  taskScope: string | null
  setTaskScope: (taskId: string | null) => void
  /** 打开系统文件选择器，选中后逐个上传（需已有任务上下文）。 */
  openFilePicker: () => void
  /** 直接上传拖入的文件（需已有任务上下文）。 */
  dropFiles: (files: File[]) => void
  /** 重新上传某个失败的上传项。 */
  retryUpload: (id: string) => void
  /** 关闭失败的上传项（从列表移除，不再显示）。 */
  dismissUpload: (id: string) => void
  /** 消息已随发送「告知」助手：移除对应上传项（freshFiles 依据其存在性，发送后 chip 即消失）。
   *  状态存 context 而非组件 ref——ChatView 按会话 key 重挂载不清零，切任务不串扰。 */
  acknowledgeUploads: (ids: string[]) => void
  /** 文件浮层真删后端文件后，同步移除对应「新上传」chip——否则合成消息会引用已删文件，
   *  模型看到 files/ 里没有它（实测会专门来问）。按 name+task 匹配（浮层只有文件名）。 */
  removeUploadsByName: (name: string, taskId: string) => void
}

const FileUploadContext = createContext<FileUploadContextValue | null>(null)

// 上传项以 id 而非文件名标识：后端支持同名覆盖，同名文件并发/重复上传时
// 各自的进度、失败与重试互不串扰
let uploadSeq = 0
const nextUploadId = () => `up_${Date.now()}_${uploadSeq++}`

/** App 级文件上传（§16 任务级文件区）：隐藏 input + XHR 进度事件（§7 chip 进度 / 上传失败重试）。 */
export function FileUploadProvider({ children }: { children: React.ReactNode }) {
  const inputRef = useRef<HTMLInputElement>(null)
  // 失败项的重试上下文：文件 + 发起时的归属任务（重试沿用原任务，不随当前视图漂移）
  const retryRef = useRef<Map<string, { file: File; taskId: string }>>(new Map())
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [taskScope, setTaskScopeState] = useState<string | null>(null)
  // 事件回调闭包读最新任务用（onChange/drop 时拿当下值，避免 stale closure）
  const taskScopeRef = useRef<string | null>(null)
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const setTaskScope = useCallback((taskId: string | null) => {
    taskScopeRef.current = taskId
    setTaskScopeState(taskId)
  }, [])

  const requireScope = useCallback((): string | null => {
    const tid = taskScopeRef.current
    if (!tid) {
      toast('请先选择所属任务，再上传文件', 'error')
      return null
    }
    return tid
  }, [toast])

  const updateUpload = useCallback((item: UploadItem) => {
    setUploads((prev) => {
      const idx = prev.findIndex((u) => u.id === item.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = item
        return next
      }
      return [...prev, item]
    })
  }, [])

  const doUpload = useCallback(
    async (file: File, id: string, taskId: string) => {
      // 占位为 uploading（无 total -> -1）
      updateUpload({ id, name: file.name, size: file.size, taskId, status: 'uploading', progress: -1 })

      try {
        await uploadFileWithProgress(file, taskId, (percent) => {
          updateUpload({ id, name: file.name, size: file.size, taskId, status: 'uploading', progress: percent })
        })
        // done 项保留在数组：InputComposer 的 freshFiles（空文本发送=通知助手处理新文件）依赖它
        updateUpload({ id, name: file.name, size: file.size, taskId, status: 'done', progress: 100 })
        retryRef.current.delete(id) // 成功的不再需要重试引用；失败的保留
        queryClient.invalidateQueries({ queryKey: ['files', taskId] })
        toast(`已上传 ${file.name}`, 'success')
      } catch (err) {
        updateUpload({
          id,
          name: file.name,
          size: file.size,
          taskId,
          status: 'error',
          progress: 0,
          error: err instanceof Error ? err.message : String(err),
          statusCode: err instanceof Error ? (err as Error & { status?: number }).status : undefined,
        })
        toast(`上传 ${file.name} 失败`, 'error')
      }
    },
    [queryClient, toast, updateUpload],
  )

  const openFilePicker = useCallback(() => {
    if (!requireScope()) return
    inputRef.current?.click()
  }, [requireScope])

  const dropFiles = useCallback(
    (files: File[]) => {
      const taskId = requireScope()
      if (!taskId) return
      for (const f of files) {
        const id = nextUploadId()
        retryRef.current.set(id, { file: f, taskId })
        void doUpload(f, id, taskId)
      }
    },
    [doUpload, requireScope],
  )

  const retryUpload = useCallback(
    (id: string) => {
      const entry = retryRef.current.get(id)
      if (!entry) {
        toast('无法重试：本地文件不可用', 'error')
        return
      }
      void doUpload(entry.file, id, entry.taskId)
    },
    [doUpload, toast],
  )

  const dismissUpload = useCallback((id: string) => {
    retryRef.current.delete(id)
    setUploads((prev) => prev.filter((u) => u.id !== id))
  }, [])

  const acknowledgeUploads = useCallback((ids: string[]) => {
    const set = new Set(ids)
    setUploads((prev) => prev.filter((u) => !set.has(u.id)))
  }, [])

  const removeUploadsByName = useCallback((name: string, taskId: string) => {
    setUploads((prev) => prev.filter((u) => !(u.name === name && u.taskId === taskId)))
  }, [])

  useEffect(() => {
    const input = inputRef.current
    if (!input) return
    const onChange = async () => {
      const files = Array.from(input.files ?? [])
      input.value = ''
      const taskId = requireScope()
      if (!taskId) return
      for (const f of files) {
        const id = nextUploadId()
        retryRef.current.set(id, { file: f, taskId })
        await doUpload(f, id, taskId)
      }
    }
    input.addEventListener('change', onChange)
    return () => input.removeEventListener('change', onChange)
  }, [doUpload, requireScope])

  return (
    <FileUploadContext.Provider
      value={{
        uploads,
        taskScope,
        setTaskScope,
        openFilePicker,
        dropFiles,
        retryUpload,
        dismissUpload,
        acknowledgeUploads,
        removeUploadsByName,
      }}
    >
      {children}
      <input ref={inputRef} type="file" className="hidden" multiple accept=".docx,.pdf,.txt,.md" />
    </FileUploadContext.Provider>
  )
}

/** 用 XHR 上传并回调进度（fetch 无上传进度事件，改用 XHR 打同一 /api/files 端点）。 */
function uploadFileWithProgress(
  file: File,
  taskId: string,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    getSidecarInfo().then(
      ({ baseURL, token }) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${baseURL}/api/files?task_id=${encodeURIComponent(taskId)}`)
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
          else onProgress(-1)
        }
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve()
            return
          }
          // 后端 detail 透传（同 rawFetch 的解析）：「.doc 请另存为 .docx」等提示直达 UI
          let detail = `上传失败: ${xhr.status}`
          try {
            const body = JSON.parse(xhr.responseText)
            detail = String(body.detail ?? body.error ?? detail)
          } catch {
            /* 非 JSON 响应 */
          }
          const err = new Error(detail) as Error & { status?: number }
          err.status = xhr.status
          reject(err)
        }
        xhr.onerror = () => reject(new Error('上传失败: 网络错误'))
        xhr.send(form)
      },
      reject, // getSidecarInfo 极端失败也落 error 态，chip 不能永久转圈
    )
  })
}

export function useFileUpload(): FileUploadContextValue {
  const ctx = useContext(FileUploadContext)
  if (!ctx) throw new Error('useFileUpload must be used within FileUploadProvider')
  return ctx
}
