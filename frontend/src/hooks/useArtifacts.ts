import { useQuery } from '@tanstack/react-query'
import { getArtifactContent, listArtifacts } from '@/api/client'

/** 全量产物列表（打开器按 id 查行、聊天内产物过滤用）。 */
export function useArtifacts() {
  return useQuery({
    queryKey: ['artifacts', 'all'],
    queryFn: async () => (await listArtifacts()).artifacts,
  })
}

/** 任务全部产物（文件归任务、单一当前版本）。 */
export function useTaskArtifacts(taskId: string | null) {
  return useQuery({
    queryKey: ['artifacts', 'task', taskId],
    queryFn: async () => (await listArtifacts({ task_id: taskId as string })).artifacts,
    enabled: !!taskId,
  })
}

/** 会话产出的产物（provenance 来源过滤，用于「本会话」高亮）。 */
export function useConversationArtifacts(convId: string | null) {
  return useQuery({
    queryKey: ['artifacts', 'conv', convId],
    queryFn: async () => (await listArtifacts({ conversation_id: convId as string })).artifacts,
    enabled: !!convId,
  })
}

export function useArtifactContent(id: string | null) {
  return useQuery({
    queryKey: ['artifacts', id, 'content'],
    queryFn: async () => getArtifactContent(id as string),
    enabled: !!id,
  })
}
