/**
 * pdf 版式预览渲染体（懒加载分包，经 React.lazy 引入）：pdfjs-dist 在浏览器
 * 本地渲染，文件不出本机。纯渲染组件——宿主负责取字节与失败兜底（onError 上抛）。
 *
 * 性能口径：逐页 canvas 懒渲染（IntersectionObserver 进视口前约一屏才画，
 * 标书几百页不一次性渲染）；fit 宽度缩放（面板拖宽经 ResizeObserver 防抖后整列
 * 重算重渲）；devicePixelRatio 高清出图。每实例独立 worker 线程，卸载即销毁。
 */
import { useEffect, useRef, useState } from 'react'
import { GlobalWorkerOptions, getDocument } from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?worker'

// 模块级 worker 单例：多文档共享同一 worker 线程（pdfjs 官方用法），预览实例
// 卸载只销毁文档不 terminate 线程（常驻约几 MB，供后续预览复用）。
// 说明：PDFWorker 构造器的 port 参数在 6.x 的 .d.ts 里类型写坏（null|undefined，
// 运行时实际接受 Worker），故走 GlobalWorkerOptions.workerPort 这条类型正确的路。
let workerReady = false
function ensureWorker() {
  if (!workerReady) {
    GlobalWorkerOptions.workerPort = new PdfWorker()
    workerReady = true
  }
}

/** 单页：懒可见 → 画布渲染。占位用 A4 比例 aspect-ratio，渲染后画布自然替换。 */
function PdfPage({
  pdf,
  pageNumber,
  width,
  registerSlot,
}: {
  pdf: PDFDocumentProxy
  pageNumber: number
  width: number
  registerSlot: (n: number, el: HTMLDivElement | null) => void
}) {
  const slotRef = useRef<HTMLDivElement>(null)
  // 首两页直接渲染（进面板即有内容），其余进视口前 400px 再渲
  const [visible, setVisible] = useState(pageNumber <= 2)

  useEffect(() => {
    const el = slotRef.current
    if (!el || visible) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true)
          io.disconnect()
        }
      },
      { rootMargin: '400px 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [visible])

  useEffect(() => {
    if (!visible) return
    const slot = slotRef.current
    if (!slot) return
    let cancelled = false
    let task: { cancel: () => void } | null = null
    ;(async () => {
      const page: PDFPageProxy = await pdf.getPage(pageNumber)
      if (cancelled) return
      const base = page.getViewport({ scale: 1 })
      const viewport = page.getViewport({ scale: width / base.width })
      const canvas = document.createElement('canvas')
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * dpr)
      canvas.height = Math.floor(viewport.height * dpr)
      canvas.style.width = '100%'
      canvas.style.display = 'block'
      const renderTask = page.render({
        canvas,
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      })
      task = renderTask
      await renderTask.promise
      if (cancelled) return
      slot.replaceChildren(canvas)
    })().catch(() => {
      /* 单页失败静默留占位：整档加载失败由宿主 onError 报 */
    })
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [visible, pdf, pageNumber, width])

  return (
    <div
      ref={(el) => {
        slotRef.current = el
        registerSlot(pageNumber, el)
      }}
      className="pdf-page-slot"
      style={{ width }}
    />
  )
}

export default function PdfPreviewBody({
  data,
  onError,
}: {
  data: Blob
  onError?: (e: unknown) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [width, setWidth] = useState(0)
  const [current, setCurrent] = useState(1)
  const slotsRef = useRef<(HTMLDivElement | null)[]>([])
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError

  // 文档加载：共享 worker，卸载销毁文档
  useEffect(() => {
    let destroyed = false
    let task: ReturnType<typeof getDocument> | null = null
    ensureWorker()
    data
      .arrayBuffer()
      .then((buf) => {
        if (destroyed) return
        task = getDocument({
          data: new Uint8Array(buf),
          // CJK 字体的 CMap 与标准回退字体（public/pdfjs/，随 build 进 dist）：
          // 不提供时中文 PDF 文字直接画不出来（translateFont failed）
          cMapUrl: '/pdfjs/cmaps/',
          cMapPacked: true,
          standardFontDataUrl: '/pdfjs/standard_fonts/',
        })
        return task.promise
      })
      .then((doc) => {
        if (!doc) return
        if (destroyed) {
          void task?.destroy()
          return
        }
        setPdf(doc)
      })
      .catch((e: unknown) => {
        if (!destroyed) onErrorRef.current?.(e)
      })
    return () => {
      destroyed = true
      void task?.destroy()
    }
  }, [data])

  // fit 宽度：容器宽防抖 120ms（拖面板不狂重渲）
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    let timer: number | undefined
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setWidth(Math.max(0, Math.floor(w) - 24)), 120)
    })
    ro.observe(el)
    return () => {
      ro.disconnect()
      window.clearTimeout(timer)
    }
  }, [])

  const registerSlot = (n: number, el: HTMLDivElement | null) => {
    slotsRef.current[n - 1] = el
  }

  // 当前页指示：滚动时找覆盖视口 30% 高度线的最后一页（rAF 合并）
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const mid = el.scrollTop + el.clientHeight * 0.3
    let page = 1
    for (let i = 0; i < slotsRef.current.length; i++) {
      const slot = slotsRef.current[i]
      if (slot && slot.offsetTop <= mid) page = i + 1
    }
    setCurrent(page)
  }

  return (
    <div ref={scrollRef} className="pdf-preview-root" onScroll={onScroll}>
      {pdf && width > 0 && (
        <div className="pdf-page-indicator">
          {current} / {pdf.numPages}
        </div>
      )}
      {!pdf || width === 0 ? (
        <div className="pdf-preview-loading">加载文档…</div>
      ) : (
        Array.from({ length: pdf.numPages }, (_, i) => (
          <PdfPage key={i + 1} pdf={pdf} pageNumber={i + 1} width={width} registerSlot={registerSlot} />
        ))
      )}
    </div>
  )
}
