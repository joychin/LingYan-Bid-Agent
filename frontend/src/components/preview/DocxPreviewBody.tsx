/**
 * docx 版式预览渲染体（懒加载分包，经 React.lazy 引入）：docx-preview 在浏览器
 * 本地渲染 OOXML，文件不出本机。纯渲染组件——宿主负责取字节
 * （fetchWorkbenchRaw / fetchSourceRaw）与失败兜底（onError 上抛，DocxView 落回
 * 文本视图）。
 *
 * 修订标记（w:ins/w:del）的呈现以 docx-preview 实际行为为准，审阅修订仍在 Word
 * （宿主的「在文件夹中显示」）；breakPages 按分页符出纸面。
 *
 * 渲染调度：每次渲染写入自己的子容器 host，resolve 时整体换装上屏。cancelled
 * 拦不住库里已在飞的渲染继续写 DOM（整本几十 MB 解析数秒），若新旧两次直接打
 * 同一容器，后完成的旧渲染会把活渲染刚画好的内容整体清掉（StrictMode 双跑、
 * 宿主换数据重取字节都会双跑）——子容器互相隔离后旧渲染只能清掉自己。
 */
import { useEffect, useRef, useState } from 'react'
import { renderAsync } from 'docx-preview'

export default function DocxPreviewBody({
  data,
  onError,
}: {
  data: Blob
  onError?: (e: unknown) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  // ref 存回调：宿主不必 useCallback，不稳定引用也不会触发整篇重渲染
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  // 渲染中提示延迟出现：小节文件百毫秒级不出提示防闪烁，整本数秒空白不再像卡死
  const [slowRender, setSlowRender] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let cancelled = false
    setSlowRender(false)
    const slowTimer = window.setTimeout(() => {
      if (!cancelled) setSlowRender(true)
    }, 400)
    const host = document.createElement('div')
    el.appendChild(host)
    renderAsync(data, host, undefined, {
      inWrapper: true,
      breakPages: true,
      experimental: true,
      useBase64URL: true,
      renderComments: true, // 待办批注高亮可见（docx_comment_add 落的缺口标记）
    })
      .then(() => {
        if (cancelled) {
          // 渲染中切走/卸载：摘掉自己的子树（含 base64 图片），别把孤立大 DOM
          // 留给 GC 慢慢发现（内存修复批的诉求，host 化后不再误清活渲染）
          host.remove()
          return
        }
        window.clearTimeout(slowTimer)
        setSlowRender(false)
        // 换装：移除旧数据/上一轮遗留的内容，只留本次；换数据重解析期间旧内容
        // 保持可见，上屏瞬间才替换
        el.replaceChildren(host)
      })
      .catch((e: unknown) => {
        host.remove()
        window.clearTimeout(slowTimer)
        if (!cancelled) {
          setSlowRender(false)
          onErrorRef.current?.(e)
        }
      })
    return () => {
      cancelled = true
      window.clearTimeout(slowTimer)
    }
  }, [data])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {slowRender && (
        <div className="shrink-0 px-4 py-2 text-xs text-muted-foreground">正在渲染版式…</div>
      )}
      <div ref={ref} className="docx-preview-root" />
    </div>
  )
}
