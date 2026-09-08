/**
 * docx 版式预览渲染体（懒加载分包，经 React.lazy 引入）：docx-preview 在浏览器
 * 本地渲染 OOXML，文件不出本机。纯渲染组件——宿主负责取字节
 * （fetchWorkbenchRaw / fetchSourceRaw）与失败兜底（onError 上抛，DocxView 落回
 * 文本视图）。
 *
 * 修订标记（w:ins/w:del）的呈现以 docx-preview 实际行为为准，审阅修订仍在 Word
 * （宿主的「在文件夹中显示」）；breakPages 按分页符出纸面。
 */
import { useEffect, useRef } from 'react'
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

  useEffect(() => {
    const el = ref.current
    if (!el) return
    let cancelled = false
    el.innerHTML = ''
    renderAsync(data, el, undefined, {
      inWrapper: true,
      breakPages: true,
      experimental: true,
      useBase64URL: true,
    }).catch((e: unknown) => {
      if (!cancelled) onErrorRef.current?.(e)
    })
    return () => {
      cancelled = true
      el.innerHTML = ''
    }
  }, [data])

  return <div ref={ref} className="docx-preview-root" />
}
