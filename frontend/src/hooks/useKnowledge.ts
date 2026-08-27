import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmKbMetadata,
  deleteKbItem,
  getKbBadge,
  getKbItemContent,
  listKbItems,
  listKbTypes,
  retriggerKbItem,
  type KbItem,
} from '@/api/client'

/** 条目列表：有解析中条目时 5s 轮询收敛（后台 fire-and-forget 入库），落定后停。 */
export function useKbItems() {
  return useQuery({
    queryKey: ['kb', 'items'],
    queryFn: () => listKbItems(),
    refetchInterval: (query) => {
      const busy = (query.state.data?.items ?? []).some(
        (it) => it.parse_status === 'parsing' || it.parse_status === 'pending' || it.extract_status === 'running',
      )
      return busy ? 5_000 : false
    },
  })
}

/** 侧栏红点：待确认计数，60s 轮询（后台抽取完成后红点自动出现）。 */
export function useKbBadge() {
  return useQuery({
    queryKey: ['kb', 'badge'],
    queryFn: getKbBadge,
    refetchInterval: 60_000,
  })
}

export function useKbTypes() {
  return useQuery({
    queryKey: ['kb', 'types'],
    queryFn: listKbTypes,
    staleTime: Infinity,
  })
}

export function useKbContent(id: string | null) {
  return useQuery({
    queryKey: ['kb', 'content', id],
    queryFn: () => getKbItemContent(id!),
    enabled: Boolean(id),
  })
}

/** 列表/徽标级失效：不碰 content 查询——删除条目后重取已删 id 会 404。 */
function useInvalidateKb() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ['kb', 'items'] })
    void qc.invalidateQueries({ queryKey: ['kb', 'badge'] })
  }
}

export function useConfirmMetadata() {
  const invalidate = useInvalidateKb()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof confirmKbMetadata>[1] }) =>
      confirmKbMetadata(id, body),
    onSuccess: invalidate,
  })
}

export function useRetriggerKbItem() {
  const invalidate = useInvalidateKb()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => retriggerKbItem(id),
    onSuccess: (_data, id) => {
      invalidate()
      // 重跑后解析内容已变，该条目的 content 查询一并失效
      void qc.invalidateQueries({ queryKey: ['kb', 'content', id] })
    },
  })
}

export function useDeleteKbItem() {
  const invalidate = useInvalidateKb()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteKbItem(id),
    onSuccess: (_data, id) => {
      invalidate()
      // 精准清缓存而非失效（失效会重取已删条目 → 404）
      qc.removeQueries({ queryKey: ['kb', 'content', id] })
    },
  })
}

/** 待确认条目（红点文案与筛选用）。 */
export function pendingCount(items: KbItem[] | undefined): number {
  return (items ?? []).filter((it) => it.review_status === 'pending_review').length
}
