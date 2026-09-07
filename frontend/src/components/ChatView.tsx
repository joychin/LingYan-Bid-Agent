import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSettings } from '@/api/client'
import { ArrowDown, CirclePause } from 'lucide-react'
import { UploadDropzone } from '@/components/UploadDropzone'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ChatMessage, DeepThinking } from '@/components/ChatMessage'
import { MemoMarkdown, markdownComponents } from '@/components/ai/MemoMarkdown'
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
import { RunTrace, NarrationLine } from '@/components/ai/RunTrace'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { toolDisplayName } from '@/components/ai/toolDisplay'
import { Message as WMessage } from '@/components/workspace/Message'
import { ArtifactCard } from '@/components/ArtifactCard'
import { placeArtifacts } from '@/lib/artifactPlacement'
import { WelcomeScreen } from '@/components/WelcomeScreen'
import { InputComposer } from '@/components/InputComposer'
import { TaskPicker } from '@/components/TaskPicker'
import { useMessages } from '@/hooks/useMessages'
import { useRun } from '@/hooks/useRun'
import { useThrottledValue } from '@/hooks/useThrottledValue'
import type { RunState } from '@/hooks/useRun'
import { useArtifacts } from '@/hooks/useArtifacts'
import { useConversations } from '@/hooks/useConversations'
import { useCreateTask, useTasks } from '@/hooks/useTasks'
import { useFileUpload } from '@/context/FileUpload'
import { useToast } from '@/context/Toast'
import { formatDay } from '@/lib/utils'
import { isLivePauseMessage, isRespondAnswer, lastInstructionText, splitMarker } from '@/lib/hitlMessage'
import { computeWindowStart } from '@/lib/messageWindow'
import type { Artifact, Message, ThinkingLevel } from '@/api/client'

/** 思考档位的本地记忆（App.tsx 的 LS_* 先例：tender-agent.<名字>） */
const LS_THINKING = 'tender-agent.thinking-level'
/** 模型选中的本地记忆：按会话粘性 map（cid→profile id）+ 上次使用（新会话默认）。
 *  导出供 Sidebar 删除会话时清理条目。 */
export const LS_MODEL_BY_CONV = 'tender-agent.model-by-conv'
const LS_MODEL_LAST = 'tender-agent.model-last'
/** 长会话首屏窗口大小（条）：尾部窗口 + 「加载更早」按此步进扩窗（见 messageWindow.ts） */
const MESSAGE_WINDOW = 50

function loadThinking(): ThinkingLevel {
  const v = localStorage.getItem(LS_THINKING)
  return v === 'medium' || v === 'high' ? v : 'low'
}

function loadModelMap(): Record<string, string> {
  try {
    const v = JSON.parse(localStorage.getItem(LS_MODEL_BY_CONV) || '{}')
    return typeof v === 'object' && v ? v : {}
  } catch {
    return {}
  }
}

export function ChatView({
  convId,
  onOpenArtifact,
  onOpenWorkbench,
  initialSend,
  onRequestCreate,
  onOpenSettings,
}: {
  convId: string | null
  onOpenArtifact: (id: string) => void
  /** 「本轮文件」chip -> 打开工作台面板编辑该文件（path 相对 <task>/work/） */
  onOpenWorkbench: (path: string) => void
  initialSend: string | null
  /** 首发消息：无会话时由 App 在所选任务下建会话并转发文本（P4：会话必须归属任务） */
  onRequestCreate: (text: string, taskId: string) => void
  /** 打开设置（输入区模型胶囊入口） */
  onOpenSettings?: () => void
}) {
  const {
    data: messages = [],
    isLoading,
    isError,
    error: messagesError,
    refetch: refetchMessages,
  } = useMessages(convId)
  const {
    running,
    runId,
    startedAt,
    stopping,
    streamText,
    reasoningText,
    tools,
    todos,
    done,
    total,
    error,
    errorCode,
    lastInstruction,
    continuationAnswer,
    pauseNarration,
    interrupt,
    continuation,
    continuationKind,
    send,
    decide,
    cancel,
  } = useRun(convId)
  // 活卡存续的 run（执行中累积 / 等待输入冻结 / 续跑接续）：该 run 的暂停/中断半截
  // 消息不渲染独立卡（一张活卡贯穿 run 生命周期）；终态后为空，消息回到转录被
  // 最终/中断消息吸收
  const liveRunId = running ? runId : (interrupt?.runId ?? null)
  // 停止/出错卡的「重新执行」文本：优先内存态 lastInstruction（发送失败重试——消息可能未落库），
  // 刷新后回退到消息列表里最后一条真实指令——终态 run 的用户消息必已落库；HITL 回答
  // 消息（含无「已选：」前缀的纯文字回答）由 isRespondAnswer 识别并跳过（重发会变成
  // 一条无上下文的普通消息）
  const retryText = lastInstruction || lastInstructionText(messages)
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
  // 思考档位（reasoning_effort）：随每条消息发送、localStorage 记忆上次选择（默认低）。
  // ChatView 持有而非 InputComposer：无会话首发（initialSend effect）也要带上档位
  const [thinking, setThinking] = useState<ThinkingLevel>(loadThinking)
  const changeThinking = useCallback((level: ThinkingLevel) => {
    setThinking(level)
    localStorage.setItem(LS_THINKING, level)
  }, [])
  // 模型选中（多模型 profile）：按会话粘性——会话里选过就一直用，新会话/无记录时
  // 用上次使用（无则 undefined=服务器 default）。ChatView 持有同 thinking 先例
  const [model, setModel] = useState<string | undefined>(() => {
    const last = localStorage.getItem(LS_MODEL_LAST)
    return last ?? undefined
  })
  useEffect(() => {
    // 切会话/进草稿时恢复该会话的粘性选择（无记录回落上次使用）
    const map = loadModelMap()
    setModel(map[convId ?? ''] ?? localStorage.getItem(LS_MODEL_LAST) ?? undefined)
  }, [convId])
  const changeModel = useCallback(
    (id: string) => {
      setModel(id)
      localStorage.setItem(LS_MODEL_LAST, id)
      if (convId) {
        const map = loadModelMap()
        map[convId] = id
        localStorage.setItem(LS_MODEL_BY_CONV, JSON.stringify(map))
      }
    },
    [convId],
  )
  // 模型配置（与 InputComposer/SettingsModal 共享 ['settings'] 缓存）：粘性 id 失效自愈用
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    staleTime: 5 * 60_000,
    retry: false,
  })
  // 粘性模型 id 失效自愈：模型被删除/另一窗口改动后，本地存档的 id 已不存在——后端
  // 会静默回落 default，但胶囊显示与实际执行模型脱节。校验失败回落 default 并清粘性
  // 键；settings 未加载（undefined 窗口）跳过，加载后自然补校。
  useEffect(() => {
    if (!settings || !model) return
    if (settings.models.some((m) => m.id === model)) return
    setModel(undefined)
    try {
      localStorage.removeItem(LS_MODEL_LAST)
      const map = loadModelMap()
      if (convId && map[convId]) {
        delete map[convId]
        localStorage.setItem(LS_MODEL_BY_CONV, JSON.stringify(map))
      }
    } catch {
      /* localStorage 不可用不致命 */
    }
  }, [settings, model, convId])
  // HITL 逐项草稿（含问快照：单问=向导 N=1 特例，统一卡内作答）。按 runId 判定
  // 新中断才重置：SSE 重连对账（run.state waiting_input）会 new 一个同 runId 的
  // interrupt 对象，按对象引用重置会把用户已答内容清空
  const [stepIndex, setStepIndex] = useState(0)
  const [stepDrafts, setStepDrafts] = useState<StepDraft[]>([])
  const lastInterruptRunRef = useRef<string | null>(null)
  useEffect(() => {
    const interruptRunId = interrupt?.runId ?? null
    if (interrupt && interruptRunId !== lastInterruptRunRef.current) {
      setStepIndex(0)
      setStepDrafts(interrupt.requests.map(() => ({ picked: [], text: '' })))
    }
    lastInterruptRunRef.current = interruptRunId
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
        // 单选已选中再点 = no-op（toggle 反选会让提交钮莫名回禁用，实测用户会双击确认）
        if (d.picked.includes(opt) && !curMultiple) return cur
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
    async (dir: -1 | 1) => {
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
        // 成功续跑才 acknowledge：失败（网络/非 409）时草稿与 chips 原样保留，可重新提交
        const resumed = await decide(decisions)
        if (fileNote && resumed) acknowledgeUploads(freshFiles.map((f) => f.id))
        return
      }
      setStepIndex(stepIndex + 1)
    },
    [interrupt, stepIndex, stepDrafts, freshFiles, decide, toast, acknowledgeUploads],
  )

  // memo 化 MessageList 的前提：三个 prop 引用都必须稳定（流式 token 期间 messages
  // 来自 react-query 缓存不变、onOpenArtifact 是 setState setter、本值 useMemo）
  const convArtifacts = useMemo(
    () => (convId ? artifacts.filter((a) => a.conversation_id === convId) : []),
    [artifacts, convId],
  )
  // ---- 长会话尾部窗口（INP：切换会话的冷挂载从全量降到尾部）----
  // 首屏只渲染最近一个窗口，「加载更早」逐步扩窗；ChatView 以 convId 为 key 挂载
  // （App），换会话窗口态自动重置。起点经 computeWindowStart 对齐到回合头，保证
  // MessageList 的回答隐藏/回合分组在窗口边界不错位。
  const [windowCount, setWindowCount] = useState(MESSAGE_WINDOW)
  const windowStart = useMemo(() => computeWindowStart(messages, windowCount), [messages, windowCount])
  const visibleMessages = useMemo(() => messages.slice(windowStart), [messages, windowStart])
  // 窗外 run 的产物卡不进转录：placeArtifacts 匹配不到回合会兜底到可见窗口末尾，
  // 位置错乱（旧产物浮到最新消息下面）；无 run_id 的产物保持尾部兜底不变，扩窗后
  // 窗外产物自然回归各自回合之后。
  const windowArtifacts = useMemo(() => {
    if (windowStart === 0) return convArtifacts
    const rids = new Set<string>()
    for (let i = windowStart; i < messages.length; i++) {
      const rid = messages[i].run_id
      if (rid) rids.add(rid)
    }
    return convArtifacts.filter((a) => !a.source?.run_id || rids.has(a.source.run_id))
  }, [convArtifacts, messages, windowStart])
  // 「加载更早」的滚动锚定：扩窗在顶部插入内容，按 scrollHeight 差值补偿 scrollTop
  // 让视口停在原消息上（不跳顶、不误触贴底）
  const expandAnchor = useRef<{ start: number; height: number } | null>(null)
  const loadEarlier = useCallback(() => {
    const el = scrollRef.current
    if (el) expandAnchor.current = { start: windowStart, height: el.scrollHeight }
    setWindowCount((c) => c + MESSAGE_WINDOW)
  }, [windowStart])
  useLayoutEffect(() => {
    const el = scrollRef.current
    const prev = expandAnchor.current
    if (!el || !prev || prev.start === windowStart) return
    el.scrollTop += el.scrollHeight - prev.height
    expandAnchor.current = null
    atBottom.current = false
  }, [windowStart])
  // isError 不能掉进欢迎页空态：加载失败是错误不是「没有消息」
  const empty = messages.length === 0 && !running && !isLoading && !isError

  const doSend = useCallback(
    async (text: string) => {
      if (!convId) {
        if (!pickedTaskId) {
          toast('请先选择所属任务', 'error')
          // reject：InputComposer 的契约是 onSend 失败即保留输入（不清空、不 acknowledge），
          // 正常 resolve 会把用户已打的文字清掉
          throw new Error('请先选择所属任务')
        }
        // 建会话失败：toast 已提示；向上抛让 InputComposer 保留输入（不清空、不 acknowledge）
        // 首发消息由建会话后的 initialSend effect 发出，届时带上当前思考档位
        try {
          await onRequestCreate(text, pickedTaskId)
        } catch (e) {
          toast(e instanceof Error ? e.message : String(e), 'error')
          throw e
        }
        return
      }
      if (running) return
      // 失败向上抛：useRun 已置错误卡，InputComposer 据此保留输入与新上传 chips
      await send(text, thinking, model)
    },
    [convId, running, send, onRequestCreate, pickedTaskId, thinking, model, toast],
  )

  // 无会话时 App 转发首发消息。StrictMode 开发模式会把本 effect 跑两遍
  // （挂载→cleanup→重挂载），无守卫会双发 POST，第二发撞 409「已有进行中的任务」
  const sentInitialRef = useRef<string | null>(null)
  useEffect(() => {
    if (initialSend) {
      setPrompt(initialSend)
      if (convId && sentInitialRef.current !== initialSend) {
        sentInitialRef.current = initialSend
        // 发送成功后清空输入框：草稿页首发的合成消息（如「我上传了文件：…」）
        // 不再整场会话残留在 composer 里；失败则保留文本（InputComposer 亦不清空，
        // 错误卡带重试），用户可改可重发
        void doSend(initialSend)
          .then(() => setPrompt(null))
          .catch(() => {})
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

  // 流式自动贴底；用户上滚则停止贴底。rAF 合并同帧多次触发：scrollHeight 读取
  // 强制同步布局，一帧最多一次（token 突发时不再逐 token 打断合成器）
  useEffect(() => {
    if (!atBottom.current) return
    const raf = requestAnimationFrame(() => {
      const el = scrollRef.current
      if (el) el.scrollTo({ top: el.scrollHeight })
    })
    return () => cancelAnimationFrame(raf)
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
      {/* min-h-0：本层与 UploadDropzone 层都是 .main（flex column，上邻 50px chat-head）里的
          h-full flex item，缺 min-h-0 时依赖默认 shrink 被压缩，异常场景会把 composer
          连同底栏推出视口下缘被 overflow:hidden 裁掉（表现为发送钮/文件 chip 点不到） */}
      <div className="relative flex h-full min-h-0 w-full flex-col">
        <div className="relative min-h-0 flex-1">
          <div ref={scrollRef} onScroll={handleScroll} className="chat-scroll h-full">
            <div className="chat">
              {isLoading && <MessageSkeletons />}
              {isError && (
                <ErrorCard
                  message={`消息加载失败：${messagesError instanceof Error ? messagesError.message : String(messagesError)}`}
                  retryText="重试"
                  onRetry={() => void refetchMessages()}
                />
              )}
              {empty && (
                <WelcomeScreen
                  hasTask={!!convId || !!pickedTaskId}
                  onPickFile={openFilePicker}
                  onPrompt={fillPrompt}
                />
              )}
              {/* 子树边界：一条坏历史数据只降级消息区占位卡，不再打到根级整窗错误页 */}
              <ErrorBoundary compact resetKey={convId ?? 'root'}>
                {windowStart > 0 && (
                  <div className="flex justify-center py-1">
                    <button
                      type="button"
                      className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground hover:text-foreground"
                      onClick={loadEarlier}
                    >
                      {`加载更早的消息（还有 ${windowStart} 条）`}
                    </button>
                  </div>
                )}
                <MessageList
                  messages={visibleMessages}
                  convArtifacts={windowArtifacts}
                  onOpenArtifact={onOpenArtifact}
                  onOpenWorkbench={onOpenWorkbench}
                  hiddenPauseRunId={liveRunId}
                />
              </ErrorBoundary>
              {(running || interrupt) && (
                <RunMessage
                  running={running}
                  paused={!!interrupt && !running}
                  startedAt={startedAt}
                  tools={tools}
                  todos={todos}
                  done={done}
                  total={total}
                  text={streamText}
                  reasoningText={reasoningText}
                  pauseNarration={pauseNarration}
                  continuation={continuation}
                  continuationKind={continuationKind}
                  continuationAnswer={continuationAnswer}
                />
              )}
              {interrupt && !running && (
                <div className="turn-attach">
                  {wizardMode ? (
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
                      onOpenWorkbench={onOpenWorkbench}
                    />
                  ) : (
                    <InterruptCard
                      requests={interrupt.requests}
                      onDecide={(d) => void decide(d)}
                      onOpenWorkbench={onOpenWorkbench}
                    />
                  )}
                </div>
              )}
              {error && (
                <ErrorCard
                  message={error}
                  cancelled={errorCode === 'cancelled'}
                  retryText={retryText}
                  onRetry={() => void doSend(retryText).catch(() => {})}
                />
              )}
            </div>
          </div>
          {/* 回到底部：浮在滚动区底部（不占布局流——在流内会把 composer 整体下压 38px） */}
          {showJump && (
            <button
              type="button"
              onClick={jumpToBottom}
              className="absolute bottom-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-md hover:text-foreground"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              回到底部
            </button>
          )}
        </div>
        <InputComposer
          running={running}
          waiting={!!interrupt}
          waitingHint={waitingHint}
          disabled={!!interrupt}
          stopping={stopping}
          onSend={doSend}
          value={prompt}
          onChange={setPrompt}
          thinking={thinking}
          onThinkingChange={changeThinking}
          model={model}
          onModelChange={changeModel}
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

/** 运行中主气泡的状态行文案：随实际活动切换（此前恒「正在思考…」——子代理长跑
 *  4 分钟期间主表面纹丝不动，读起来像卡死）。子代理在跑=带完成计数；普通工具
 *  在跑=工具中文名；都没有时按 startingSubagents 区分「子代理启动中」（审批续跑
 *  已批准、首个子代理事件未达）与「正在思考」。 */
function hasTaskStep(steps: RunState['tools']): boolean {
  return steps.some((step) => step.tool === 'task' || hasTaskStep(step.children))
}

function activeStatusLabel(tools: RunState['tools'], startingSubagents = false): string {
  let subDone = 0
  let subActive = false
  let plainTool: string | null = null
  const walk = (steps: RunState['tools']) => {
    for (const s of steps) {
      if (s.status === 'running') {
        if (s.tool === 'task') {
          subActive = true
          for (const c of s.children) if (c.status !== 'running') subDone++
        } else if (!plainTool) {
          plainTool = s.tool
        }
      }
      if (s.children.length > 0) walk(s.children)
    }
  }
  walk(tools)
  if (subActive) return `子代理执行中 · 已完成 ${subDone} 项`
  if (plainTool) return `正在执行 · ${toolDisplayName(plainTool)}`
  return startingSubagents ? '子代理启动中…' : '正在思考…'
}

/** 运行中的助手消息（活卡）：头像 + 状态 + 执行过程（Reasoning 折叠）+ 任务清单时间线（Steps）+ 流式正文。
 *  一张活卡贯穿 run 生命周期：running 累积 → ask_human 原地冻结（paused=true：胶囊转
 *  「等待你的输入」、折叠头转「已暂停 · N 步」、正文/思考/工具树全保留，pauseNarration
 *  是暂停时未封口的正文旁白行）→ 裁决后同一实例解冻续跑（React 不卸载，手动展开的
 *  折叠态全程保持）→ 完成时与落库最终消息同帧原子替换（settle-after-messages 时序）。
 *  continuationAnswer 是刚提交的问答回答--转录里不再有回答气泡，续跑期间在此显示一行
 *  防「提交后答案消失」的空窗，最终消息到达后随本占位组件一起退场。 */
function RunMessage({
  running,
  paused,
  startedAt,
  tools,
  todos,
  done,
  total,
  text,
  reasoningText,
  pauseNarration,
  continuation,
  continuationKind,
  continuationAnswer,
}: {
  running: boolean
  /** ask_human 等待裁决：活卡冻结呈现（不转圈、不计时，动作入口是下方提问卡） */
  paused: boolean
  startedAt: number | null
  tools: RunState['tools']
  todos: RunState['todos']
  done: number
  total: number
  text: string
  reasoningText: string
  /** 暂停时未封口的正文（settle-interrupt 移入）：冻结/续跑期间渲染为过程区顶部旁白行 */
  pauseNarration: string
  continuation: boolean
  continuationKind: RunState['continuationKind']
  continuationAnswer: string
}) {
  // 状态行的三次 O(steps) 树遍历只在 tools 变化时重算（正文 token 流期间跳过）
  const hasSubagents = useMemo(() => hasTaskStep(tools), [tools])
  const startingSubagents = useMemo(
    () =>
      continuationKind === 'subagents' &&
      hasSubagents &&
      !tools.some((step) => step.children.length > 0 || step.reasoning),
    [continuationKind, hasSubagents, tools],
  )
  const label = useMemo(() => activeStatusLabel(tools, startingSubagents), [tools, startingSubagents])
  // 流式渲染节流：state 仍是精确值，渲染层把 markdown 重解析合并到每 200ms 一档
  // （历史消息已被 ChatMessage memo 隔离，此处只剩流式正文与思考两块热路径）
  const shownText = useThrottledValue(text)
  const shownReasoning = useThrottledValue(reasoningText)
  return (
    <WMessage
      role="assistant"
      name="Tender Agent"
      avatar={<div className="msg-avatar">T</div>}
      status={
        paused ? (
          <span className="inline-flex items-center gap-1.5">
            <CirclePause className="size-3.5" /> 等待你的输入
          </span>
        ) : (
          <>
            <Loader variant="dots" size="sm" /> {continuation ? '继续执行' : '执行中'}
            {startedAt && <Duration startedAt={startedAt} className="ml-1" />}
          </>
        )
      }
    >
      {continuation && continuationAnswer && (
        <div className="turn-chip mb-1.5">你的回答：{continuationAnswer.replace(/^已选：/, '')}</div>
      )}
      {(reasoningText ||
        tools.length > 0 ||
        todos.length > 0 ||
        pauseNarration.trim() ||
        (continuation && hasSubagents)) && (
        <Reasoning isStreaming={running} className="mb-1.5">
          <ReasoningTrigger className="text-sm text-muted-foreground">
            {paused ? (
              `已暂停${tools.length ? ` · ${tools.length} 步` : ''}`
            ) : running ? (
              <TextShimmer>执行过程</TextShimmer>
            ) : (
              '执行过程'
            )}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2 space-y-2">
            {pauseNarration.trim() && <NarrationLine text={pauseNarration} />}
            <RunTrace tools={tools} todos={todos} done={done} total={total} />
            {/* 思考块 = 当前未封口段（历史思考已按 tool.called 封段沉入步骤行），
                放步骤区之后保持时序：先看到已发生的工具流水，再看到正在增长的思考 */}
            {shownReasoning && <DeepThinking text={shownReasoning} isStreaming={running} autoFollow />}
          </ReasoningContent>
        </Reasoning>
      )}
      {!paused && (
        <div className="bubble">
          {shownText ? (
            <>
              <MemoMarkdown text={shownText} components={markdownComponents} />
              <span className="caret-blink ml-0.5 inline-block h-[1.15em] w-0.5 translate-y-[0.2em] bg-primary" />
            </>
          ) : (
            <ThinkingBar text={label} />
          )}
        </div>
      )}
    </WMessage>
  )
}

/** 消息列表 → 渲染节点：连续同 run_id 的消息聚合为一个回合组（单回合聚合——
 *  HITL 暂停段+续跑段是同一动作的连续，不是两条独立消息）；run_id 为空的
 *  旧消息各自独立。日期分隔条只出现在组与组之间。
 *  HITL respond 回答消息不渲染气泡（痕迹收进过程卡的问答组，见 hitlMessage）。
 *  活卡存续期间（hiddenPauseRunId 非空）该 run 的暂停/中断半截消息整体不渲染——
 *  一张活卡贯穿 run 生命周期，终态后回到转录被最终/中断消息吸收。
 *  memo：流式 token 期间 props 引用稳定 → 整个列表（含分组装配）跳过重渲染，
 *  每 token 只剩 RunMessage 一个热路径组件。 */
const MessageList = memo(function MessageList({
  messages,
  convArtifacts,
  onOpenArtifact,
  onOpenWorkbench,
  hiddenPauseRunId,
}: {
  messages: Message[]
  convArtifacts: Artifact[]
  onOpenArtifact: (id: string) => void
  /** 「本轮文件」chip -> 工作台面板（引用须稳定：浅比较 memo） */
  onOpenWorkbench: (path: string) => void
  /** 活卡存续的 run id（running 或等待输入）；null = 无活卡（终态），不隐藏任何消息 */
  hiddenPauseRunId?: string | null
}) {
  type Item = { kind: 'solo'; m: Message } | { kind: 'group'; runId: string; items: Message[] }
  const items: Item[] = []
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]
    if (isRespondAnswer(messages, i)) continue // 回答不占转录（答案在过程卡问答组里）
    if (isLivePauseMessage(m, hiddenPauseRunId)) continue // 活卡期间暂停消息不渲染独立卡
    const rid = m.run_id ?? null
    const last = items[items.length - 1]
    if (rid && last?.kind === 'group' && last.runId === rid) {
      last.items.push(m)
    } else if (rid) {
      items.push({ kind: 'group', runId: rid, items: [m] })
    } else {
      items.push({ kind: 'solo', m })
    }
  }
  // 产物卡挂回发布它的回合（placeArtifacts）：恒追加转录末尾的话，新消息一插
  // 进来产物卡就会被挤到用户气泡之后（2026-09-06 实测错位）
  const placed = placeArtifacts(
    convArtifacts,
    items.flatMap((it) => (it.kind === 'group' ? [it.runId] : [])),
  )

  const nodes: React.ReactNode[] = []
  let lastDay = ''
  const pushDay = (m: Message) => {
    const day = formatDay(m.created_at)
    if (day !== lastDay) {
      lastDay = day
      nodes.push(
        <div key={`day-${m.id}`} className="flex justify-center">
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{day}</span>
        </div>,
      )
    }
  }
  for (const item of items) {
    if (item.kind === 'solo') {
      pushDay(item.m)
      nodes.push(<ChatMessage key={item.m.id} message={item.m} onOpenWorkbench={onOpenWorkbench} />)
      continue
    }
    pushDay(item.items[0])
    // 组内装配（单回合一张过程卡）：
    // - 带暂停/中断标记的 assistant 段若后面还有 assistant 段（最终回复已落库），
    //   自身整体不渲染——旁白与标记上提进最终段的卡片，避免「已暂停空壳卡 + 无头
    //   最终段」读成两条消息（2026-08-30 实测反馈）；标记段是最后一段（等待中/
    //   无产出终止）时照常自渲染，它是回合头与问答卡的载体。
    // - 首个实际渲染的 assistant 段带回合头（头像/名字），其余 attach。
    const hasLaterAssistant: boolean[] = Array.from({ length: item.items.length }, () => false)
    let seen = false
    for (let k = item.items.length - 1; k >= 0; k--) {
      hasLaterAssistant[k] = seen
      if (item.items[k].role === 'assistant') seen = true
    }
    let seenAssistant = false
    let hoist: { narration: string[]; marker: 'pause' | 'interrupted' } | null = null
    nodes.push(
      <div key={`turn-${item.runId}`} className="turn-group">
        {item.items.map((m, k) => {
          if (m.role === 'user') return <ChatMessage key={m.id} message={m} />
          const split = splitMarker(m.content)
          if (split.marker && hasLaterAssistant[k]) {
            hoist = hoist ?? { narration: [], marker: split.marker }
            if (split.body.trim()) hoist.narration.push(split.body.trim())
            return null
          }
          const attach = seenAssistant
          seenAssistant = true
          const lifted = hoist
          hoist = null
          return (
            <ChatMessage
              key={m.id}
              message={m}
              attach={attach}
              pauseNarration={lifted?.narration.join('\n\n')}
              pauseMarker={lifted?.marker}
              onOpenWorkbench={onOpenWorkbench}
            />
          )
        })}
      </div>,
    )
    // 该回合发布的产物卡紧随其后（旧数据/活卡进行中的 run 落尾部兜底）
    for (const a of placed.byRun.get(item.runId) ?? []) {
      nodes.push(<ArtifactCard key={a.artifact_id} artifact={a} onOpen={onOpenArtifact} />)
    }
  }
  for (const a of placed.tail) {
    nodes.push(<ArtifactCard key={a.artifact_id} artifact={a} onOpen={onOpenArtifact} />)
  }
  return <>{nodes}</>
})

/** 错误卡。cancelled=true（用户主动停止，契约 additive code）：中性灰呈现 +
 *  「重新执行」——自己停的不算出错，不与真实错误共用红色。 */
function ErrorCard({
  message,
  cancelled = false,
  retryText,
  onRetry,
}: {
  message: string
  cancelled?: boolean
  retryText: string
  onRetry: () => void
}) {
  return (
    <div
      className={
        cancelled
          ? 'rounded-lg border border-line bg-secondary px-3 py-2 text-sm text-muted-foreground'
          : 'rounded-lg border border-error/50 bg-error/5 px-3 py-2 text-sm text-error'
      }
    >
      {message}
      {retryText.trim() && (
        <button type="button" className="ml-2 hover:underline" onClick={onRetry}>
          {cancelled ? '重新执行' : '重试'}
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
