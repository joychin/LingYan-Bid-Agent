/**
 * 查询/加载失败的可重试错误卡（原 ChatView 局部组件，2026-09-17 批次⑤提为共享）。
 *
 * 用途：react-query isError 分支的统一呈现——「错误 ≠ 空态」是全仓约定
 * （useMessages/ChatView 先例：isError 必须排除出空态分支，失败可见可重试，
 * 不得伪装成「还没有数据」引导用户重复建任务/重传文件）。
 */

const ERROR_RECOVERY_HINT = '中断前已完成的产出都已保存，重新执行会基于现有成果继续，不会从零开始。'

export function ErrorCard({
  message,
  code,
  retryText,
  onRetry,
  onOpenSettings,
  onContinue,
}: {
  message: string
  code: string | null
  retryText: string
  onRetry: () => void
  /** llm_auth 的「去设置」入口（调用方已有设置窗开关回调时传入） */
  onOpenSettings?: () => void
  /** 「从断点继续」（code 可续且调用方提供入口时显示为主按钮） */
  onContinue?: () => void
}) {
  const cancelled = code === 'cancelled' || code === 'interrupted'
  const showHint =
    code === 'cancelled' || code === 'interrupted' || code === 'llm_unavailable' || code === 'llm_auth'
  const [headline, ...detailLines] = message.split('\n')
  return (
    <div
      className={
        cancelled
          ? 'rounded-lg border border-line bg-secondary px-3 py-2 text-sm text-muted-foreground'
          : 'rounded-lg border border-error/50 bg-error/5 px-3 py-2 text-sm text-error'
      }
    >
      {headline}
      {detailLines.length > 0 && (
        <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {detailLines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}
      {showHint && <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{ERROR_RECOVERY_HINT}</div>}
      <span className="ml-2 inline-flex gap-2">
        {code === 'llm_auth' && onOpenSettings && (
          <button type="button" className="hover:underline" onClick={onOpenSettings}>
            去设置
          </button>
        )}
        {onContinue && (
          <button type="button" className="font-medium hover:underline" onClick={onContinue}>
            从断点继续
          </button>
        )}
        {retryText.trim() && (
          <button type="button" className="hover:underline" onClick={onRetry}>
            {cancelled ? '重新执行' : '重试'}
          </button>
        )}
      </span>
    </div>
  )
}
