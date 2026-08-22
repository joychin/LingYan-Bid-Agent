import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createConversation, listConversations } from '@/api/client'

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: async () => (await listConversations()).conversations,
  })
}

export function useCreateConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => createConversation(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}
