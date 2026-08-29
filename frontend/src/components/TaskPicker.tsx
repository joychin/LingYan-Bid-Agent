import { useEffect, useState } from 'react'
import { Check, ChevronDown, Folder, Plus } from 'lucide-react'
import type { Task } from '@/api/client'
import { cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

/**
 * 新会话的「所属任务」选择器（P4：会话必须归属任务）。
 * 嵌在输入框底栏左侧的中性胶囊（与 ModelSelect 同语言），
 * 下拉可选既有任务，也可就地新建（不跳会话——用户正在输入首发消息，
 * 新任务不连带会话，由首发消息创建）。
 */
export function TaskPicker({
  tasks,
  value,
  onChange,
  onCreateTask,
}: {
  tasks: Task[]
  value: string | null
  onChange: (taskId: string | null) => void
  /** 就地新建任务：返回新任务 id（不建会话）；失败抛错由本组件提示 */
  onCreateTask: (title: string) => Promise<string>
}) {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const selected = tasks.find((t) => t.id === value) ?? null

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (target && !(target as HTMLElement).closest?.('[data-task-picker]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  const submitCreate = async () => {
    const name = title.trim()
    if (!name || busy) return
    setBusy(true)
    try {
      const id = await onCreateTask(name)
      onChange(id)
      setOpen(false)
      setCreating(false)
      setTitle('')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="relative"
      data-task-picker
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <button type="button" className="task-select" onClick={() => setOpen(!open)}>
        <Folder className="task-icon" />
        <span className="label">{selected ? selected.title : '选择任务'}</span>
        <ChevronDown className={cn('chev transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-72 rounded-[var(--Radius-radius-12)] border border-line bg-card py-1.5 shadow-md">
          {tasks.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                onChange(t.id)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm',
                t.id === value ? 'bg-accent-soft' : 'hover:bg-secondary',
              )}
            >
              <Folder className="h-4 w-4 shrink-0 text-ink-3" />
              <span className="flex-1 truncate">{t.title}</span>
              {t.id === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
            </button>
          ))}
          {tasks.length > 0 && <div className="my-1 border-t border-line" />}
          {creating ? (
            <div className="flex items-center gap-1.5 px-2 py-1.5">
              <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void submitCreate()
                  if (e.key === 'Escape') {
                    e.stopPropagation()
                    setCreating(false)
                  }
                }}
                placeholder="新任务名称"
                className="w-full rounded-md border border-line bg-transparent px-2 py-1 text-sm focus:border-primary focus:outline-none"
              />
              <button
                type="button"
                disabled={!title.trim() || busy}
                onClick={() => void submitCreate()}
                className="shrink-0 rounded-md border border-line px-2 py-1 text-xs hover:border-primary disabled:opacity-50"
              >
                {busy ? '…' : '创建'}
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-secondary"
            >
              <Plus className="h-4 w-4" />
              新建任务
            </button>
          )}
        </div>
      )}
    </div>
  )
}
