/**
 * 通用笔记 Processor（doc.note/note-md@1）：markdown 文档查看 + 编辑。
 * 未注册类型的统一收拢形态——LLM 的中间结论/记忆以笔记保存，这里保证一定打得开、改得了。
 * 保存基建走 useAutoSave（2026-09-04 统一）：防抖自动保存 + content_seq 探测 +
 * 5s 轮询外部更新（查看态静默跟随、编辑态弹「拉取最新 / 保留我的」用户裁决，
 * 与目录编辑器同一文件夹语义——此前笔记无轮询、查看态不跟随，本批补齐）。
 */

import { useEffect, useRef, useState } from 'react'
import type { ProcessorProps } from '@/artifacts/registry'
import { getArtifactContent, getArtifactMeta, restoreArtifact, updateArtifactContent } from '@/api/client'
import { useQueryClient } from '@tanstack/react-query'
import { History, Pencil, X } from 'lucide-react'
import { useAutoSave } from '@/hooks/useAutoSave'
import { SaveStateBar } from '@/components/editors/SaveStateBar'
import { MarkdownEditor, type EditorMode } from '@/components/editors/MarkdownEditor'

interface NoteData {
  title: string
  body_md: string
}

function parseNote(raw: string): NoteData | null {
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>
    return {
      title: typeof obj.title === 'string' ? obj.title : '',
      body_md: typeof obj.body_md === 'string' ? obj.body_md : '',
    }
  } catch {
    return null
  }
}

export function NoteProcessor({ artifact, content }: ProcessorProps) {
  const queryClient = useQueryClient()
  const initial = parseNote(content)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(initial?.title ?? '')
  const [body, setBody] = useState(initial?.body_md ?? '')
  const [restoring, setRestoring] = useState(false)
  const [mode, setMode] = useState<EditorMode>('split')

  // 基底版本号：保存成功/adopt/reset 三处同步写（useAutoSave 的 core 同步维护同一来源）
  const seqRef = useRef(artifact.content_seq)
  const latest = useRef({ title, body })
  latest.current = { title, body }

  const auto = useAutoSave({
    save: async (force) => {
      const res = await updateArtifactContent(
        artifact.artifact_id,
        {
          title: latest.current.title.trim() || artifact.display_name,
          body_md: latest.current.body,
        },
        seqRef.current,
        force,
      )
      seqRef.current = res.content_seq
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      return res.content_seq
    },
    fetchMeta: async () => (await getArtifactMeta(artifact.artifact_id)).content_seq,
    initialVersion: artifact.content_seq,
    onExternalUpdate: () => {
      void adoptLatest() // 查看态静默跟随（AI 重新发布后 ≤5s 刷新）
    },
  })

  /** 拉取最新：换基底（无改动静默跟随 / 冲突时用户已知情选择丢弃本地）。 */
  const adoptLatest = async () => {
    const fresh = await getArtifactContent(artifact.artifact_id)
    const note = parseNote(fresh.content)
    if (note) {
      setTitle(note.title)
      setBody(note.body_md)
    }
    const meta = await getArtifactMeta(artifact.artifact_id)
    seqRef.current = meta.content_seq
    auto.reset(meta.content_seq)
  }

  const doRestore = async () => {
    setRestoring(true)
    try {
      await restoreArtifact(artifact.artifact_id)
      const fresh = await getArtifactContent(artifact.artifact_id)
      const note = parseNote(fresh.content)
      if (note) {
        setTitle(note.title)
        setBody(note.body_md)
      }
      const meta = await getArtifactMeta(artifact.artifact_id)
      seqRef.current = meta.content_seq
      auto.reset(meta.content_seq)
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    } finally {
      setRestoring(false)
    }
  }

  // 外部内容刷新（react-query refetch）：无本地改动时跟随 + 对齐基底版本号
  useEffect(() => {
    const note = parseNote(content)
    if (!note) return
    const s = auto.state
    if (s === 'dirty' || s === 'saving' || s === 'conflict' || s === 'error') return
    setTitle(note.title)
    setBody(note.body_md)
    seqRef.current = artifact.content_seq
    auto.reset(artifact.content_seq)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, artifact.content_seq])

  if (!initial) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        内容解析失败：不符合笔记结构
      </div>
    )
  }

  const stopEditing = () => {
    if (auto.state === 'conflict') return // 留在编辑态等横幅裁决，不静默丢编辑
    if (auto.state === 'dirty') void auto.saveNow()
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
              auto.markDirty()
            }}
            placeholder="标题"
            className="w-full max-w-md rounded-md border border-line bg-card px-2 py-1 text-base font-semibold focus:border-primary focus:outline-none"
          />
        ) : (
          <h3 className="truncate text-base font-semibold">{title || artifact.display_name}</h3>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
          {editing && <SaveStateBar state={auto.state} lastSavedAt={auto.lastSavedAt} onRetry={() => void auto.saveNow()} />}
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

      {auto.state === 'conflict' && (
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
              onClick={() => void auto.saveNow(true)}
              className="rounded-md bg-warning px-2.5 py-1 text-xs font-medium text-warning-foreground hover:opacity-90"
            >
              保留我的版本
            </button>
          </div>
        </div>
      )}

      {editing ? (
        <MarkdownEditor
          value={body}
          onChange={(v) => {
            setBody(v)
            auto.markDirty()
          }}
          mode={mode}
          onModeChange={setMode}
          placeholder="markdown 正文…"
          className="rounded-lg"
        />
      ) : (
        <div className="note-md flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line bg-card p-4 text-sm leading-relaxed">
          <MarkdownEditor value={body} mode="preview" viewOnly emptyLabel="_（空笔记）_" />
        </div>
      )}
    </div>
  )
}
