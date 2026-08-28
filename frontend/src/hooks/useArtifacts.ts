import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getArtifactContent, listArtifacts, promoteArtifact } from '@/api/client'
import { useToast } from '@/context/Toast'

/** 全量产物列表（打开器按 id 查行、聊天内过程稿过滤用）。 */
export function useArtifacts() {
  return useQuery({
    queryKey: ['artifacts', 'all'],
    queryFn: async () => (await listArtifacts()).artifacts,
  })
}

/** 任务「正式稿」。 */
export function useTaskArtifacts(taskId: string | null) {
  return useQuery({
    queryKey: ['artifacts', 'task', taskId],
    queryFn: async () => (await listArtifacts({ task_id: taskId as string })).artifacts,
    enabled: !!taskId,
  })
}

/** 会话「过程稿」。 */
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

/** 过程稿转正（用户点头）：成功后刷新两层列表并提示。 */
export function usePromoteArtifact() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => promoteArtifact(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      toast(`已转正「${data.artifact.display_name}」到项目文件`, 'success')
    },
    onError: (e) => {
      toast(e instanceof Error ? e.message : String(e), 'error')
    },
  })
}
