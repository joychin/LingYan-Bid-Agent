import { FileText, X } from 'lucide-react'
import { useFileUpload } from '@/context/FileUpload'
import { formatSize, cn } from '@/lib/utils'

/**
 * 上传文件 chips（输入区通用件）：上传中/失败 chip 行 + 新上传（未随消息告知）
 * 高亮 chip 行。自包含读 FileUpload context，只显示当前任务的条目。
 * InputComposer（输入框上方）与 HITL 提问卡底部的上传行共用——等待期输入框被
 * 提问卡原位替换后，补传窗口的上传可见性由这里保住。
 */
export function UploadChips({ className }: { className?: string }) {
  const { uploads, taskScope, retryUpload, dismissUpload } = useFileUpload()
  // 上传中/失败 chip 只显示当前任务的（AGENTS 约定「文件 chips 只显示当前任务的文件」）：
  // 错误 chip 不随任务切换泄漏到别的任务输入区（上传目标仍锁原任务，重试不受影响）
  const inFlight = uploads.filter((u) => u.status !== 'done' && u.taskId === taskScope)
  // 本任务新上传、尚未随任何消息「告知」的文件
  const freshFiles = uploads.filter((u) => u.status === 'done' && u.taskId === taskScope)
  if (inFlight.length === 0 && freshFiles.length === 0) return null
  return (
    <>
      {inFlight.length > 0 && (
        <div className={cn('flex flex-wrap items-center gap-2', className)}>
          {inFlight.map((u) => (
            <div
              key={u.id}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 text-xs',
                u.status === 'error' ? 'border-error/50 bg-error/5 text-error' : 'border-input bg-background',
              )}
            >
              <FileText className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="max-w-[180px] truncate">{u.name}</span>
              <span className="text-muted-foreground">{formatSize(u.size)}</span>
              {u.status === 'uploading' && (
                <span className="h-1 w-16 overflow-hidden rounded-full bg-muted">
                  <span
                    className={cn('block h-full bg-primary', u.progress < 0 && 'w-1/3 animate-pulse')}
                    style={u.progress >= 0 ? { width: `${u.progress}%` } : undefined}
                  />
                </span>
              )}
              {u.status === 'error' && (
                <>
                  <span className="max-w-[220px] truncate" title={u.error}>
                    {u.error}
                  </span>
                  {/* statusCode 缺省=网络层错误；400/413 是永久性失败，重试无意义，只留关闭 */}
                  {(u.statusCode == null || u.statusCode >= 500) && (
                    <button type="button" onClick={() => retryUpload(u.id)} className="text-error hover:underline">
                      重试
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => dismissUpload(u.id)}
                    className="opacity-60 hover:opacity-100"
                    aria-label={`移除 ${u.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      {/* 新上传（未随消息告知）：高亮 chip，随消息告知后消失 */}
      {freshFiles.length > 0 && (
        <div className={cn('flex flex-wrap items-center gap-2', className)}>
          {freshFiles.map((f) => (
            <div
              key={f.id}
              title="新上传：随回答/消息告知助手"
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/60 bg-secondary px-2 py-0.5 text-xs text-foreground"
            >
              <FileText className="h-3.5 w-3.5 text-primary" />
              <span className="max-w-[180px] truncate">{f.name}</span>
              <span className="text-muted-foreground">{formatSize(f.size)}</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
