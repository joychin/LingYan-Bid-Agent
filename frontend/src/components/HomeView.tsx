import { useMemo, useState } from 'react'
import type { DragEvent } from 'react'
import { ArrowRight, FolderOpen, Plus, Search, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useActiveRuns } from '@/hooks/useActiveRuns'
import { useConversations } from '@/hooks/useConversations'
import { useTasks } from '@/hooks/useTasks'
import { formatRelativeTime } from '@/lib/utils'
import { isFinishedStage, stageLabel } from '@/lib/taskStage'

/** 文件名去扩展名（拖放建任务的默认任务名；「.tar.gz」类双后缀不较真） */
function fileStem(name: string): string {
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(0, i) : name
}

/**
 * 任务首页（无会话选中时的主区，「任务即房间」2026-09-13；列表形态 = 用户拍板的
 * H2 方向）：一屏看清「每个标走到哪一步」，而不是只有会话数。
 *
 * - 阶段/最近活动来自 sidecar（task_stage.py 机械推导，零 LLM）；本页**按
 *   last_activity_at 倒序**排（后端 /tasks 仍按创建序——侧栏保持稳定不跳动）。
 * - 行点击 = 进入该任务最近会话（继续）；行 hover「＋」= 在该任务新建会话。
 * - 建任务入口两条：顶部「＋ 开始新投标」（行内命名）/ 整页拖入招标文件（文件名
 *   即任务名，文件随后在会话里上传）。
 * - 实时状态胶囊（执行中/等待确认）由 useActiveRuns 纯前端 join 会话所属任务得到
 *   ——比「待办数」现成且实时（待办只存 run 级 trace，无法在列表廉价取到）。
 */
export function HomeView({
  onOpenTask,
  onCreateTask,
  onNewConversation,
}: {
  /** 进入任务：打开其最近会话（无会话则由 App 就地新建一个） */
  onOpenTask: (taskId: string) => void
  /** 建任务（自带首个会话）并进入；失败由 App toast，本页不重复提示 */
  onCreateTask: (title: string, files: File[]) => Promise<void> | void
  /** 在该任务新建会话并进入（行 hover「＋」，与侧栏任务文件夹同款语义） */
  onNewConversation: (taskId: string) => void
}) {
  const { data: tasks = [] } = useTasks()
  const { data: conversations = [] } = useConversations()
  const { data: activeRuns = [] } = useActiveRuns()

  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  // 任务 → 占用中 run 状态：经 conversation_id 反查所属任务（等待确认优先于执行中，
  // 一个任务多会话同时跑时取更强信号——等待确认是「要你动手」，不该被 running 盖掉）
  const runStatusByTask = useMemo(() => {
    const taskOfConv = new Map(conversations.map((c) => [c.id, c.task_id ?? null] as const))
    const out = new Map<string, 'running' | 'waiting_input'>()
    for (const r of activeRuns) {
      const tid = taskOfConv.get(r.conversation_id)
      if (!tid) continue
      const prev = out.get(tid)
      if (prev === 'waiting_input') continue
      out.set(tid, r.status)
    }
    return out
  }, [activeRuns, conversations])

  const rows = useMemo(() => {
    const q = query.trim().toLocaleLowerCase()
    return tasks
      .map((task) => ({
        task,
        convCount: conversations.filter((c) => c.task_id === task.id).length,
        runStatus: runStatusByTask.get(task.id) ?? null,
      }))
      // 最近活动倒序：「我昨天在猛推的那个标」应排最上面（后端排序是创建序，不合此用）。
      // ?? ''：sidecar 旧进程无该字段时降级为空串（排最后），不白屏——stageLabel/formatRelativeTime 同款容忍
      .toSorted((a, b) => (b.task.last_activity_at ?? '').localeCompare(a.task.last_activity_at ?? ''))
      .filter((r) => !q || r.task.title.toLocaleLowerCase().includes(q))
  }, [tasks, conversations, runStatusByTask, query])

  const submit = async () => {
    const name = title.trim()
    if (busy || !name) return
    setBusy(true)
    try {
      await onCreateTask(name, [])
    } finally {
      // 成功则本页随导航卸载；重置只为失败时停在原地可改可重试
      setBusy(false)
    }
  }

  // 整页拖放=拖招标文件建任务：已有手输名沿用之，否则文件名即任务名；
  // 只拦 Files（框内文字拖放走原生行为）
  const dropHandlers = {
    onDragOver: (e: DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer.types.includes('Files')) return
      e.preventDefault()
      setDragOver(true)
    },
    onDragLeave: (e: DragEvent<HTMLDivElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false)
    },
    onDrop: (e: DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer.types.includes('Files')) return
      e.preventDefault()
      setDragOver(false)
      const files = Array.from(e.dataTransfer.files ?? [])
      if (files.length === 0) return
      void onCreateTask(title.trim() || fileStem(files[0].name), files)
    },
  }

  // 行内命名创建（顶部按钮触发；零任务时是唯一的创建入口）
  const createForm = (
    <div className="home-newrow">
      <input
        className="home-newrow-input"
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void submit()
          if (e.key === 'Escape') setCreating(false)
        }}
        placeholder="任务名称，回车创建"
      />
      <Button size="sm" disabled={busy || !title.trim()} onClick={() => void submit()}>
        {busy ? '创建中…' : '创建并开始'}
      </Button>
      <Button size="sm" variant="ghost" disabled={busy} onClick={() => setCreating(false)}>
        取消
      </Button>
    </div>
  )

  return (
    <div className="home" {...dropHandlers}>
      <div className="home-inner">
        <div className="home-head">
          <h2 className="home-title">任务</h2>
          <div className="home-head-right">
            <label className="home-search">
              <Search />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索任务"
                aria-label="搜索任务"
              />
            </label>
            <Button size="sm" onClick={() => setCreating(true)} disabled={creating}>
              <Plus />
              开始新投标
            </Button>
          </div>
        </div>

        {creating && createForm}

        {tasks.length === 0 ? (
          <button type="button" className="home-empty" onClick={() => setCreating(true)}>
            <Plus />
            <span className="main">开始第一个投标任务</span>
            <span className="sub">点击命名，或直接把招标文件拖到这里</span>
          </button>
        ) : rows.length === 0 ? (
          <p className="home-noresult">没有匹配「{query.trim()}」的任务</p>
        ) : (
          <>
            <div className="home-thead">
              <span className="c-task">任务</span>
              <span className="c-stage">阶段</span>
              <span className="c-convs">会话</span>
              <span className="c-time">最近更新</span>
              <span className="c-tail" />
            </div>
            <div className="home-rows">
              {rows.map(({ task, convCount, runStatus }) => (
                <div
                  key={task.id}
                  className="home-row group/home-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => onOpenTask(task.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onOpenTask(task.id)
                    }
                  }}
                >
                  <span className="c-task">
                    <FolderOpen />
                    <span className="name">{task.title}</span>
                    {runStatus && (
                      <span className={runStatus === 'waiting_input' ? 'wait-pill' : 'run-pill'}>
                        {runStatus === 'waiting_input' ? '等待确认' : '执行中'}
                      </span>
                    )}
                  </span>
                  <span className="c-stage">
                    <span className={isFinishedStage(task.stage) ? 'stage-pill done' : 'stage-pill'}>
                      {stageLabel(task.stage)}
                    </span>
                  </span>
                  <span className="c-convs">{convCount} 个会话</span>
                  <span className="c-time">{formatRelativeTime(task.last_activity_at)}</span>
                  <span className="c-tail">
                    <button
                      type="button"
                      className="home-row-add"
                      title="在此任务新建会话"
                      onClick={(e) => {
                        e.stopPropagation()
                        onNewConversation(task.id)
                      }}
                    >
                      <Plus />
                    </button>
                    <ArrowRight className="home-row-arrow" />
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        <p className="home-hint">也可以直接把招标文件拖进来，自动创建任务</p>
      </div>
      {dragOver && (
        <div className="home-drop-overlay">
          <Upload />
          <span>松开：以文件名创建任务并上传</span>
        </div>
      )}
    </div>
  )
}
