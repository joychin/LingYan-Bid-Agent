import { useEffect, useState } from 'react'

/** 搜索防抖（每次击键打后端 FTS 太密；原 MaterialsLibraryView 局部 hook，2026-09-17 批次⑦提为共享）。 */
export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}
