import { useEffect } from 'react'

/** 通用模态壳：遮罩 + Escape 关闭 + 卡片（默认 85vh/1000px，头部内容由调用方插槽）。
 * cardClassName 可整体替换卡片尺寸类（如设置窗 860×620），布局类（flex/圆角/边框）不可替换。 */
export function ModalShell({
  onClose,
  children,
  cardClassName,
}: {
  onClose: () => void
  children: React.ReactNode
  cardClassName?: string
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div
        className={`relative z-10 flex flex-col overflow-hidden rounded-2xl border bg-card shadow-md ${
          cardClassName ?? 'h-[85vh] w-[min(90vw,1000px)]'
        }`}
      >
        {children}
      </div>
    </div>
  )
}
