/**
 * 版式库：版式文件管理（格式资产，与素材=内容资产分离，2026-09-08 拆库拍板）。
 * 内置基准 + 用户上传 .docx；全局一个「默认版式」（2026-09-08 用户定名，原
 * 「设为当前/当前生效」）：设为默认后新建节与合册即用新版式，改动即时无重启。
 * 定名沿革：2026-09-09 用户拍板「模板库」改名「版式库」（模板二字三义歧义：
 * 版式资产/招标格式件/旧标书，界面一律用「版式」；代码标识符保留 templates）。
 * 右栏按钮恒显示（选中项即默认时禁用态「已是默认」——按钮只出现在非默认项上
 * 会让默认项无任何入口，用户点名缺陷）。「应用到任务」换装已于 2026-09-08
 * 整链移除（用户拍板没有业务意义）——版式只管新节外观，已写内容不动。
 */
import { lazy, Suspense, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileText, Trash2, Upload } from 'lucide-react'
import {
  activateTemplate,
  deleteTemplate,
  fetchTemplateRaw,
  listTemplates,
  uploadTemplate,
} from '@/api/client'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ai/Loader'
import { useToast } from '@/context/Toast'
import { cn, downloadBlob, formatRelativeTime } from '@/lib/utils'

const DocxPreviewBody = lazy(() => import('./preview/DocxPreviewBody'))

const BUILTIN_KEY = '__builtin__'

function sizeStr(n: number): string {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
}

export function TemplatesView() {
  const { toast } = useToast()
  const qc = useQueryClient()
  const [selectedKey, setSelectedKey] = useState<string | null>(BUILTIN_KEY)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [previewError, setPreviewError] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const list = useQuery({ queryKey: ['templates'], queryFn: listTemplates })
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
      toast(`已上传「${info.name}」，点「设为默认版式」后生效`, 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const actMut = useMutation({
    mutationFn: activateTemplate,
    onSuccess: () => {
      invalidate()
      toast('已设为默认版式：之后新建的正文节与合册即用此版式', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
  const delMut = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: (_r, key) => {
      invalidate()
      if (selectedKey === key) setSelectedKey(BUILTIN_KEY)
      setConfirmDelete(null)
      toast('版式已删除', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  // 下载版式文件副本到本机（拉当前字节，不走 5min 预览缓存——同名覆盖后下载要拿到新版）
  const download = async () => {
    if (!selected || downloading) return
    setDownloading(true)
    try {
      downloadBlob(`${selected.name}.docx`, await fetchTemplateRaw(selected.key))
    } catch {
      toast('下载失败，请重试', 'error')
    } finally {
      setDownloading(false)
    }
  }

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

      {/* 左栏：版式列表 */}
      <aside className="kb-side">
        <div className="kb-side-head" data-tauri-drag-region>
          <span className="kb-title" data-tauri-drag-region>版式库</span>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
          <p className="px-2 pb-1 text-xs leading-5 text-muted-foreground">
            版式决定新章节的外观（样式/页面/页眉页脚）；版式文件里的示例内容不会进入正文。可上传公司的 Word 版式文件（仅支持 DOCX 格式）。
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
                      默认
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
              「默认」=新建节与合册实际使用的版式；换默认版式只影响之后
              新建的节，已写内容不变。
            </p>
          )}
        </div>

        {/* 上传入口与知识库/写作素材库同款：列表底部通栏主按钮 + 格式提示 */}
        <div className="kb-side-foot">
          <Button size="sm" className="kb-upload-btn" disabled={upMut.isPending} onClick={() => fileInput.current?.click()}>
            {upMut.isPending ? <Loader variant="classic" size="sm" /> : <Upload className="h-3.5 w-3.5" />}
            上传文件
          </Button>
          <div className="kb-foot-hint">仅支持 .docx（Word 版式文件），单个不超过 20MB</div>
        </div>
      </aside>

      {/* 右栏：预览 + 操作 */}
      <section className="flex min-w-0 flex-1 flex-col">
        {selected ? (
          <>
            <div className="flex items-center gap-2 border-b px-4 py-2.5">
              <span className="truncate text-sm font-medium">{selected.name}</span>
              <Button
                variant="outline"
                size="sm"
                className="flex-none"
                disabled={selected.active || actMut.isPending}
                title={selected.active ? '此版式已是默认版式' : '设为默认后，之后新建的正文节与合册即用此版式'}
                onClick={() => actMut.mutate(selected.key)}
              >
                {selected.active ? '已是默认' : '设为默认版式'}
              </Button>
              <div className="flex-1" />
              <Button
                variant="ghost"
                size="sm"
                className="flex-none"
                disabled={downloading}
                title="下载版式文件到本机"
                onClick={download}
              >
                {downloading ? <Loader variant="classic" size="sm" /> : <Download className="h-4 w-4" />}
                {downloading ? '下载中…' : '下载'}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className={cn('flex-none', confirmDelete === selected.key && 'text-destructive')}
                disabled={selected.builtin || delMut.isPending}
                title={selected.builtin ? '内置版式不可删除' : undefined}
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
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto bg-background p-6">
              {raw.isLoading && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader variant="classic" size="sm" /> 加载预览…
                </div>
              )}
              {raw.isError && (
                <p className="text-xs text-muted-foreground">版式文件拉取失败，请重试或重新上传。</p>
              )}
              {raw.data && previewError && (
                <p className="text-xs text-muted-foreground">
                  浏览器内预览渲染失败（版式较复杂时可能发生）；内容不受影响，
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
            选择左侧版式查看预览
          </div>
        )}
      </section>
    </div>
  )
}
