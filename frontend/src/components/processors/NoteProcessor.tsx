import { useEffect, useRef, useState } from 'react'
import type { ProcessorProps } from '@/artifacts/registry'
import { getArtifactContent, listArtifacts, restoreArtifact, updateArtifactContent } from '@/api/client'
import { useQueryClient } from '@tanstack/react-query'
import { markdownComponents } from '@/components/ChatMessage'
import { History, Loader2, Pencil, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface NoteData {
  title: string
  body_md: string
}

function parseNote(raw: string): NoteData {
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>
    return {
      title: typeof obj.title === 'string' ? obj.title : '',
      body_md: typeof obj.body_md === 'string' ? obj.body_md : '',
    }
  } catch {
    return { title: '', body_md: '' }
  }
}

/**
 * 通用笔记 Processor（doc.note/note-md@1）：markdown 文档查看 + 编辑。
 * 未注册类型的统一收拢形态——LLM 的中间结论/记忆以笔记保存，这里保证一定打得开、改得了。
 * 编辑走防抖自动保存 + content_seq 探测；409 时弹「拉取最新 / 保留我的」用户裁决
 * （与目录编辑器同一文件夹语义）。笔记不做 5s 轮询——保存撞上外部更新时 409 兜底。
 */
export function NoteProcessor({ artifact, content }: ProcessorProps) {
  const queryClient = useQueryClient()
  const initial = parseNote(content)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(initial.title)
  const [body, setBody] = useState(initial.body_md)
  const [seq, setSeq] = useState(artifact.content_seq)
  const [conflict, setConflict] = useState(false)
  const [saving, setSaving] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const dirty = useRef(false)
  const timer = useRef<number | null>(null)
  const latest = useRef({ title, body, seq })

  latest.current = { title, body, seq }

  const doSave = async (force = false) => {
    if (!artifact.editable) return
    setSaving(true)
    try {
      const res = await updateArtifactContent(
        artifact.artifact_id,
        {
          title: latest.current.title.trim() || artifact.display_name,
          body_md: latest.current.body,
        },
        latest.current.seq,
        force,
      )
      setSeq(res.content_seq)
      setConflict(false)
      dirty.current = false
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    } catch (e) {
      const err = e as Error & { status?: number }
      if (err.status === 409) {
        setConflict(true)
      } else {
        // 网络等异常：保留本地内容等下次改动重试（永不回滚用户输入）
      }
    } finally {
      setSaving(false)
    }
  }

  /** 拉取最新：换基底（丢弃本地未保存改动，进入冲突时用户已知情）。 */
  const adoptLatest = async () => {
    const fresh = await getArtifactContent(artifact.artifact_id)
    const note = parseNote(fresh.content)
    setTitle(note.title)
    setBody(note.body_md)
    const { artifacts } = await listArtifacts()
    const row = artifacts.find((a) => a.artifact_id === artifact.artifact_id)
    if (row) setSeq(row.content_seq)
    dirty.current = false
    setConflict(false)
  }

  const doRestore = async () => {
    setRestoring(true)
    try {
      await restoreArtifact(artifact.artifact_id)
      const fresh = await getArtifactContent(artifact.artifact_id)
      const note = parseNote(fresh.content)
      setTitle(note.title)
      setBody(note.body_md)
      const { artifacts } = await listArtifacts()
      const row = artifacts.find((a) => a.artifact_id === artifact.artifact_id)
      if (row) setSeq(row.content_seq)
      dirty.current = false
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    } finally {
      setRestoring(false)
    }
  }

  // 防抖自动保存（800ms）：改完即生效，无保存确认
  useEffect(() => {
    if (!editing) return
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      if (dirty.current) void doSave()
    }, 800)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, body, editing])

  // 关闭编辑/卸载时冲刷挂起保存；撞上外部更新按「主导权归用户」强制保留
  const flushPending = () => {
    if (!artifact.editable || !dirty.current) return
    void updateArtifactContent(
      artifact.artifact_id,
      {
        title: latest.current.title.trim() || artifact.display_name,
        body_md: latest.current.body,
      },
      latest.current.seq,
      true,
    ).catch(() => {})
    dirty.current = false
  }
  useEffect(() => flushPending, []) // eslint-disable-line react-hooks/exhaustive-deps

  const stopEditing = () => {
    if (timer.current) window.clearTimeout(timer.current)
    flushPending()
    setEditing(false)
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden p-4">
      <div className="flex items-center gap-2">
        {editing ? (
          <input
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              dirty.current = true
            }}
            placeholder="标题"
            className="w-full max-w-md rounded-md border border-line bg-card px-2 py-1 text-base font-semibold focus:border-primary focus:outline-none"
          />
        ) : (
          <h3 className="truncate text-base font-semibold">{title || artifact.display_name}</h3>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {saving ? '保存中…' : editing ? '自动保存' : ''}
          {artifact.editable &&
            (editing ? (
              <button
                type="button"
                onClick={stopEditing}
                className="ml-1 flex items-center gap-1 rounded-md border border-line px-2 py-1 hover:border-primary"
              >
                <X className="h-3.5 w-3.5" />
                完成
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="ml-1 flex items-center gap-1 rounded-md border border-line px-2 py-1 hover:border-primary"
              >
                <Pencil className="h-3.5 w-3.5" />
                编辑
              </button>
            ))}
          {artifact.restore_available && (
            <button
              type="button"
              disabled={restoring}
              onClick={() => void doRestore()}
              className="flex items-center gap-1 rounded-md border border-line px-2 py-1 hover:border-primary disabled:opacity-50"
              title="用最近恢复点覆盖当前内容（可再撤销）"
            >
              <History className="h-3.5 w-3.5" />
              恢复上一版
            </button>
          )}
        </span>
      </div>

      {conflict && (
        <div className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2.5 text-sm">
          <p className="font-medium text-warning">内容已被其他会话更新</p>
          <p className="mt-1 text-muted-foreground">
            你屏幕上的修改仍然完整——请选择保留哪一份；选「保留我的」会覆盖对方版本（对方版本自动留底）。
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void adoptLatest()}
              className="rounded-md border border-line bg-card px-2.5 py-1 text-xs hover:border-line-2"
            >
              拉取最新内容
            </button>
            <button
              type="button"
              onClick={() => void doSave(true)}
              className="rounded-md bg-warning/90 px-2.5 py-1 text-xs font-medium text-white hover:bg-warning"
            >
              保留我的版本
            </button>
          </div>
        </div>
      )}

      {editing ? (
        <textarea
          value={body}
          onChange={(e) => {
            setBody(e.target.value)
            dirty.current = true
          }}
          placeholder="markdown 正文…"
          className="min-h-0 w-full flex-1 resize-none rounded-lg border border-line bg-card p-3 text-sm leading-relaxed focus:border-primary focus:outline-none"
        />
      ) : (
        <div className="note-md min-h-0 flex-1 overflow-auto rounded-lg border border-line bg-card p-4 text-sm leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {body || '_（空笔记）_'}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}
