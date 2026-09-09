/**
 * 详情头部：文件名 + 徽章行（类型 / 确认状态 / 时效）+ 元信息行
 * （识别档位 · 页数 · 字数；识别中显示进度），右侧 重新识别 / 删除（两步）。
 * 原 FreshnessBar / ParseMetaBar 的信息并入此处，详情区不再横幅堆叠。
 */
import { useEffect, useState } from 'react'
import { Download, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchKbItemBlob, type KbItem, type KbParseMeta } from '@/api/client'
import { useDeleteKbItem, useRetriggerKbItem } from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { cn, downloadBlob } from '@/lib/utils'
import { KbBadge, WARN_CONVERSIONS, isBusy, statusText } from './kbShared'

export function KbDetailHeader({
  item,
  meta,
  onBeforeDelete,
}: {
  item: KbItem
  meta?: KbParseMeta | null
  onBeforeDelete: () => void
}) {
  const retrigger = useRetriggerKbItem()
  const del = useDeleteKbItem()
  const { toast } = useToast()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const busy = isBusy(item)
  const parsing = item.parse_status === 'pending' || item.parse_status === 'parsing'
  const extracting = item.extract_status === 'running'

  // 原件副本下载：拉字节存本地文件（不动知识库本体；识别中原件可能正被替换，禁用）
  const download = async () => {
    setDownloading(true)
    try {
      downloadBlob(item.file_name, await fetchKbItemBlob(item.id))
    } catch (e) {
      toast(e instanceof Error ? e.message : '下载失败', 'error')
    } finally {
      setDownloading(false)
    }
  }

  useEffect(() => {
    if (!confirmDelete) return
    const t = window.setTimeout(() => setConfirmDelete(false), 3000)
    return () => window.clearTimeout(t)
  }, [confirmDelete])

  return (
    <header className="kb-detail-head">
      <div className="min-w-0">
        <div className="kb-detail-title">{item.file_name}</div>
        <div className="kb-badges">
          <KbBadge kind="brand">{item.doc_type_name}</KbBadge>
          {!busy && item.review_status === 'confirmed' && (
            <KbBadge
              kind="success"
              title={item.business?.confirmed_by === 'auto' ? '程序核对自动确认' : undefined}
            >
              {item.business?.confirmed_by === 'auto' ? '已确认 · 程序核对' : '已确认'}
            </KbBadge>
          )}
          {!busy && item.review_status === 'pending_review' && <KbBadge kind="warning">待确认</KbBadge>}
          {item.freshness?.map((f) => (
            <KbBadge key={f.kind} kind={f.kind === 'expired' ? 'danger' : 'warning'}>
              {f.label}
            </KbBadge>
          ))}
        </div>
        <div className="kb-detail-meta">
          {busy ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{statusText(item)}</span>
            </>
          ) : meta ? (
            <>
              <span className={cn(WARN_CONVERSIONS.has(meta.conversion) && 'text-warning')}>
                {meta.conversion_label}
              </span>
              {meta.pages != null && <span>{meta.pages} 页</span>}
              {meta.chars != null && <span>{meta.chars.toLocaleString()} 字</span>}
              {meta.tables != null && meta.tables > 0 && <span>{meta.tables} 个表格</span>}
            </>
          ) : (
            <span>{statusText(item)}</span>
          )}
        </div>
      </div>
      <div className="flex gap-1.5">
        {parsing ? (
          <span className="inline-flex items-center gap-1.5 self-center px-1 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            解析中…
          </span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className={item.parse_status === 'failed' ? 'text-error' : ''}
            disabled={extracting}
            title="重新解析与识别（覆盖建议信息，不动已确认内容）"
            onClick={() => {
              void retrigger
                .mutateAsync(item.id)
                .then(() => toast('已重新触发解析与识别', 'info'))
                .catch((e) => toast(e instanceof Error ? e.message : '重新识别失败', 'error'))
            }}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', retrigger.isPending && 'animate-spin')} />
            {retrigger.isPending ? '提交中…' : item.parse_status === 'failed' ? '重新解析' : '重新识别'}
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={downloading || busy}
          title="下载原件副本到本机"
          onClick={() => void download()}
        >
          <Download className="h-3.5 w-3.5" />
          {downloading ? '下载中…' : '下载'}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className={!confirmDelete ? 'text-error' : ''}
          onClick={() => {
            if (!confirmDelete) {
              setConfirmDelete(true)
              return
            }
            onBeforeDelete()
            void del.mutateAsync(item.id)
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
          {confirmDelete ? '确认删除？' : '删除'}
        </Button>
      </div>
    </header>
  )
}
