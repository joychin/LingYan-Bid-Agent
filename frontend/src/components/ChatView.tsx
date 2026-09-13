import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSettings } from '@/api/client'
import { ArrowDown, CirclePause, Paperclip } from 'lucide-react'
import { UploadDropzone } from '@/components/UploadDropzone'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ChatMessage, DeepThinking, type InterruptAction } from '@/components/ChatMessage'
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
import { TraceLiveContext, TRACE_LIVE_TEXT_CAP } from '@/components/ai/traceLive'
import { TodoPanel } from '@/components/ai/TodoPanel'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { toolDisplayName } from '@/components/ai/toolDisplay'
import { Message as WMessage } from '@/components/workspace/Message'
import { ArtifactCard } from '@/components/ArtifactCard'
import { placeArtifacts } from '@/lib/artifactPlacement'
import { capStreamingText } from '@/lib/streamTextCap'
import { WelcomeScreen } from '@/components/WelcomeScreen'
import { InputComposer } from '@/components/InputComposer'
import { UploadChips } from '@/components/UploadChips'
import { useMessages } from '@/hooks/useMessages'
import { useRun } from '@/hooks/useRun'
import { useThrottledValue } from '@/hooks/useThrottledValue'
import type { RunState } from '@/hooks/useRun'
import type { DeliverableSignal } from '@/api/sse'
import { useArtifacts } from '@/hooks/useArtifacts'
import { useConversations } from '@/hooks/useConversations'
import { taskOfConversation, useTasks } from '@/hooks/useTasks'
import { useFileUpload } from '@/context/FileUpload'
import { useToast } from '@/context/Toast'
import { formatDay, cn } from '@/lib/utils'
import { isLivePauseMessage, isRespondAnswer, lastInstructionText, splitMarker } from '@/lib/hitlMessage'
import { computeWindowStart } from '@/lib/messageWindow'
import { getLatestRun } from '@/api/client'
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
  onPresentDeliverable,
  initialFiles,
  onInitialFilesConsumed,
  onOpenSettings,
}: {
  /** 所属会话（「任务即房间」2026-09-13：本组件只在有会话时挂载；类型保留 null 容忍是
   *  为了少动全文件的空值守卫，null 分支实际不可达） */
  convId: string | null
  onOpenArtifact: (id: string) => void
  /** 「本轮文件」chip -> 打开工作台面板编辑该文件（path 相对 <task>/work/） */
  onOpenWorkbench: (path: string) => void
  /** 交付物呈现信号（deliverable.created，产出即开）：App 侧守卫（面板空闲/
   *  自动内容才开）后打开产物面板——声明权在产出侧，前端零文件名/业务类型规则 */
  onPresentDeliverable: (d: DeliverableSignal) => void
  /** 建任务弹窗转交的文件（创建成功后在此上传到新任务）：等 taskScope 就位后
   *  dropFiles 一次；消费后回调 App 清空来源（消费即清源，见下 effect） */
  initialFiles?: File[]
  /** initialFiles 已消费（上传已发起）——App 据此清空 pendingFiles，任何重挂载
   *  路径都不会再喂一次（＋新会话/进入任务/切视图往返） */
  onInitialFilesConsumed?: () => void
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
    retrying,
    lastInstruction,
    continuationAnswer,
    pauseNarration,
    interrupt,
    continuation,
    continuationKind,
    traceSyncIssue,
    send,
    decide,
    cancel,
    continueRun,
    resyncTrace,
  } = useRun(convId, { onDeliverable: onPresentDeliverable })
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
  const { toast } = useToast()
  const { setTaskScope, uploads, taskScope, acknowledgeUploads, openFilePicker, dropFiles } = useFileUpload()
  const scrollRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const [prompt, setPrompt] = useState<string | null>(null)
  // 思考档位（reasoning_effort）：随每条消息发送、localStorage 记忆上次选择（默认低）。
  // ChatView 持有而非 InputComposer：重试/续发等编程式发送也要带上档位
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

  // 上传归属任务（§16 任务级文件区）：选中会话→其所属任务
  useEffect(() => {
    const conv = convId ? conversations.find((c) => c.id === convId) : null
    setTaskScope(conv?.task_id ?? null)
  }, [convId, conversations, setTaskScope])

  // 当前任务（空会话欢迎语/输入框占位符的任务感知文案用）
  const currentTask = useMemo(
    () => taskOfConversation(tasks, conversations, convId),
    [tasks, conversations, convId],
  )

  // 建任务弹窗转交的文件：等 taskScope 就位（建会话后 conversations 失效重拉可能晚到，
  // taskScope 先 null 后有值）再上传一次。消费后回调 App 清空 pendingFiles（消费即
  // 清源）——实例级 ref 只能防本实例重跑，换 key 重挂（＋新会话/切视图往返）会复位，
  // 只有清来源才能保证任何重挂载都不会二次上传。ref 仍留（防 StrictMode 双跑双传）。
  // dropFiles 走 FileUpload 既有管线（并行上传+进度 chips+失败可重试）。
  const droppedInitialRef = useRef(false)
  useEffect(() => {
    if (droppedInitialRef.current || !initialFiles || initialFiles.length === 0) return
    if (!taskScope) return
    droppedInitialRef.current = true
    dropFiles(initialFiles)
    onInitialFilesConsumed?.()
  }, [initialFiles, taskScope, dropFiles, onInitialFilesConsumed])

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
        // 上传告知只进 decisions、不落草稿（2026-09-10 review：失败重试保留草稿
        // 可重提——此前拼进 drafts[stepIndex].text，重试会重复拼接「我上传了文件」）
        const fileNote =
          freshFiles.length > 0 && isQuestion(reqs[stepIndex])
            ? `我上传了文件：${freshFiles.map((f) => f.name).join('、')}，请查收处理`
            : ''
        const decisions = reqs.map((r, i) => {
          const d = drafts[i]
          if (isQuestion(r)) {
            const text =
              i === stepIndex && fileNote
                ? [d.text.trim(), fileNote].filter(Boolean).join('\n')
                : d.text.trim()
            return {
              type: 'respond' as const,
              message: [d.picked.length > 0 ? `已选：${d.picked.join('；')}` : '', text]
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
  // 活卡 run 的产物卡活卡期间不进转录（2026-09-13 两次实测反馈收束）：活卡存续时
  // 该回合在转录里只有一张执行卡，产物卡落转录尾=插在用户气泡与执行卡之间，落
  // 执行卡之后=挂在还在输出的 LLM 卡片底下，放哪都读成错位。发布瞬间已有
  // deliverable.created 产出即开 + 右栏产物面板常驻兜底，转录卡等 run 终态后随
  // 回合落位（最终回复之后）自然现身——与暂停消息「活卡期间隐藏、终态回归」同一条规则
  const transcriptArtifacts = useMemo(
    () => (liveRunId ? windowArtifacts.filter((a) => a.source?.run_id !== liveRunId) : windowArtifacts),
    [windowArtifacts, liveRunId],
  )
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
      if (!convId || running) return
      // 失败向上抛：useRun 已置错误卡，InputComposer 据此保留输入与新上传 chips
      await send(text, thinking, model)
    },
    [convId, running, send, thinking, model],
  )

  // 历史中断回合的一键续接入口（2026-09-12）：错误卡是内存态、刷新即消失，转录里
  // 最后一个「已中断」回合给出口（MessageList 定位目标消息）。引用须稳定
  // （MessageList/ChatMessage 均 memo）。error 卡可见时不挂（卡上已有同款按钮，
  // 避免双入口）；运行/等待/加载中不挂。latest run 定性可续时升级为「从断点继续」
  // （不重发消息、已完成的工作不重跑），否则维持「重新执行」。
  const lastTurnInterrupted = useMemo(() => {
    const last = messages[messages.length - 1]
    return !!last && last.role === 'assistant' && splitMarker(last.content).marker === 'interrupted'
  }, [messages])
  const { data: latestRun } = useQuery({
    queryKey: ['runs', 'latest', convId],
    queryFn: () => getLatestRun(convId!),
    enabled: !!convId && lastTurnInterrupted && !running && !interrupt && !error,
    staleTime: 10_000,
    retry: false,
  })
  const interruptAction = useMemo<InterruptAction | null>(() => {
    if (running || interrupt || error || isLoading) return null
    const last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant' || splitMarker(last.content).marker !== 'interrupted') {
      return null
    }
    const run = latestRun?.run ?? null
    if (
      run &&
      run.id === last.run_id &&
      run.status === 'error' &&
      run.error_code &&
      RESUMABLE_ERROR_CODES.includes(run.error_code)
    ) {
      return { label: '从断点继续', onRun: () => void continueRun(run.id) }
    }
    const text = lastInstruction || lastInstructionText(messages)
    if (!text.trim()) return null
    return { label: '重新执行', onRun: () => void doSend(text).catch(() => {}) }
  }, [
    running,
    interrupt,
    error,
    isLoading,
    messages,
    latestRun,
    lastInstruction,
    doSend,
    continueRun,
  ])

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

  return (
    <UploadDropzone>
      {/* min-h-0：本层与 UploadDropzone 层都是 .main（flex column，上邻 50px chat-head）里的
          h-full flex item，缺 min-h-0 时依赖默认 shrink 被压缩，异常场景会把 composer
          连同底栏推出视口下缘被 overflow:hidden 裁掉（表现为发送钮/文件 chip 点不到）。
          空会话（欢迎态）：欢迎文案 + 输入框整体垂直居中（内容区 flex-none + justify-center），
          不再是「文案顶上、输入框贴底」。 */}
      <div className={cn('relative flex h-full min-h-0 w-full flex-col', empty && 'justify-center gap-6')}>
        <div className={cn('relative min-h-0', empty ? 'flex-none' : 'flex-1')}>
          <div ref={scrollRef} onScroll={handleScroll} className="chat-scroll h-full">
            <div className="chat">
              {isLoading && <MessageSkeletons />}
              {isError && (
                <ErrorCard
                  message={`消息加载失败：${messagesError instanceof Error ? messagesError.message : String(messagesError)}`}
                  code={null}
                  retryText="重试"
                  onRetry={() => void refetchMessages()}
                />
              )}
              {empty && <WelcomeScreen taskTitle={currentTask?.title} />}
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
                  convArtifacts={transcriptArtifacts}
                  onOpenArtifact={onOpenArtifact}
                  onOpenWorkbench={onOpenWorkbench}
                  hiddenPauseRunId={liveRunId}
                  interruptAction={interruptAction}
                />
              </ErrorBoundary>
              {(running || interrupt) && (
                <RunMessage
                  running={running}
                  paused={!!interrupt && !running}
                  startedAt={startedAt}
                  tools={tools}
                  text={streamText}
                  reasoningText={reasoningText}
                  retrying={retrying}
                  pauseNarration={pauseNarration}
                  continuation={continuation}
                  continuationKind={continuationKind}
                  continuationAnswer={continuationAnswer}
                  traceSyncIssue={traceSyncIssue}
                  onTraceResync={() => resyncTrace()}
                />
              )}
              {error && (
                <ErrorCard
                  message={error}
                  code={errorCode}
                  retryText={retryText}
                  onRetry={() => void doSend(retryText).catch(() => {})}
                  onOpenSettings={onOpenSettings}
                  onContinue={
                    runId && errorCode && RESUMABLE_ERROR_CODES.includes(errorCode)
                      ? () => void continueRun(runId)
                      : undefined
                  }
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
          {/* 任务清单常驻浮层（右上角）：run 存续期显示当前清单，活卡过程区不再内嵌
              清单组（长任务里随卡片被淹没）——无 todo 不出现，终态消失、历史可回看 */}
          {(running || interrupt) && todos.length > 0 && (
            <TodoPanel
              todos={todos}
              done={done}
              total={total}
              running={running}
              paused={!!interrupt && !running}
            />
          )}
        </div>
        {interrupt && !running ? (
          /* HITL 等待期：提问卡原位替换输入框（2026-09-09 拍板方向 A）——回答入口搬到
             输入区，提交/放弃后输入框原位回归；活卡冻结态留在上方消息流，此卡是唯一
             动作入口。上传钮+chips 随行，保住确认门补传补遗能力（提交时 wizardNav 拼
             「我上传了文件：…」）。 */
          <div className="composer">
            <div className="interrupt-host">
              <div className="interrupt-scroll">
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
                    onAbandon={() => void cancel()}
                  />
                ) : (
                  <InterruptCard
                    requests={interrupt.requests}
                    onDecide={(d) => void decide(d)}
                    onOpenWorkbench={onOpenWorkbench}
                    onAbandon={() => void cancel()}
                  />
                )}
              </div>
              <div className="interrupt-upload-row">
                <button
                  type="button"
                  className="composer-plus"
                  title={taskScope ? '上传文件到当前任务' : '请先选择所属任务'}
                  onClick={openFilePicker}
                  disabled={!taskScope}
                >
                  <Paperclip />
                </button>
                <UploadChips />
              </div>
            </div>
          </div>
        ) : (
          <InputComposer
            running={running}
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
            idlePlaceholder={
              currentTask ? `在「${currentTask.title}」中输入消息，可上传招标文件…` : undefined
            }
          />
        )}
      </div>
    </UploadDropzone>
  )
}

/** 运行中主气泡的状态行文案：随实际活动切换（此前恒「正在思考…」——子代理长跑
 *  4 分钟期间主表面纹丝不动，读起来像卡死）。子代理在跑=「子代理执行中」（完成
 *  计数 2026-09-08 删——数字只统计活跃子代理内部步骤、随其完成回落/波间归零，
 *  非累计进度，读起来无规律误导，勿回加）；普通工具在跑=工具中文名；都没有时按
 *  startingSubagents 区分「子代理启动中」（审批续跑已批准、首个子代理事件未达）
 *  与「正在思考」。 */
function hasTaskStep(steps: RunState['tools']): boolean {
  return steps.some((step) => step.tool === 'task' || hasTaskStep(step.children))
}

function activeStatusLabel(tools: RunState['tools'], startingSubagents = false): string {
  let subActive = false
  let plainTool: string | null = null
  const walk = (steps: RunState['tools']) => {
    for (const s of steps) {
      if (s.status === 'running') {
        if (s.tool === 'task') subActive = true
        else if (!plainTool) plainTool = s.tool
      }
      if (s.children.length > 0) walk(s.children)
    }
  }
  walk(tools)
  if (subActive) return '子代理执行中'
  if (plainTool) return `正在执行 · ${toolDisplayName(plainTool)}`
  return startingSubagents ? '子代理启动中…' : '正在思考…'
}

/** 运行中的助手消息（活卡）：头像 + 状态 + 执行过程（Reasoning 折叠）+ 流式正文。
 *  一张活卡贯穿 run 生命周期：running 累积 → ask_human 原地冻结（paused=true：胶囊转
 *  「等待你的输入」、折叠头转「已暂停 · N 步」、正文/思考/工具树全保留，pauseNarration
 *  是暂停时未封口的正文旁白行）→ 裁决后同一实例解冻续跑（React 不卸载，手动展开的
 *  折叠态全程保持）→ 完成时与落库最终消息同帧原子替换（settle-after-messages 时序）。
 *  continuationAnswer 是刚提交的问答回答--转录里不再有回答气泡，续跑期间在此显示一行
 *  防「提交后答案消失」的空窗，最终消息到达后随本占位组件一起退场。
 *  任务清单不在卡内（2026-09-12 提取）：TodoPanel 常驻会话区右上角，见 ChatView。 */
function RunMessage({
  running,
  paused,
  startedAt,
  tools,
  text,
  reasoningText,
  retrying,
  pauseNarration,
  continuation,
  continuationKind,
  continuationAnswer,
  traceSyncIssue,
  onTraceResync,
}: {
  running: boolean
  /** ask_human 等待裁决：活卡冻结呈现（不转圈、不计时，动作入口是下方提问卡） */
  paused: boolean
  startedAt: number | null
  tools: RunState['tools']
  text: string
  reasoningText: string
  /** LLM 瞬时错误自动重试等待期（agent.retry）：正文区显示「正在自动重试」shimmer，
   *  正文已同步清空（与 sidecar cur_text_parts.clear() 对齐）。流恢复即清除。 */
  retrying: RunState['retrying']
  /** 暂停时未封口的正文（settle-interrupt 移入）：冻结/续跑期间渲染为过程区顶部旁白行 */
  pauseNarration: string
  continuation: boolean
  continuationKind: RunState['continuationKind']
  continuationAnswer: string
  /** 过程对账重试后仍失败（2026-09-12）：过程树可能缺步骤/有死步——折叠头标出并给
   *  「重新同步」出口，不再静默赌下一个缺口事件 */
  traceSyncIssue: boolean
  onTraceResync: () => void
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
      name="Swift Agent"
      avatar={<div className="msg-avatar" aria-hidden />}
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
        pauseNarration.trim() ||
        (continuation && hasSubagents)) && (
        <Reasoning isStreaming={running} className="mb-1.5">
          <ReasoningTrigger className="text-sm text-muted-foreground">
            {paused ? (
              `已暂停${tools.length ? ` · ${tools.length} 步` : ''}`
            ) : running ? (
              <TextShimmer>{traceSyncIssue ? '执行过程（可能与实际有出入）' : '执行过程'}</TextShimmer>
            ) : traceSyncIssue ? (
              '执行过程（可能与实际有出入）'
            ) : (
              '执行过程'
            )}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2 space-y-2">
            {/* 活卡语境标记：内部步骤树的子代理思考恒走尾部封顶（run 期内存爬升
                主因之一是陆续完成的子代理卡整段思考常驻 DOM），历史过程区不受影响 */}
            <TraceLiveContext.Provider value={true}>
              {pauseNarration.trim() && (
                <NarrationLine text={capStreamingText(pauseNarration, undefined, '正文').text} />
              )}
              {traceSyncIssue && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>执行过程可能与实际有出入（同步失败）</span>
                  <button type="button" className="hover:underline" onClick={onTraceResync}>
                    重新同步
                  </button>
                </div>
              )}
              <RunTrace tools={tools} />
              {/* 思考块 = 当前未封口段（历史思考已按 tool.called 封段沉入步骤行），
                  放步骤区之后保持时序：先看到已发生的工具流水，再看到正在增长的思考。
                  活卡恒封顶（含暂停冻结态 isStreaming=false）：全文在 run 结束后的
                  历史过程区可见 */}
              {shownReasoning && (
                <DeepThinking
                  text={capStreamingText(shownReasoning, TRACE_LIVE_TEXT_CAP).text}
                  isStreaming={running}
                  autoFollow
                />
              )}
            </TraceLiveContext.Provider>
          </ReasoningContent>
        </Reasoning>
      )}
      {!paused && (
        <div className="bubble">
          {shownText ? (
            <>
              {/* 流式正文同思考流封顶（11GB 修复家族漏网的一处）：尾窗预览，
                  终态后由落库最终消息渲染全文 */}
              <MemoMarkdown
                text={running ? capStreamingText(shownText, undefined, '正文').text : shownText}
                components={markdownComponents}
              />
              <span className="caret-blink ml-0.5 inline-block h-[1.15em] w-0.5 translate-y-[0.2em] bg-primary" />
            </>
          ) : retrying ? (
            // 自动重试等待期（agent.retry）：后台在退避等待（最长 30s/次），不显示成
            // 卡死——服务方不稳的事实直接说给人听
            <TextShimmer className="text-sm">
              {`模型服务不稳，正在自动重试（第 ${retrying.attempt}/${retrying.total} 次）…`}
            </TextShimmer>
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
  interruptAction,
}: {
  messages: Message[]
  convArtifacts: Artifact[]
  onOpenArtifact: (id: string) => void
  /** 「本轮文件」chip -> 打开工作台面板（引用须稳定：浅比较 memo） */
  onOpenWorkbench: (path: string) => void
  /** 活卡存续的 run id（running 或等待输入）；null = 无活卡（终态），不隐藏任何消息 */
  hiddenPauseRunId?: string | null
  /** 中断回合一键续接入口（引用须稳定：useMemo）：挂到转录最后一个「已中断」assistant
   *  消息上——错误卡是内存态、刷新即消失，此前中断会话没有任何续接入口 */
  interruptAction?: InterruptAction | null
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
  // 中断续接入口的目标：转录最后一条消息是带「（任务中断）」标记的 assistant
  // （后续还有消息说明会话已前进，重跑旧指令语义不成立——不挂）
  const lastItem = items[items.length - 1]
  const lastMsg = lastItem
    ? lastItem.kind === 'group'
      ? lastItem.items[lastItem.items.length - 1]
      : lastItem.m
    : null
  const interruptTargetId =
    interruptAction &&
    lastMsg &&
    lastMsg.role === 'assistant' &&
    splitMarker(lastMsg.content).marker === 'interrupted'
      ? lastMsg.id
      : null

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
      nodes.push(
        <ChatMessage
          key={item.m.id}
          message={item.m}
          interruptAction={item.m.id === interruptTargetId ? interruptAction : undefined}
          onOpenWorkbench={onOpenWorkbench}
        />,
      )
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
              interruptAction={m.id === interruptTargetId ? interruptAction : undefined}
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

/** 错误卡。按 code（契约 additive，2026-09-08 取值域扩展）分形态：
 *  - cancelled/interrupted（用户主动停止/sidecar 重启中断）：中性灰 +「重新执行」——
 *    自己停的不算出错，不与真实错误共用红色；
 *  - llm_auth（模型未配置/Key 失效）：红卡 +「去设置」——重试救不了配置问题；
 *  - 其余（llm_unavailable/internal/旧 sidecar 无 code）：红卡 +「重试」。
 *  message 由 sidecar 拼好：首行人话、次行起为服务方/异常原文——按首行换行拆开渲染，
 *  原文降为小字灰（一眼人话、原文可查可复制）。
 *  非程序自身原因的中断（2026-09-12）附一行安抚提示：产出落文件系统（唯一真值），
 *  重开由管线对账跳过已完成部分——长任务用户最大的恐惧是「全部重来」，这层兜底
 *  必须说给人听。internal/无 code 不加（程序自己崩了，没有可承诺的兜底）。 */
const ERROR_RECOVERY_HINT = '中断前已完成的产出都已保存，重新执行会基于现有成果继续，不会从零开始。'

/** 「从断点继续」覆盖的错误定性（与 sidecar db.RESUMABLE_ERROR_CODES 对齐）：
 *  服务重启中断 / 模型服务不稳重试耗尽 / Key 失效欠费（修好配置回来续）。
 *  cancelled 尊重停止意图、internal 续跑大概率原地再错——都不提供。 */
const RESUMABLE_ERROR_CODES: ReadonlyArray<string> = ['interrupted', 'llm_unavailable', 'llm_auth']

function ErrorCard({
  message,
  code,
  retryText,
  onRetry,
  onOpenSettings,
  onContinue,
}: {
  message: string
  code: string | null
  retryText: string
  onRetry: () => void
  /** llm_auth 的「去设置」入口（ChatView 已有设置窗开关回调；可缺省=浏览器无入口场景） */
  onOpenSettings?: () => void
  /** 「从断点继续」（2026-09-12）：code 可续且调用方提供入口时显示为主按钮——
   *  从 checkpoint 续跑，不重发消息、已完成的工作不重跑 */
  onContinue?: () => void
}) {
  const cancelled = code === 'cancelled' || code === 'interrupted'
  const showHint =
    code === 'cancelled' || code === 'interrupted' || code === 'llm_unavailable' || code === 'llm_auth'
  const [headline, ...detailLines] = message.split('\n')
  return (
    <div
      className={
        cancelled
          ? 'rounded-lg border border-line bg-secondary px-3 py-2 text-sm text-muted-foreground'
          : 'rounded-lg border border-error/50 bg-error/5 px-3 py-2 text-sm text-error'
      }
    >
      {headline}
      {detailLines.length > 0 && (
        <div className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {detailLines.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}
      {showHint && <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{ERROR_RECOVERY_HINT}</div>}
      <span className="ml-2 inline-flex gap-2">
        {code === 'llm_auth' && onOpenSettings && (
          <button type="button" className="hover:underline" onClick={onOpenSettings}>
            去设置
          </button>
        )}
        {onContinue && (
          <button type="button" className="font-medium hover:underline" onClick={onContinue}>
            从断点继续
          </button>
        )}
        {retryText.trim() && (
          <button type="button" className="hover:underline" onClick={onRetry}>
            {cancelled ? '重新执行' : '重试'}
          </button>
        )}
      </span>
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
