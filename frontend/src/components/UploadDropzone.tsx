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
      className="relative flex h-full w-full flex-col"
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false)
      }}
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
