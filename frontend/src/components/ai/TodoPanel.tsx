import { useEffect, useRef, useState } from 'react'
import { ChevronUp, CirclePause } from 'lucide-react'
import type { TodoItem } from '@/api/sse'
import { Loader } from '@/components/ai/Loader'
import { cn } from '@/lib/utils'

/** 会话区右上角的任务清单常驻浮层（2026-09-12，取代活卡过程区末尾的清单折叠组——
 *  长任务里它随会话卡片被淹没，用户不知道模型此刻在做什么）。
 *  形态 = 常驻展开的紧凑清单卡（ZCode 目标模式「右侧摘要面板」的轻量版）：限高滚动、
 *  当前项推进时自动滚到列表中部；可收起成单行胶囊（进度 + 当前任务）。
 *  生命周期：无 todo 不出现（闲聊/短问答天然没有，由活卡状态行承担活动可见性）；
 *  恒显当前活跃 run 的最新清单（todo.updated 整组替换）；HITL 等待期冻结保留
 *  （暂停图标）；run 终态随活卡消失——历史清单仍在历史消息的过程区（run_traces 快照）。
 *  open 态是 run 级的（新 run 重新默认展开），不持久化。 */
export function TodoPanel({
  todos,
  done,
  total,
  running,
  paused,
}: {
  todos: TodoItem[]
  done: number
  total: number
  running: boolean
  /** ask_human 等待裁决：清单冻结显示（不转圈） */
  paused: boolean
}) {
  const [open, setOpen] = useState(true)
  const activeIndex = todos.findIndex((t) => t.status === 'in_progress')
  const activeItem = activeIndex >= 0 ? todos[activeIndex] : null
  const listRef = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLDivElement>(null)
  // 自动跟随：仅在当前项推进（索引变化）或展开瞬间定位一次——列表其余重排（前项
  // 置灰、文案改写）不打扰用户手动滚动。手动算 scrollTop 而非 scrollIntoView：
  // 后者会连动聊天滚动区等所有滚动祖先
  useEffect(() => {
    const list = listRef.current
    const el = activeRef.current
    if (!open || !list || !el) return
    const target = el.offsetTop - list.clientHeight / 2 + el.clientHeight / 2
    if (target > 0) list.scrollTop = target
  }, [open, activeIndex])

  if (todos.length === 0) return null

  const statusIcon = running ? (
    <Loader variant="dots" size="xs" className="shrink-0" />
  ) : paused ? (
    <CirclePause className="size-3.5 shrink-0" aria-hidden />
  ) : null

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="展开任务清单"
        className="absolute right-3 top-2 z-10 flex max-w-[calc(100%-1.5rem)] items-center gap-2 rounded-full border border-line bg-card px-3 py-1.5 text-xs shadow-md hover:text-foreground"
      >
        {statusIcon}
        <span className="shrink-0 text-muted-foreground">
          {done}/{total}
        </span>
        {activeItem && <span className="truncate text-foreground">{activeItem.content}</span>}
      </button>
    )
  }

  return (
    <div className="absolute right-3 top-2 z-10 flex max-h-[60vh] w-72 max-w-[calc(100%-1.5rem)] flex-col rounded-lg border border-line bg-card shadow-md">
      <div className="flex items-center gap-1.5 border-b border-line px-3 py-2 text-xs text-muted-foreground">
        {statusIcon}
        <span className="shrink-0">
          任务清单 · {done} / {total}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          title="收起"
          className="ml-auto cursor-pointer rounded p-0.5 text-muted-foreground/60 hover:text-foreground"
        >
          <ChevronUp className="size-3.5" aria-hidden />
        </button>
      </div>
      {/* relative：让行的 offsetTop 以列表为基准（自动跟随的定位前提） */}
      <div ref={listRef} className="relative min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {todos.map((t, i) => {
          const isDone = t.status === 'completed'
          const isDoing = t.status === 'in_progress'
          return (
            <div
              key={i}
              ref={i === activeIndex ? activeRef : undefined}
              className="flex items-start gap-2 py-1 text-[13px] leading-5"
            >
              <span
                className={cn(
                  'mt-0.5 flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px]',
                  isDone
                    ? 'bg-primary text-primary-foreground'
                    : isDoing
                      ? 'bg-muted text-muted-foreground'
                      : 'border border-line text-transparent',
                )}
              >
                {isDone ? '✓' : isDoing ? '●' : '○'}
              </span>
              <span
                className={cn(
                  'min-w-0 break-words',
                  isDone
                    ? 'text-muted-foreground/70 line-through'
                    : isDoing
                      ? 'font-medium text-foreground'
                      : 'text-muted-foreground',
                )}
              >
                {t.content}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
