import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmKbMetadata,
  createMtBlock,
  deleteKbItem,
  deleteMtBlock,
  deleteMtFile,
  getKbBadge,
  getKbItemContent,
  getKbItemImages,
  getMtBlockContent,
  getMtFileContent,
  getMtOutline,
  listKbItems,
  listKbTypes,
  listMtBlocks,
  listMtFiles,
  retriggerKbItem,
  updateMtBlock,
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

/** 本文档图片清单（内容页折叠区）。 */
export function useKbItemImages(id: string | null) {
  return useQuery({
    queryKey: ['kb', 'images', id],
    queryFn: () => getKbItemImages(id!),
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
      // 原件字节同样可能变化（同名覆盖语义不存在，但保险起见随重跑失效）
      void qc.invalidateQueries({ queryKey: ['kb', 'raw', id] })
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

// ===== 写作素材库（用户手工构建） =====

/** 素材文件列表：解析中 5s 轮询收敛。 */
export function useMtFiles() {
  return useQuery({
    queryKey: ['mt', 'files'],
    queryFn: () => listMtFiles(),
    refetchInterval: (query) => {
      const busy = (query.state.data?.files ?? []).some(
        (f) => f.parse_status === 'pending' || f.parse_status === 'parsing',
      )
      return busy ? 5_000 : false
    },
  })
}

/** 全部素材块（块列表视图；q 非空走服务端——正文 FTS ∪ 标题/备注匹配）。 */
export function useMtBlocks(q?: string) {
  return useQuery({
    queryKey: ['mt', 'blocks', q ?? ''],
    queryFn: () => listMtBlocks(q),
  })
}

/** 目录树（挑章节视图）。 */
export function useMtOutline(fileId: string | null) {
  return useQuery({
    queryKey: ['mt', 'outline', fileId],
    queryFn: () => getMtOutline(fileId!),
    enabled: Boolean(fileId),
  })
}

/** 块内容（预览用，展开时才拉）。 */
export function useMtBlockContent(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['mt', 'block-content', id],
    queryFn: () => getMtBlockContent(id!),
    enabled: Boolean(id) && enabled,
    staleTime: 60_000,
  })
}

/** 文件片段内容（挑章节点节点实时预览；staleTime 长——解析产物不变）。 */
export function useMtFileContent(fileId: string | null, start: number, end: number) {
  return useQuery({
    queryKey: ['mt', 'file-content', fileId, start, end],
    queryFn: () => getMtFileContent(fileId!, start, end),
    enabled: Boolean(fileId) && start > 0 && end >= start,
    staleTime: 5 * 60_000,
  })
}

function useInvalidateMt() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ['mt'] })
  }
}

export function useCreateMtBlock() {
  const invalidate = useInvalidateMt()
  return useMutation({
    mutationFn: ({ fileId, body }: { fileId: string; body: Parameters<typeof createMtBlock>[1] }) =>
      createMtBlock(fileId, body),
    onSuccess: invalidate,
  })
}

export function useUpdateMtBlock() {
  const invalidate = useInvalidateMt()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof updateMtBlock>[1] }) =>
      updateMtBlock(id, body),
    onSuccess: invalidate,
  })
}

export function useDeleteMtBlock() {
  const invalidate = useInvalidateMt()
  return useMutation({
    mutationFn: (id: string) => deleteMtBlock(id),
    onSuccess: invalidate,
  })
}

export function useDeleteMtFile() {
  const invalidate = useInvalidateMt()
  return useMutation({
    mutationFn: (id: string) => deleteMtFile(id),
    onSuccess: invalidate,
  })
}
