import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown } from 'lucide-react'
import { UploadDropzone } from '@/components/UploadDropzone'
import { ChatMessage, markdownComponents } from '@/components/ChatMessage'
import { Loader } from '@/components/ai/Loader'
import { Duration } from '@/components/ai/Duration'
import { ThinkingBar } from '@/components/ai/ThinkingBar'
import {
  InterruptCard,
  isQuestion,
  hasQuestion,
  stepAnswered,
  type StepDraft,
} from '@/components/ai/InterruptCard'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { RunTrace } from '@/components/ai/RunTrace'
import { Message as WMessage } from '@/components/workspace/Message'
import { ArtifactCard } from '@/components/ArtifactCard'
import { WelcomeScreen } from '@/components/WelcomeScreen'
import { InputComposer } from '@/components/InputComposer'
import { TaskPicker } from '@/components/TaskPicker'
import { useMessages } from '@/hooks/useMessages'
import { useRun } from '@/hooks/useRun'
import type { RunState } from '@/hooks/useRun'
import { useArtifacts } from '@/hooks/useArtifacts'
import { useConversations } from '@/hooks/useConversations'
import { useCreateTask, useTasks } from '@/hooks/useTasks'
import { useFileUpload } from '@/context/FileUpload'
import { useToast } from '@/context/Toast'
import { formatDay } from '@/lib/utils'
import type { Artifact, Message } from '@/api/client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function ChatView({
  convId,
  onOpenArtifact,
  initialSend,
  onRequestCreate,
  onOpenSettings,
}: {
  convId: string | null
  onOpenArtifact: (id: string) => void
  initialSend: string | null
  /** 首发消息：无会话时由 App 在所选任务下建会话并转发文本（P4：会话必须归属任务） */
  onRequestCreate: (text: string, taskId: string) => void
  /** 打开设置（输入区模型胶囊入口） */
  onOpenSettings?: () => void
}) {
  const { data: messages = [], isLoading } = useMessages(convId)
  const {
    running,
    startedAt,
    stopping,
    streamText,
    reasoningText,
    tools,
    todos,
    done,
    total,
    error,
    lastSent,
    interrupt,
    send,
    decide,
    cancel,
  } = useRun(convId)
  const { data: artifacts = [] } = useArtifacts()
  const { data: tasks = [] } = useTasks()
  const { data: conversations = [] } = useConversations()
  const createTask = useCreateTask()
  const { toast } = useToast()
  const { openFilePicker, setTaskScope, uploads, taskScope, acknowledgeUploads } = useFileUpload()
  const scrollRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const [prompt, setPrompt] = useState<string | null>(initialSend)
  const [pickedTaskId, setPickedTaskId] = useState<string | null>(null)
  // HITL 逐项草稿（含问快照：单问=向导 N=1 特例，统一卡内作答）。按 runId 判定
  // 新中断才重置：SSE 重连对账（run.state waiting_input）会 new 一个同 runId 的
  // interrupt 对象，按对象引用重置会把用户已答内容清空
  const [stepIndex, setStepIndex] = useState(0)
  const [stepDrafts, setStepDrafts] = useState<StepDraft[]>([])
  const lastInterruptRunRef = useRef<string | null>(null)
  useEffect(() => {
    const runId = interrupt?.runId ?? null
    if (interrupt && runId !== lastInterruptRunRef.current) {
      setStepIndex(0)
      setStepDrafts(interrupt.requests.map(() => ({ picked: [], text: '' })))
    }
    lastInterruptRunRef.current = runId
  }, [interrupt])

  // 上传归属任务（§16 任务级文件区）：选中会话→其所属任务；草稿页→选择器挑的任务
  useEffect(() => {
    const conv = convId ? conversations.find((c) => c.id === convId) : null
    setTaskScope(conv?.task_id ?? (convId ? null : pickedTaskId))
  }, [convId, conversations, pickedTaskId, setTaskScope])

  // ---- HITL 逐项卡（含问快照，单问=向导 N=1 特例）：卡内作答，最后一项一次 resume 全量 ----
  const wizardMode = !!interrupt && hasQuestion(interrupt.requests)
  const curReq = wizardMode && interrupt ? interrupt.requests[stepIndex] : null
  const curMultiple = Boolean(curReq?.args?.multiple)
  // 本任务新上传未告知的文件：HITL 提交时自动拼「我上传了文件：…」告知
  // （主输入框等待期间禁用，确认门补传补遗的场景由此保住）
  const freshFiles = useMemo(
    () => uploads.filter((u) => u.status === 'done' && u.taskId === taskScope),
    [uploads, taskScope],
  )

  const toggleStepOption = useCallback(
    (opt: string) => {
      setStepDrafts((cur) => {
        const d = cur[stepIndex] ?? { picked: [], text: '' }
        const picked = d.picked.includes(opt)
          ? d.picked.filter((o) => o !== opt)
          : curMultiple
            ? [...d.picked, opt]
            : [opt]
        const next = [...cur]
        next[stepIndex] = { ...d, picked }
        return next
      })
    },
    [stepIndex, curMultiple],
  )

  const setStepText = useCallback((v: string) => {
    setStepDrafts((cur) => {
      const next = [...cur]
      next[stepIndex] = { ...(next[stepIndex] ?? { picked: [], text: '' }), text: v }
      return next
    })
  }, [stepIndex])

  const setStepApproval = useCallback((choice: 'approve' | 'reject') => {
    setStepDrafts((cur) => {
      const next = [...cur]
      next[stepIndex] = { ...(next[stepIndex] ?? { picked: [], text: '' }), approval: choice }
      return next
    })
  }, [stepIndex])

  const setStepReason = useCallback((v: string) => {
    setStepDrafts((cur) => {
      const next = [...cur]
      next[stepIndex] = { ...(next[stepIndex] ?? { picked: [], text: '' }), reason: v }
      return next
    })
  }, [stepIndex])

  /**
   * 逐项卡导航：-1 回退（卡内草稿受控保留）；+1 未答守卫（toast 拦下）→
   * 非最后一项步进，最后一项组装全量 decisions 一次 resume（协议要求 decisions
   * 与快照逐位对应、数量相等，不能只答部分）。提交时若有刚上传未告知的文件，
   * 把「我上传了文件：…」拼进当前 question 步的回答。
   */
  const wizardNav = useCallback(
    (dir: -1 | 1) => {
      if (!interrupt) return
      const reqs = interrupt.requests
      const drafts = [...stepDrafts]
      while (drafts.length < reqs.length) drafts.push({ picked: [], text: '' })

      if (dir < 0) {
        setStepDrafts(drafts)
        setStepIndex(Math.max(0, stepIndex - 1))
        return
      }
      const cur = drafts[stepIndex]
      if (!stepAnswered(reqs[stepIndex], cur)) {
        toast(isQuestion(reqs[stepIndex]) ? '请先点选选项或输入回答' : '请先选择批准或拒绝', 'error')
        return
      }
      setStepDrafts(drafts)
      if (stepIndex + 1 >= reqs.length) {
        const fileNote =
          freshFiles.length > 0 && isQuestion(reqs[stepIndex])
            ? `我上传了文件：${freshFiles.map((f) => f.name).join('、')}，请查收处理`
            : ''
        if (fileNote) {
          drafts[stepIndex] = { ...cur, text: [cur.text.trim(), fileNote].filter(Boolean).join('\n') }
        }
        const decisions = reqs.map((r, i) => {
          const d = drafts[i]
          if (isQuestion(r)) {
            return {
              type: 'respond' as const,
              message: [d.picked.length > 0 ? `已选：${d.picked.join('；')}` : '', d.text.trim()]
                .filter(Boolean)
                .join('\n'),
            }
          }
          return d.approval === 'reject'
            ? { type: 'reject' as const, ...(d.reason?.trim() ? { message: d.reason.trim() } : {}) }
            : { type: 'approve' as const }
        })
        void decide(decisions)
        if (fileNote) acknowledgeUploads(freshFiles.map((f) => f.id))
        return
      }
      setStepIndex(stepIndex + 1)
    },
    [interrupt, stepIndex, stepDrafts, freshFiles, decide, toast, acknowledgeUploads],
  )

  const convArtifacts = convId ? artifacts.filter((a) => a.conversation_id === convId) : []
  const empty = messages.length === 0 && !running && !isLoading

  const doSend = useCallback(
    async (text: string) => {
      if (!convId) {
        if (!pickedTaskId) {
          toast('请先选择所属任务', 'error')
          return
        }
        // 建会话失败时恢复被 InputComposer 清掉的输入，用户重试不必重打
        try {
          await onRequestCreate(text, pickedTaskId)
        } catch (e) {
          toast(e instanceof Error ? e.message : String(e), 'error')
          setPrompt(text)
        }
        return
      }
      if (running) return
      try {
        await send(text)
      } catch {
        /* 发送失败：由 useRun 展示错误，输入框内容由 InputComposer 保留 */
      }
    },
    [convId, running, send, onRequestCreate, pickedTaskId, toast],
  )

  // 无会话时 App 转发首发消息。StrictMode 开发模式会把本 effect 跑两遍
  // （挂载→cleanup→重挂载），无守卫会双发 POST，第二发撞 409「已有进行中的任务」
  const sentInitialRef = useRef<string | null>(null)
  useEffect(() => {
    if (initialSend) {
      setPrompt(initialSend)
      if (convId && sentInitialRef.current !== initialSend) {
        sentInitialRef.current = initialSend
        void doSend(initialSend)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSend, convId])

  const fillPrompt = (text: string) => setPrompt(text)

  /** 选择器就地新建任务：只建任务不建会话（首发消息时再建），保住已输入的文本。 */
  const handlePickerCreateTask = async (title: string): Promise<string> => {
    const body = await createTask.mutateAsync({ title, withConversation: false })
    return body.task.id
  }

  // 流式自动贴底；用户上滚则停止贴底
  useEffect(() => {
    if (atBottom.current) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    }
  }, [messages, streamText, tools, todos])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    atBottom.current = nearBottom
    setShowJump(!nearBottom)
  }

  const jumpToBottom = () => {
    atBottom.current = true
    setShowJump(false)
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }

  // HITL 等待期间主输入框禁用（作答在卡内），placeholder 只做指引
  const waitingHint = interrupt
    ? wizardMode
      ? curReq && !isQuestion(curReq)
        ? '此步为审批：请在上方卡片选择批准或拒绝…'
        : '请在上方卡片中作答（可先在此上传文件）…'
      : '请在上方卡片中选择批准或拒绝…'
    : undefined

  return (
    <UploadDropzone>
      <div className="relative flex h-full w-full flex-col">
        <div ref={scrollRef} onScroll={handleScroll} className="chat-scroll">
          <div className="chat">
            {isLoading && <MessageSkeletons />}
            {empty && <WelcomeScreen onPickFile={openFilePicker} onPrompt={fillPrompt} />}
            <MessageList messages={messages} convArtifacts={convArtifacts} onOpenArtifact={onOpenArtifact} />
            {running && (
              <RunMessage running={running} startedAt={startedAt} tools={tools} todos={todos} done={done} total={total} text={streamText} reasoningText={reasoningText} />
            )}
            {interrupt && !running && (
              wizardMode ? (
                <InterruptCard
                  requests={interrupt.requests}
                  wizard={{
                    stepIndex,
                    stepDrafts,
                    onToggleStep: toggleStepOption,
                    onTextChange: setStepText,
                    onApprovalChoice: setStepApproval,
                    onReasonChange: setStepReason,
                    onNav: wizardNav,
                  }}
                />
              ) : (
                <InterruptCard requests={interrupt.requests} onDecide={(d) => void decide(d)} />
              )
            )}
            {error && (
              <ErrorCard message={error} retryText={lastSent} onRetry={() => void doSend(lastSent)} />
            )}
          </div>
        </div>
        {showJump && (
          <div className="flex shrink-0 justify-center pb-2">
            <button
              type="button"
              onClick={jumpToBottom}
              className="flex items-center gap-1 rounded-full border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-md hover:text-foreground"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              回到底部
            </button>
          </div>
        )}
        <InputComposer
          running={running}
          waiting={!!interrupt}
          waitingHint={waitingHint}
          disabled={!!interrupt}
          stopping={stopping}
          onSend={doSend}
          value={prompt}
          onChange={setPrompt}
          onOpenSettings={onOpenSettings}
          onStop={() => void cancel()}
          leftSlot={
            !convId ? (
              <TaskPicker
                tasks={tasks}
                value={pickedTaskId}
                onChange={setPickedTaskId}
                onCreateTask={handlePickerCreateTask}
              />
            ) : null
          }
        />
      </div>
    </UploadDropzone>
  )
}

/** 运行中的助手消息：头像 + 状态 + 执行过程（Reasoning 折叠）+ 任务清单时间线（Steps）+ 流式正文。 */
function RunMessage({
  running,
  startedAt,
  tools,
  todos,
  done,
  total,
  text,
  reasoningText,
}: {
  running: boolean
  startedAt: number | null
  tools: RunState['tools']
  todos: RunState['todos']
  done: number
  total: number
  text: string
  reasoningText: string
}) {
  return (
    <WMessage
      role="assistant"
      name="Tender Agent"
      avatar={<div className="msg-avatar">T</div>}
      status={
        <>
          <Loader variant="dots" size="sm" /> 执行中
          {startedAt && <Duration startedAt={startedAt} className="ml-1" />}
        </>
      }
    >
      {reasoningText && (
        <Reasoning isStreaming={running} className="mb-2">
          <ReasoningTrigger className="text-sm text-foreground">深度思考</ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2 text-[13px] leading-relaxed" markdown>
            {reasoningText}
          </ReasoningContent>
        </Reasoning>
      )}
      {(tools.length > 0 || todos.length > 0) && (
        <Reasoning isStreaming={running} className="mb-2">
          <ReasoningTrigger className="text-sm text-foreground">执行过程</ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2">
            <RunTrace tools={tools} todos={todos} done={done} total={total} />
          </ReasoningContent>
        </Reasoning>
      )}
      <div className="bubble">
        {text ? (
          <>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {text}
            </ReactMarkdown>
            <span className="caret-blink ml-0.5 inline-block h-[1.15em] w-0.5 translate-y-[0.2em] bg-primary" />
          </>
        ) : (
          <ThinkingBar text="正在思考…" />
        )}
      </div>
    </WMessage>
  )
}

function MessageList({
  messages,
  convArtifacts,
  onOpenArtifact,
}: {
  messages: Message[]
  convArtifacts: Artifact[]
  onOpenArtifact: (id: string) => void
}) {
  const nodes: React.ReactNode[] = []
  let lastDay = ''
  for (const m of messages) {
    const day = formatDay(m.created_at)
    if (day !== lastDay) {
      lastDay = day
      nodes.push(
        <div key={`day-${m.id}`} className="flex justify-center">
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{day}</span>
        </div>,
      )
    }
    nodes.push(<ChatMessage key={m.id} message={m} />)
  }
  for (const a of convArtifacts) {
    nodes.push(<ArtifactCard key={a.artifact_id} artifact={a} onOpen={onOpenArtifact} />)
  }
  return <>{nodes}</>
}

function ErrorCard({ message, retryText, onRetry }: { message: string; retryText: string; onRetry: () => void }) {
  return (
    <div className="rounded-lg border border-error/50 bg-error/5 px-3 py-2 text-sm text-error">
      {message}
      {retryText.trim() && (
        <button type="button" className="ml-2 hover:underline" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  )
}

function MessageSkeletons() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <div className="h-10 w-48 animate-pulse rounded-xl bg-muted" />
      </div>
      <div className="h-6 w-3/4 animate-pulse rounded-md bg-muted" />
      <div className="h-6 w-2/3 animate-pulse rounded-md bg-muted" />
    </div>
  )
}
