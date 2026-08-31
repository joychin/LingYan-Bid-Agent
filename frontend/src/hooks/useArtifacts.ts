import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { confirmArtifact, getArtifactContent, listArtifacts, unconfirmArtifact } from '@/api/client'
import { useToast } from '@/context/Toast'

/** 全量产物列表（打开器按 id 查行、聊天内产物过滤用）。 */
export function useArtifacts() {
  return useQuery({
    queryKey: ['artifacts', 'all'],
    queryFn: async () => (await listArtifacts()).artifacts,
  })
}

/** 任务全部产物（文件归任务：草稿 + 已确认）。 */
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

/** 确认盖戳（草稿→已确认）：带确认时所见 content_seq，后端不符返回 409（内容已被更新）。
 *  409 时同样刷新列表——卡片上的版本号和内容随后对齐最新，用户查看后可再次确认。 */
export function useConfirmArtifact() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: ({ id, seq }: { id: string; seq?: number }) => confirmArtifact(id, seq),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      // artifact 可为 null：锁释放后行被并发删除（删任务）——动作已成功，不追名
      toast(data.artifact ? `已确认「${data.artifact.display_name}」为正式成果` : '已确认为正式成果', 'success')
    },
    onError: (e) => {
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      toast(e instanceof Error ? e.message : String(e), 'error')
    },
  })
}

/** 撤销确认（已确认→草稿）。 */
export function useUnconfirmArtifact() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => unconfirmArtifact(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      toast(data.artifact ? `已撤销确认「${data.artifact.display_name}」，回到草稿` : '已撤销确认，回到草稿', 'success')
    },
    onError: (e) => {
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      toast(e instanceof Error ? e.message : String(e), 'error')
    },
  })
}
