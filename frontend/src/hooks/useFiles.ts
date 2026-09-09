import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { deleteFile, listFiles, uploadFile } from '@/api/client'

/** 任务级文件区（§16）：当前任务的 files/；无任务上下文时不查询。 */
export function useFiles(taskId: string | null | undefined) {
  return useQuery({
    queryKey: ['files', taskId ?? null],
    queryFn: async () => (await listFiles(taskId!)).files,
    enabled: !!taskId,
  })
}

export function useUploadFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, taskId }: { file: File; taskId: string }) => uploadFile(file, taskId),
    onSuccess: (_data, { taskId }) => {
      queryClient.invalidateQueries({ queryKey: ['files', taskId] })
      // 同名重传=内容可能不同：预览字节缓存一并失效（staleTime Infinity 的配套）
      queryClient.invalidateQueries({ queryKey: ['source-raw', taskId] })
    },
  })
}

export function useDeleteFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, taskId }: { name: string; taskId: string }) => deleteFile(name, taskId),
    onSuccess: (_data, { taskId }) => {
      queryClient.invalidateQueries({ queryKey: ['files', taskId] })
      queryClient.invalidateQueries({ queryKey: ['source-raw', taskId] })
    },
  })
}
