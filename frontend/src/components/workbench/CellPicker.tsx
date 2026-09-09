/**
 * 表格单元格选择浮层（写作指引素材/依据列编辑态，2026-09-09 设计稿 A 方向）：
 * fixed 定位贴触发器下方、右/底缘回退绝不溢出视口（ContextMenu 同款纪律）；
 * Escape 在捕获段拦截并阻断（工作区编辑器的收起语义互不误触）、外点/滚动/缩放
 * 关闭——fixed 跟不走滚动中的锚点，重定位不如关掉重开。内容（搜索框+候选列表）
 * 由调用方给；滚动列表在自己内部的滚动不算外滚，不触发关闭。
 */

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export function CellPicker({
  anchor,
  onClose,
  width = 320,
  children,
}: {
  /** 触发器元素（浮层贴其下方；调用方持有 ref 传入） */
  anchor: HTMLElement | null
  onClose: () => void
  width?: number
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  // 挂载即测量定位（useLayoutEffect 防首帧闪跳）；下方放不下且上方空间更大时向上翻
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !anchor) return
    const r = anchor.getBoundingClientRect()
    const h = el.offsetHeight
    const below = r.bottom + 4
    const top = below + h > window.innerHeight - 8 && r.top - h - 4 > 8 ? r.top - h - 4 : below
    setPos({
      left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
      top: Math.max(8, Math.min(top, window.innerHeight - h - 8)),
    })
  }, [anchor, width])

  useEffect(() => {
    // 外点关闭；但落在锚点（触发器/输入框）内的点击除外——打开它的那一下点击在
    // 冒泡到 window 时监听已注册（React 离散事件同步刷效果），不豁免会秒开秒关，
    // 触发器的开合由其自身 toggle 处理；点其他行的触发器则正常走这里关闭（单浮层）。
    const close = (e: Event) => {
      if (e.target instanceof Node && anchor?.contains(e.target)) return
      onClose()
    }
    const onScroll = (e: Event) => {
      // 浮层内部候选列表的滚动不是外滚
      if (e.target instanceof Node && ref.current?.contains(e.target)) return
      onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onClose()
    }
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', close)
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', close)
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [anchor, onClose])

  return (
    <div
      ref={ref}
      className="fixed z-50 flex flex-col rounded-lg border border-line bg-card py-1 shadow-lg"
      style={{
        left: pos?.left ?? -9999,
        top: pos?.top ?? -9999,
        width,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  )
}
