import { useQuery } from '@tanstack/react-query'
import { fetchActiveRuns } from '@/api/client'

/** 占用中的 run（running/waiting_input）轮询：侧栏跨会话「输出中」指示 + 任务级
 *  「等待确认」聚合的数据源。run 生命周期没有全局广播通道（SSE 按会话建连，全局
 *  长连接有连接预算前科），轻端点 3s 轮询是最简可靠路径；发送/续跑后 useRun 会
 *  主动失效一次，亮灯不等轮询周期。 */
export function useActiveRuns() {
  return useQuery({
    queryKey: ['runs', 'active'],
    queryFn: fetchActiveRuns,
    refetchInterval: 3000,
    select: (d) => d.runs,
  })
}
