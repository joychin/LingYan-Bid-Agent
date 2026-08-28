import { useQuery } from '@tanstack/react-query'
import { listWorkbench } from '@/api/client'

/** 任务工作台（out/ 的 md 过程产物）：任务级，无任务上下文时不查询。 */
export function useWorkbench(taskId: string | null | undefined) {
  return useQuery({
    queryKey: ['workbench', taskId ?? null],
    queryFn: async () => (await listWorkbench(taskId!)).files,
    enabled: !!taskId,
  })
}
