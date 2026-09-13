/**
 * pdf 版式预览渲染体（懒加载分包，经 React.lazy 引入）：pdfjs-dist 在浏览器
 * 本地渲染，文件不出本机。纯渲染组件——宿主负责取字节与失败兜底（onError 上抛）。
 *
 * 性能口径：逐页 canvas 双向懒渲染（进视口前约一屏才画；**滚出视口约 2000px 回收
 * 画布回占位、重进再画**——只加不减时几百页标书滚一遍就是 GB 级常驻，2026-09-13
 * 内存修复批）；渲染/回收阈值错开形成迟滞带，慢速滚动在回收边界不抖动。
 * fit 宽度缩放（面板拖宽经 ResizeObserver 防抖后整列重算重渲）；devicePixelRatio
 * 高清出图、封顶 1.5（单页背衬内存减半，正文文字锐度无感差异）。每实例独立
 * worker 线程，卸载即销毁。
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

/** 单页：双向懒可见 → 画布渲染/回收。占位用 A4 比例 aspect-ratio，渲染后画布
 *  自然替换，回收后回到占位（页高不变，页码指示与滚动位置不跳）。 */
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
  // 首两页直接渲染（进面板即有内容），其余进视口前 400px 再渲；离视口约 2000px 回收
  const [visible, setVisible] = useState(pageNumber <= 2)

  useEffect(() => {
    const el = slotRef.current
    if (!el) return
    // 渲染观察器：进视口（含 400px 前瞻）即渲染；已渲染时 setVisible(true) 是同值 no-op
    const renderIo = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setVisible(true)
      },
      { rootMargin: '400px 0px' },
    )
    // 回收观察器：离视口约 2000px 才回收（与渲染阈值错开成迟滞带，快速滚动不抖动）
    const recycleIo = new IntersectionObserver(
      (entries) => {
        if (entries.every((e) => !e.isIntersecting)) setVisible(false)
      },
      { rootMargin: '2000px 0px' },
    )
    renderIo.observe(el)
    recycleIo.observe(el)
    return () => {
      renderIo.disconnect()
      recycleIo.disconnect()
    }
  }, [])

  // 回收释放：visible 转 false 时清掉已挂画布回占位。单独成 effect 而不是塞进渲染
  // effect 的 cleanup——那条路宽度重渲也会走，清了会拖面板闪白；这里只跟 visible。
  useEffect(() => {
    if (visible) return
    slotRef.current?.replaceChildren()
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
      // dpr 封顶 1.5：单页背衬 ~14MB→~8MB，正文文字锐度无感差异（3GB 内存修复批）
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
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
