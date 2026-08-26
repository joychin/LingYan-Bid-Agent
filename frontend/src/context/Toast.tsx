import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

type ToastKind = 'info' | 'success' | 'error'

interface Toast {
  id: number
  message: string
  kind: ToastKind
}

interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

/** 右下角轻量 toast（§10 保存成功、各操作反馈），3s 自动消失。 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const idRef = useRef(0)

  const toast = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = idRef.current++
    setToasts((prev) => [...prev, { id, message, kind }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3000)
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-72 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              // pointer-events-none：toast 无交互，出现期间不可挡住右下角输入区的点击
              'pointer-events-none rounded-lg border bg-card px-3 py-2 text-sm shadow-md',
              t.kind === 'error' && 'border-error/40 text-error',
              t.kind === 'success' && 'border-success/40 text-success',
              t.kind === 'info' && 'border-border text-foreground',
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
