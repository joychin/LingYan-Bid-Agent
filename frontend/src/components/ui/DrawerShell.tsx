import { useEffect } from 'react'

/** 右侧滑入抽屉壳：遮罩 + Escape 关闭 + 全高面板（mac 红绿灯让位靠左缝 ≥96px——
 * Overlay 标题栏灯簇占 x 13-73 且系统层绘制，任何盖住左上角的面板都无法避开）。
 * widthClass 替换面板宽度（默认 calc(100vw-96px)，左侧缝露出底层内容与灯簇）。 */
export function DrawerShell({
  onClose,
  children,
  widthClass = 'w-[calc(100vw-96px)]',
}: {
  onClose: () => void
  children: React.ReactNode
  widthClass?: string
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" aria-hidden />
      <aside
        className={`absolute right-0 top-0 bottom-0 ${widthClass} flex flex-col overflow-hidden rounded-l-2xl border bg-card shadow-md drawer-slide-in`}
      >
        {children}
      </aside>
    </div>
  )
}
