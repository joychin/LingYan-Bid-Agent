/**
 * 全局悬停提示（事件委托版）：给任意带 [title] / [data-tip] 的元素显示气泡。
 *
 * 动因（2026-09-15）：Tauri 桌面端在 macOS 用 WKWebView，**不渲染原生 title 悬停
 * 提示**（嵌入式 WebView 的已知共性，Electron/webview 同病）——项目里大量
 * title=（状态点/按钮/入口 tips）在桌面端一直是死的。本组件以 window 级事件
 * 委托统一兜底：显示期间摘掉 el.title 防浏览器双显（离开时恢复），开发浏览器
 * 与桌面端行为一致。
 *
 * 行为对齐原生 title 的克制：悬停 ~350ms 才出现、随光标移动、滚动/离锚即隐。
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const SHOW_DELAY_MS = 350
const OFFSET_X = 14
const OFFSET_Y = 20
const VIEWPORT_MARGIN = 8

/** 光标坐标 + 气泡尺寸 → 视口内坐标（右下优先，右/下贴边翻到左/上；纯函数供单测）。 */
export function computeTipPosition(
  x: number,
  y: number,
  w: number,
  h: number,
  vw: number,
  vh: number,
): { left: number; top: number } {
  let left = x + OFFSET_X
  let top = y + OFFSET_Y
  if (left + w > vw - VIEWPORT_MARGIN) left = Math.max(VIEWPORT_MARGIN, x - w - OFFSET_X)
  if (top + h > vh - VIEWPORT_MARGIN) top = Math.max(VIEWPORT_MARGIN, y - h - OFFSET_Y)
  return { left, top }
}

function tipTextOf(el: HTMLElement): string {
  const fromData = el.getAttribute('data-tip')
  return (fromData ?? el.title ?? '').trim()
}

export function HoverTip() {
  const [text, setText] = useState<string | null>(null)
  const tipRef = useRef<HTMLDivElement | null>(null)
  const posRef = useRef({ x: 0, y: 0 })
  const sizeRef = useRef({ w: 0, h: 0 })
  const holderRef = useRef<HTMLElement | null>(null)
  const savedTitleRef = useRef<{ el: HTMLElement; title: string } | null>(null)

  // 按实测尺寸把气泡放到光标附近（文本变化后重排；首帧藏在屏外防角上闪烁）
  useLayoutEffect(() => {
    const el = tipRef.current
    if (!el || !text) return
    sizeRef.current = { w: el.offsetWidth, h: el.offsetHeight }
    const { left, top } = computeTipPosition(
      posRef.current.x,
      posRef.current.y,
      sizeRef.current.w,
      sizeRef.current.h,
      window.innerWidth,
      window.innerHeight,
    )
    el.style.left = `${left}px`
    el.style.top = `${top}px`
    el.style.visibility = 'visible'
  }, [text])

  useEffect(() => {
    let showTimer: number | undefined
    const placed = () => tipRef.current?.style.visibility === 'visible'

    const place = () => {
      const el = tipRef.current
      if (!el) return
      const { left, top } = computeTipPosition(
        posRef.current.x,
        posRef.current.y,
        sizeRef.current.w,
        sizeRef.current.h,
        window.innerWidth,
        window.innerHeight,
      )
      el.style.left = `${left}px`
      el.style.top = `${top}px`
    }

    const restoreTitle = () => {
      const saved = savedTitleRef.current
      if (saved) saved.el.title = saved.title
      savedTitleRef.current = null
    }

    const hide = () => {
      window.clearTimeout(showTimer)
      if (holderRef.current) restoreTitle()
      holderRef.current = null
      setText(null)
    }

    const scheduleShow = (el: HTMLElement, x: number, y: number) => {
      if (holderRef.current === el) {
        posRef.current = { x, y }
        if (placed()) place()
        return
      }
      hide()
      holderRef.current = el
      posRef.current = { x, y }
      showTimer = window.setTimeout(() => {
        const t = tipTextOf(el)
        if (!t || holderRef.current !== el || !el.isConnected) {
          holderRef.current = null
          return
        }
        // 摘 title 防浏览器端双显（离开时恢复）
        if (el.title) savedTitleRef.current = { el, title: el.title }
        setText(t)
      }, SHOW_DELAY_MS)
    }

    const holderFrom = (target: EventTarget | null): HTMLElement | null => {
      if (!(target instanceof Element)) return null
      const el = target.closest('[data-tip],[title]')
      return el instanceof HTMLElement ? el : null
    }

    const onMouseOver = (e: MouseEvent) => {
      const el = holderFrom(e.target)
      if (!el) {
        // 移入空白区：取消未出的提示；已出的等 mouseout 收（native 语义同款）
        if (!holderRef.current) window.clearTimeout(showTimer)
        return
      }
      scheduleShow(el, e.clientX, e.clientY)
    }
    const onMouseOut = (e: MouseEvent) => {
      const el = holderRef.current
      if (!el) return
      if (e.relatedTarget instanceof Node && el.contains(e.relatedTarget)) return
      hide()
    }
    const onMouseMove = (e: MouseEvent) => {
      const el = holderRef.current
      if (!el) return
      if (!el.isConnected) {
        hide()
        return
      }
      posRef.current = { x: e.clientX, y: e.clientY }
      if (placed()) place()
    }
    const onScroll = () => hide()
    const onBlur = () => hide()
    // 右键弹菜单时收掉 tooltip（2026-09-23 B5）：光标没离开行、mouseout 不触发，
    // 高 z-index 的 tooltip 会压住右键菜单第一项
    const onContextMenu = () => hide()

    window.addEventListener('mouseover', onMouseOver)
    window.addEventListener('mouseout', onMouseOut)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('blur', onBlur)
    window.addEventListener('contextmenu', onContextMenu)
    return () => {
      window.clearTimeout(showTimer)
      restoreTitle()
      window.removeEventListener('mouseover', onMouseOver)
      window.removeEventListener('mouseout', onMouseOut)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('blur', onBlur)
      window.removeEventListener('contextmenu', onContextMenu)
    }
  }, [])

  if (!text) return null
  return createPortal(
    <div ref={tipRef} className="hover-tip" role="tooltip">
      {text}
    </div>,
    document.body,
  )
}
