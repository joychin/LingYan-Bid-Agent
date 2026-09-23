/**
 * 知识库详情壳：头部（徽章/元信息/动作）→ 解析失败横幅 → 识别更新条 →
 * 「内容 / 信息」双 tab → 内容 pane（档案卡+解析文本+原件切换）或信息表单。
 * 纯装配层；信息语义在子组件。
 */
import { useEffect, useMemo, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { KbItem, KbTypePayload } from '@/api/client'
import { useKbContent, useKbItemImages } from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { KbDetailHeader } from './DetailHeader'
import { ContentPane } from './ContentPane'
import { InfoForm } from './InfoForm'
import { UpdateAdoption } from './UpdateAdoption'
import { computeKbDiff, diffSummary } from './kbDiff'
import { cn } from '@/lib/utils'

export type DetailTab = 'content' | 'info'

export function ItemDetail({
  item,
  types,
  tab,
  onTab,
  onBeforeDelete,
  onDirtyChange,
}: {
  item: KbItem
  types: KbTypePayload[]
  tab: DetailTab
  onTab: (t: DetailTab) => void
  onBeforeDelete: () => void
  onDirtyChange: (dirty: boolean) => void
}) {
  const { data: content, isLoading: contentLoading } = useKbContent(item.id)
  const { data: imagesData } = useKbItemImages(item.id)
  const qc = useQueryClient()
  const { toast } = useToast()
  const busy =
    item.parse_status === 'pending' ||
    item.parse_status === 'parsing' ||
    item.extract_status === 'running'
  const diff = useMemo(() => computeKbDiff(item, types), [item, types])

  // 识别跑完给个明确反馈——确认版优先展示，此前主视图纹丝不动，只能猜成没成
  const wasBusyRef = useRef(busy)
  useEffect(() => {
    if (wasBusyRef.current && !busy) {
      // 解析/抽取落定：失效该条目 content/images 缓存——解析进行中打开详情会把
      // 空文本缓存住，items 轮询收敛后旧空值永不刷新（「文本」视图显示无文本内容
      // 直到手刷页面，2026-09-23 自动化测试 X6）。parse 落定改 content、extract
      // 不改，统一失效只多一次 304 级 refetch，换时序鲁棒
      void qc.invalidateQueries({ queryKey: ['kb', 'content', item.id] })
      void qc.invalidateQueries({ queryKey: ['kb', 'images', item.id] })
      if (item.extract_status === 'done') {
        toast(diff ? `识别完成：${diffSummary(diff, types)}` : '识别完成', 'info')
      }
    }
    wasBusyRef.current = busy
  }, [busy]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="kb-detail">
      <KbDetailHeader item={item} meta={content?.meta} onBeforeDelete={onBeforeDelete} />

      {item.parse_status === 'failed' && <div className="kb-error-bar">解析失败：{item.error}</div>}
      <div className="kb-detail-body">
        <UpdateAdoption item={item} types={types} diff={diff} />
      </div>

      <nav className="kb-tabs">
        <button
          type="button"
          className={cn('kb-tab', tab === 'content' && 'kb-tab--active')}
          onClick={() => onTab('content')}
        >
          内容
        </button>
        <button
          type="button"
          className={cn('kb-tab', tab === 'info' && 'kb-tab--active')}
          onClick={() => onTab('info')}
        >
          信息{item.review_status === 'pending_review' && !busy ? '（待确认）' : ''}
        </button>
      </nav>

      {tab === 'content' ? (
        <ContentPane
          item={item}
          types={types}
          meta={content?.meta}
          content={content?.content}
          contentLoading={contentLoading}
          images={imagesData?.images ?? []}
          onEditInfo={() => onTab('info')}
        />
      ) : (
        <InfoForm item={item} types={types} onDirtyChange={onDirtyChange} />
      )}
    </div>
  )
}
