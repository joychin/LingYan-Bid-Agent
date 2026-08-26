import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createTask, deleteTask, listTasks, patchTask } from '@/api/client'
import type { Conversation, Task } from '@/api/client'

export function useTasks() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: async () => (await listTasks()).tasks,
  })
}

export function useCreateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ title, withConversation = true }: { title: string; withConversation?: boolean }) =>
      createTask(title, withConversation),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useRenameTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => patchTask(id, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

/** 进度便签保存（任务白板，LLM 与用户共写同一份真值）。 */
export function useSaveTaskProgress() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => patchTask(id, { progress_note: note }),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      // 打开中的编辑器持有的任务信息也失效
      queryClient.invalidateQueries({ queryKey: ['task', vars.id] })
    },
  })
}

export function useDeleteTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    },
  })
}

/** 由会话列表推导「当前会话 → 所属任务」映射（侧栏分组与面板两层切换共用）。 */
export function taskOfConversation(tasks: Task[], conversations: Conversation[], convId: string | null): Task | null {
  if (!convId) return null
  const conv = conversations.find((c) => c.id === convId)
  if (!conv?.task_id) return null
  return tasks.find((t) => t.id === conv.task_id) ?? null
}
