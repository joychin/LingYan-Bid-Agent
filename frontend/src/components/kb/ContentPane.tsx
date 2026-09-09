/**
 * 详情内容 tab：文本（默认）/ 原件 双模式。
 * - 文本 = 资料档案卡（AI 整理）+ 解析警告 + 截断正文 + 文档图片折叠区
 * - 原件 = pdf/docx 版式预览、.doc 提示另存（解析失败也能看原件，
 *   正是「回原文核对」的场景）；图片条目无切换、维持内联大图。
 */
import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Copy } from 'lucide-react'
import { fetchKbItemBlob, fetchKbItemRaw, type KbItem, type KbParseMeta, type KbTypePayload } from '@/api/client'
import { mdRemarkPlugins } from '@/lib/markdown'
import { markdownComponents } from '@/components/ai/MemoMarkdown'
import { KbImage } from '@/components/KbImage'
import { Loader } from '@/components/ai/Loader'
import { isBusy, statusText, WarnLine } from './kbShared'
import { ArchiveCard } from './ArchiveCard'
import { OriginalView, originalPreviewable } from '@/components/preview/OriginalView'

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp'])

const TRUNCATE_CHARS = 8000

function MarkdownPreview({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
  const clean = content.replace(/<!--[\s\S]*?-->/g, '')
  const isTruncated = clean.length > TRUNCATE_CHARS
  let shown = clean
  if (isTruncated && !expanded) {
    const cut = clean.lastIndexOf('\n\n', TRUNCATE_CHARS)
    shown = cut > TRUNCATE_CHARS * 0.6 ? clean.slice(0, cut) : clean.slice(0, TRUNCATE_CHARS)
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied('ok')
    } catch {
      setCopied('fail')
    }
    window.setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div>
      <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={markdownComponents}>
        {shown}
      </ReactMarkdown>
      {isTruncated && (
        <div className="kb-md-tail">
          <span className="kb-md-count">
            {expanded ? '全文' : '已截断，共'} {clean.length.toLocaleString()} 字符
          </span>
          <button type="button" className="kb-md-action" onClick={() => setExpanded((v) => !v)}>
            {expanded ? '收起' : '查看完整内容'}
          </button>
          <button type="button" className="kb-md-action" onClick={() => void copy()}>
            <Copy className="h-3 w-3" />
            {copied === 'ok' ? '已复制' : copied === 'fail' ? '复制失败' : '复制全文'}
          </button>
        </div>
      )}
    </div>
  )
}

export function ContentPane({
  item,
  types,
  meta,
  content,
  contentLoading,
  images,
  onEditInfo,
}: {
  item: KbItem
  types: KbTypePayload[]
  meta?: KbParseMeta | null
  content?: string
  contentLoading: boolean
  images: { name: string; size: number }[]
  onEditInfo: () => void
}) {
  const [mode, setMode] = useState<'text' | 'original'>('text')
  const isImage = IMAGE_EXTS.has(item.ext.toLowerCase())
  const previewable = !isImage && originalPreviewable(item.ext)
  const busy = isBusy(item)
  const [imgUrl, setImgUrl] = useState<string | null>(null)

  useEffect(() => {
    setImgUrl(null)
    // 局部变量而非 state 读值：cleanup 闭包共享本变量，revoke 到的是 fetch 完成后的
    // 真实 URL（读 state 的旧闭包恒拿到 null，objectURL 从不被释放——每看一张图泄一张）
    let url: string | null = null
    if (isImage && item.md_ready === false) {
      void fetchKbItemRaw(item.id)
        .then((u) => {
          url = u
          setImgUrl(u)
        })
        .catch(() => setImgUrl(null))
    }
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [item.id]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="kb-pane">
      {previewable && (
        <div className="kb-pane-bar">
          <div className="kb-seg">
            <button
              type="button"
              className={mode === 'text' ? 'kb-seg-btn kb-seg-btn--active' : 'kb-seg-btn'}
              onClick={() => setMode('text')}
            >
              文本
            </button>
            <button
              type="button"
              className={mode === 'original' ? 'kb-seg-btn kb-seg-btn--active' : 'kb-seg-btn'}
              onClick={() => setMode('original')}
            >
              原件
            </button>
          </div>
        </div>
      )}
      {previewable && mode === 'original' ? (
        <OriginalView
          key={item.id}
          source={{
            id: item.id,
            ext: item.ext,
            fetchBlob: fetchKbItemBlob,
            queryKey: ['kb', 'raw', item.id],
            failHint: '版式渲染失败——完整原件请在数据目录的 knowledge/ 下打开',
          }}
        />
      ) : (
        <div className="kb-content">
          {meta?.warnings.map((w) => <WarnLine key={w}>{w}</WarnLine>)}
          <ArchiveCard item={item} types={types} onEditInfo={onEditInfo} />
          {isImage && imgUrl ? (
            <img src={imgUrl} alt={item.file_name} className="kb-image" />
          ) : content ? (
            <MarkdownPreview content={content} />
          ) : contentLoading || busy ? (
            <div className="kb-pane-empty">
              <Loader variant="classic" size="md" tone="muted" />
              <p>{statusText(item)}</p>
            </div>
          ) : (
            <div className="kb-pane-empty">
              <p>无文本内容</p>
              <p className="text-xs text-muted-foreground">
                {isImage
                  ? '图片原件可切「信息」页确认识别结果，或配置支持图片输入的模型后点「重新识别」'
                  : '可点「重新识别」重试'}
              </p>
            </div>
          )}
          {images.length > 0 && (
            <details className="kb-images-fold">
              <summary>本文档图片 {images.length} 张（证书扫描/架构图等，仅供查看）</summary>
              <div className="kb-images-grid">
                {images.map((img) => (
                  <KbImage key={img.name} itemId={item.id} imagePath={img.name} alt={img.name} />
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
