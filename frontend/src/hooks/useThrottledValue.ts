import { useEffect, useRef, useState } from 'react'

/**
 * 流式渲染节流：把高频更新（SSE token）合并为每 throttleMs 最多一次渲染提交。
 * 语义对齐 Vercel Streamdown 的 useThrottledDebounce：
 * - leading：距上次提交 ≥ throttleMs 时立即生效（首字不延迟）；
 * - trailing：否则安排 debounceMs 后补一次（持续流末尾不丢字——连续 token 会不断
 *   清掉补发定时器，直到出现 ≥throttleMs 间隔或流结束后的静默窗口）。
 * 只节流渲染层：状态层（runReducer/useRun）仍存精确值，run 收敛时消息拉回替换
 * 流式气泡，≤throttleMs+debounceMs 的尾巴不可感知。
 */
export function useThrottledValue<T>(value: T, throttleMs = 200, debounceMs = 50): T {
  const [displayed, setDisplayed] = useState(value)
  const lastRunAtRef = useRef(0)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (Date.now() - lastRunAtRef.current >= throttleMs) {
      setDisplayed(value)
      lastRunAtRef.current = Date.now()
      return
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      setDisplayed(value)
      lastRunAtRef.current = Date.now()
    }, debounceMs)
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [value, throttleMs, debounceMs])

  return displayed
}
