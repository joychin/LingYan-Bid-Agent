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
  status: 'uploading' | 'done' | 'error'
  progress: number // 0-100；无 total 时为 -1（indeterminate）
  error?: string
}

interface FileUploadContextValue {
  uploads: UploadItem[]
  /** 打开系统文件选择器，选中后逐个上传。 */
  openFilePicker: () => void
  /** 直接上传拖入的文件。 */
  dropFiles: (files: File[]) => void
  /** 重新上传某个失败的上传项。 */
  retryUpload: (id: string) => void
}

const FileUploadContext = createContext<FileUploadContextValue | null>(null)

// 上传项以 id 而非文件名标识：后端支持同名覆盖，同名文件并发/重复上传时
// 各自的进度、失败与重试互不串扰
let uploadSeq = 0
const nextUploadId = () => `up_${Date.now()}_${uploadSeq++}`

/** App 级文件上传：隐藏 input + XHR 进度事件（§7 chip 进度 / 上传失败重试）。 */
export function FileUploadProvider({ children }: { children: React.ReactNode }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const retryRef = useRef<Map<string, File>>(new Map())
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const queryClient = useQueryClient()
  const { toast } = useToast()

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
    async (file: File, id: string) => {
      // 占位为 uploading（无 total -> -1）
      updateUpload({ id, name: file.name, size: file.size, status: 'uploading', progress: -1 })

      try {
        await uploadFileWithProgress(file, (percent) => {
          updateUpload({ id, name: file.name, size: file.size, status: 'uploading', progress: percent })
        })
        updateUpload({ id, name: file.name, size: file.size, status: 'done', progress: 100 })
        retryRef.current.delete(id) // 成功的不再需要重试引用；失败的保留
        queryClient.invalidateQueries({ queryKey: ['files'] })
        toast(`已上传 ${file.name}`, 'success')
      } catch (err) {
        updateUpload({
          id,
          name: file.name,
          size: file.size,
          status: 'error',
          progress: 0,
          error: err instanceof Error ? err.message : String(err),
        })
        toast(`上传 ${file.name} 失败`, 'error')
      }
    },
    [queryClient, toast, updateUpload],
  )

  const openFilePicker = useCallback(() => {
    inputRef.current?.click()
  }, [])

  const dropFiles = useCallback(
    (files: File[]) => {
      for (const f of files) {
        const id = nextUploadId()
        retryRef.current.set(id, f)
        void doUpload(f, id)
      }
    },
    [doUpload],
  )

  const retryUpload = useCallback(
    (id: string) => {
      const file = retryRef.current.get(id)
      if (!file) {
        toast('无法重试：本地文件不可用', 'error')
        return
      }
      void doUpload(file, id)
    },
    [doUpload, toast],
  )

  useEffect(() => {
    const input = inputRef.current
    if (!input) return
    const onChange = async () => {
      const files = Array.from(input.files ?? [])
      input.value = ''
      for (const f of files) {
        const id = nextUploadId()
        retryRef.current.set(id, f)
        await doUpload(f, id)
      }
    }
    input.addEventListener('change', onChange)
    return () => input.removeEventListener('change', onChange)
  }, [doUpload])

  return (
    <FileUploadContext.Provider value={{ uploads, openFilePicker, dropFiles, retryUpload }}>
      {children}
      <input ref={inputRef} type="file" className="hidden" multiple />
    </FileUploadContext.Provider>
  )
}

/** 用 XHR 上传并回调进度（fetch 无上传进度事件，改用 XHR 打同一 /api/files 端点）。 */
function uploadFileWithProgress(
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    void getSidecarInfo().then(({ baseURL, token }) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${baseURL}/api/files`)
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
        else onProgress(-1)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve()
        else reject(new Error(`上传失败: ${xhr.status}`))
      }
      xhr.onerror = () => reject(new Error('上传失败: 网络错误'))
      xhr.send(form)
    })
  })
}

export function useFileUpload(): FileUploadContextValue {
  const ctx = useContext(FileUploadContext)
  if (!ctx) throw new Error('useFileUpload must be used within FileUploadProvider')
  return ctx
}
