import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createConversation,
  deleteConversation,
  listConversations,
  patchConversation,
} from '@/api/client'

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: async () => (await listConversations()).conversations,
  })
}

/** 会话必须归属任务（P4）：创建时带 task_id。 */
export function useCreateConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => createConversation(taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useRenameConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => patchConversation(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    },
  })
}
