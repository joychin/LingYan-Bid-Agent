import { useState } from 'react'
import type { DragEvent, ReactNode } from 'react'
import { Upload } from 'lucide-react'
import { useFileUpload } from '@/context/FileUpload'

/** 聊天区拖拽覆盖层：dragover 高亮，drop 上传到工作区根目录（走 FileUploadProvider，含进度）。 */
export function UploadDropzone({ children }: { children: ReactNode }) {
  const [over, setOver] = useState(false)
  const { dropFiles } = useFileUpload()

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) dropFiles(files)
  }

  return (
    <div
      className="relative flex h-full min-h-0 w-full flex-col"
      onDragOver={(e) => {
        e.preventDefault()
        // 拖到输入框（[data-drag-target]）上时本层让位：InputComposer 已给局部反馈，
        // 两层同时亮是双反馈打架（从聊天区一路拖到输入框，本层不会收到 dragleave，
        // 只能在这里按拖拽目标逐帧裁决）
        const el = e.target instanceof Element ? e.target : null
        setOver(!el?.closest('[data-drag-target]'))
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false)
      }}
      // 捕获段收尾：输入框的 drop 会 stopPropagation（防双上传），冒泡段的 onDrop 收不到
      // → 覆盖层永久卡在「松开上传到工作区」（实测拖文件进输入框必现）
      onDropCapture={() => setOver(false)}
      onDrop={handleDrop}
    >
      {children}
      {over && (
        <div className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center rounded-lg border-2 border-dashed border-primary/60 bg-primary/5">
          <div className="flex flex-col items-center gap-2 text-primary">
            <Upload className="h-8 w-8" />
            <span className="text-sm font-medium">松开上传到工作区</span>
          </div>
        </div>
      )}
    </div>
  )
}
