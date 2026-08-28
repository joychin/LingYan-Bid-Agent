import { useEffect } from 'react'

/** 通用模态壳：遮罩 + Escape 关闭 + 85vh/1000px 卡片（头部内容由调用方插槽）。 */
export function ModalShell({
  onClose,
  children,
}: {
  onClose: () => void
  children: React.ReactNode
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
      <div className="relative z-10 flex h-[85vh] w-[min(90vw,1000px)] flex-col overflow-hidden rounded-2xl border bg-card shadow-md">
        {children}
      </div>
    </div>
  )
}
