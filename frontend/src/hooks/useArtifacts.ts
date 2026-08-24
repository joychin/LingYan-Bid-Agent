import { useQuery } from '@tanstack/react-query'
import { getArtifactContent, listArtifacts } from '@/api/client'

export function useArtifacts() {
  return useQuery({
    queryKey: ['artifacts'],
    queryFn: async () => (await listArtifacts()).artifacts,
  })
}

export function useArtifactContent(id: string | null) {
  return useQuery({
    queryKey: ['artifacts', id, 'content'],
    queryFn: async () => getArtifactContent(id as string),
    enabled: !!id,
  })
}
