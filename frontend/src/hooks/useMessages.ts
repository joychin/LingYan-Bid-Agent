import { useQuery } from '@tanstack/react-query'
import { listMessages } from '@/api/client'

export function useMessages(convId: string | null) {
  return useQuery({
    queryKey: ['messages', convId],
    queryFn: async () => (await listMessages(convId!)).messages,
    enabled: !!convId,
  })
}
