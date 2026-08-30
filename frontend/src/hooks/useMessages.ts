import { useQuery } from '@tanstack/react-query'
import { listMessages } from '@/api/client'

export function useMessages(convId: string | null) {
  return useQuery({
    queryKey: ['messages', convId],
    queryFn: async () => (await listMessages(convId!)).messages,
    enabled: !!convId,
    // 快速失败：默认 retry 3 次×15s 请求超时 ≈63s 骨架屏；1 次重试 ≈31s 进入可见错误态。
    // refetchOnWindowFocus 仅此查询开启（全局已关）：页面隐藏期间挂起/死掉的请求，
    // 切回窗口时自动重拉自愈（messages 是毫秒级小请求，代价可忽略）
    retry: 1,
    refetchOnWindowFocus: true,
  })
}
