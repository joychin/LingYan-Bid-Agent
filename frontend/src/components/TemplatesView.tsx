/**
 * 模板库：文档模板管理（格式资产，与素材=内容资产分离，2026-09-08 拆库拍板）。
 * 内置基准 + 用户上传 .docx；上传=入库、显式「设为当前」生效（之后新建节与
 * 合册即用新版式，改动即时无重启）；「应用到任务」=把当前生效模板换装到
 * 已有正文节（重建式，旧版自动入恢复点可反悔；「整本-」派生物跳过）。
 */
import { lazy, Suspense, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FileText, Trash2, Upload, Wand2 } from 'lucide-react'
import type { RestyleReport, Task } from '@/api/client'
import {
  activateTemplate,
  applyTemplate,
  deleteTemplate,
  fetchTemplateRaw,
  listTemplates,
  uploadTemplate,
} from '@/api/client'
import { useTasks } from '@/hooks/useTasks'
import { Button } from '@/components/ui/button'
import { ModalShell } from '@/components/ui/ModalShell'
import { Loader } from '@/components/ai/Loader'
import { useToast } from '@/context/Toast'
import { cn, formatRelativeTime } from '@/lib/utils'

const DocxPreviewBody = lazy(() => import('./preview/DocxPreviewBody'))

const BUILTIN_KEY = '__builtin__'

function sizeStr(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

/** 应用到任务弹窗（作用于当前生效模板）。 */
function ApplyDialog({
  tasks,
  busy,
  onClose,
  onApply,
}: {
  tasks: Task[]
  busy: boolean
  onClose: () => void
  onApply: (taskId: string) => void
}) {
  const [tid, setTid] = useState<string | null>(null)
  return (
    <ModalShell onClose={onClose} cardClassName="max-w-md">
      <div className="flex flex-col gap-3 p-5">
        <div>
          <h3 className="text-sm font-semibold">应用到任务</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            把当前生效模板换装到任务已有正文节（新版式即刻生效，每节旧版自动存
            恢复点可反悔；「整本」文件是派生物会跳过，需要时重新合册）。
          </p>
        </div>
        <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
          {tasks.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">还没有任务</p>
          )}
          {tasks.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTid(t.id)}
              className={cn(
                'flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm',
                tid === t.id ? 'bg-accent-soft text-primary' : 'hover:bg-secondary',
              )}
            >
              <span className="flex h-4 w-4 flex-none items-center justify-center">
                {tid === t.id && <Check className="h-3.5 w-3.5 text-primary" />}
              </span>
              <span className="truncate">{t.title}</span>
            </button>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" disabled={!tid || busy} onClick={() => tid && onApply(tid)}>
            {busy ? '换装中…' : '应用'}
          </Button>
        </div>
      </div>
    </ModalShell>
  )
}

export function TemplatesView() {
  const { toast } = useToast()
  const qc = useQueryClient()
  const [selectedKey, setSelectedKey] = useState<string | null>(BUILTIN_KEY)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [applyOpen, setApplyOpen] = useState(false)
  const [previewError, setPreviewError] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const list = useQuery({ queryKey: ['templates'], queryFn: listTemplates })
  // 复用全局 ['tasks'] 缓存（useTasks 的 queryFn 返回 Task[]——同 key 不同
  // queryFn 会互相污染缓存形状，Sidebar 任务树会拿到错误形状）
  const tasksQuery = useTasks()
  const selected =
    list.data?.find((t) => t.key === selectedKey) ?? list.data?.[0] ?? null

  const raw = useQuery({
    queryKey: ['template-raw', selected?.key],
    queryFn: () => fetchTemplateRaw(selected!.key),
    enabled: !!selected,
    staleTime: 5 * 60_000,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['templates'] })
    // 预览字节随文件变（同名覆盖上传/删除后重开）：一并失效防旧缓存
    void qc.invalidateQueries({ queryKey: ['template-raw'] })
  }

  const upMut = useMutation({
    mutationFn: uploadTemplate,
    onSuccess: (info) => {
      invalidate()
      setSelectedKey(info.key)
      toast(`已上传「${info.name}」，点「设为当前」后生效`, 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const actMut = useMutation({
    mutationFn: activateTemplate,
    onSuccess: () => {
      invalidate()
      toast('已设为当前模板：之后新建的正文节即用此版式', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const delMut = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: (_r, key) => {
      invalidate()
      if (selectedKey === key) setSelectedKey(BUILTIN_KEY)
      setConfirmDelete(null)
      toast('模板已删除', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const applyMut = useMutation({
    mutationFn: applyTemplate,
    onSuccess: (rep: RestyleReport) => {
      setApplyOpen(false)
      const parts = [`已换装 ${rep.applied} 节`]
      if (rep.failed) parts.push(`失败 ${rep.failed} 节`)
      if (rep.skipped_volumes) parts.push(`整本 ${rep.skipped_volumes} 册跳过（重新合册即可）`)
      toast(`${parts.join('，')}；原版已存恢复点`, rep.failed ? 'error' : 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  return (
    <div className="kb-view">
      <input
        ref={fileInput}
        type="file"
        hidden
        accept=".docx"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) upMut.mutate(f)
          e.target.value = ''
        }}
      />

      {/* 左栏：模板列表 */}
      <aside className="kb-side">
        <div className="kb-side-head" data-tauri-drag-region>
          <span className="kb-title" data-tauri-drag-region>
            模板库
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => fileInput.current?.click()}
            disabled={upMut.isPending}
          >
            {upMut.isPending ? <Loader variant="classic" size="sm" /> : <Upload className="h-4 w-4" />}
            上传
          </Button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
          <p className="px-2 pb-1 text-xs leading-5 text-muted-foreground">
            模板决定新章节的版式（样式/页面/页眉页脚）；模板文件里的示例内容不会进入正文。可上传公司的 Word 模板（仅支持 DOCX 格式）。
          </p>
          {list.isLoading && (
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
              <Loader variant="classic" size="sm" /> 加载中…
            </div>
          )}
          {list.data?.map((t) => (
            <div
              key={t.key}
              role="button"
              tabIndex={0}
              onClick={() => {
                setSelectedKey(t.key)
                setPreviewError(false)
                setConfirmDelete(null)
              }}
              onKeyDown={(e) => e.key === 'Enter' && setSelectedKey(t.key)}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm',
                selected?.key === t.key ? 'bg-secondary' : 'hover:bg-secondary/60',
              )}
            >
              <FileText className="h-4 w-4 flex-none text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate">{t.name}</span>
                  {t.builtin && (
                    <span className="flex-none rounded bg-secondary px-1.5 py-px text-[10px] text-muted-foreground">
                      内置
                    </span>
                  )}
                  {t.active && (
                    <span className="flex-none rounded bg-accent-soft px-1.5 py-px text-[10px] text-primary">
                      当前
                    </span>
                  )}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {formatRelativeTime(new Date((t.mtime ?? 0) * 1000).toISOString())} ·{' '}
                  {sizeStr(t.size ?? 0)}
                </div>
              </div>
            </div>
          ))}
          {list.data && list.data.length > 1 && (
            <p className="px-2 pt-2 text-xs leading-5 text-muted-foreground">
              「当前」=新建节与合册实际使用的模板；换模板不影响已写内容，
              需要时用「应用到任务」换装。
            </p>
          )}
        </div>
      </aside>

      {/* 右栏：预览 + 操作 */}
      <section className="flex min-w-0 flex-1 flex-col">
        {selected ? (
          <>
            <div className="flex items-center gap-2 border-b px-4 py-2.5">
              <span className="truncate text-sm font-medium">{selected.name}</span>
              {selected.active ? (
                <span className="flex-none rounded bg-accent-soft px-2 py-0.5 text-xs text-primary">
                  当前生效
                </span>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-none"
                  disabled={actMut.isPending}
                  onClick={() => actMut.mutate(selected.key)}
                >
                  设为当前
                </Button>
              )}
              <div className="flex-1" />
              <Button
                variant="ghost"
                size="sm"
                className="flex-none"
                title="把当前生效模板换装到任务已有正文节"
                onClick={() => setApplyOpen(true)}
              >
                <Wand2 className="h-4 w-4" />
                应用到任务…
              </Button>
              {!selected.builtin && (
                <Button
                  variant="ghost"
                  size="sm"
                  className={cn('flex-none', confirmDelete === selected.key && 'text-destructive')}
                  disabled={delMut.isPending}
                  onClick={() => {
                    if (confirmDelete === selected.key) delMut.mutate(selected.key)
                    else {
                      setConfirmDelete(selected.key)
                      window.setTimeout(() => setConfirmDelete(null), 3000)
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                  {confirmDelete === selected.key ? '确认删除' : '删除'}
                </Button>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto bg-background p-6">
              {raw.isLoading && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader variant="classic" size="sm" /> 加载预览…
                </div>
              )}
              {raw.isError && (
                <p className="text-xs text-muted-foreground">模板拉取失败，请重试或重新上传。</p>
              )}
              {raw.data && previewError && (
                <p className="text-xs text-muted-foreground">
                  浏览器内预览渲染失败（模板样式较复杂时可能发生）；内容不受影响，
                  可上传后在 Word 中打开确认。
                </p>
              )}
              {raw.data && !previewError && (
                <div className="mx-auto max-w-[794px] rounded-lg border bg-background shadow-sm">
                  <Suspense
                    fallback={
                      <div className="p-4 text-xs text-muted-foreground">加载预览组件…</div>
                    }
                  >
                    <DocxPreviewBody data={raw.data} onError={() => setPreviewError(true)} />
                  </Suspense>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            选择左侧模板查看版式
          </div>
        )}
      </section>

      {applyOpen && (
        <ApplyDialog
          tasks={tasksQuery.data ?? []}
          busy={applyMut.isPending}
          onClose={() => setApplyOpen(false)}
          onApply={(tid) => applyMut.mutate(tid)}
        />
      )}
    </div>
  )
}
