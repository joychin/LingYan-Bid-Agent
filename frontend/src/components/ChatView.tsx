import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDown } from 'lucide-react'
import { UploadDropzone } from '@/components/UploadDropzone'
import { ChatMessage, markdownComponents } from '@/components/ChatMessage'
import { Loader } from '@/components/ai/Loader'
import { ThinkingBar } from '@/components/ai/ThinkingBar'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { ChainOfThought, ChainOfThoughtContent, ChainOfThoughtStep, ChainOfThoughtTrigger } from '@/components/ai/ChainOfThought'
import { Steps, StepsContent, StepsItem, StepsTrigger } from '@/components/ai/Steps'
import { Message as WMessage } from '@/components/workspace/Message'
import { ArtifactCard } from '@/components/ArtifactCard'
import { WelcomeScreen } from '@/components/WelcomeScreen'
import { InputComposer } from '@/components/InputComposer'
import { useMessages } from '@/hooks/useMessages'
import { useRun } from '@/hooks/useRun'
import type { RunState } from '@/hooks/useRun'
import { useArtifacts } from '@/hooks/useArtifacts'
import { useFileUpload } from '@/context/FileUpload'
import { cn, formatDay } from '@/lib/utils'
import type { Artifact, Message } from '@/api/client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** 工具显示名映射（§6，写死在前端；未映射工具直接显示原始名）。 */
const TOOL_DISPLAY: Record<string, string> = {
  convert_tender: '转换招标文件',
  extract_toc: '抽取文档大纲',
  build_tender: '组装产物',
}

export function ChatView({
  convId,
  onOpenArtifact,
  initialSend,
  onRequestCreate,
}: {
  convId: string | null
  onOpenArtifact: (id: string) => void
  initialSend: string | null
  onRequestCreate: (text: string) => void
}) {
  const { data: messages = [], isLoading } = useMessages(convId)
  const { running, streamText, reasoningText, tools, todos, done, total, error, lastSent, send } = useRun(convId)
  const { data: artifacts = [] } = useArtifacts()
  const { openFilePicker } = useFileUpload()
  const scrollRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const [prompt, setPrompt] = useState<string | null>(initialSend)

  const convArtifacts = convId ? artifacts.filter((a) => a.conversation_id === convId) : []
  const empty = messages.length === 0 && !running && !isLoading

  const doSend = useCallback(
    async (text: string) => {
      if (!convId) {
        await onRequestCreate(text)
        return
      }
      if (!text.trim() || running) return
      try {
        await send(text)
      } catch {
        /* 发送失败：由 useRun 展示错误，输入框内容由 InputComposer 保留 */
      }
    },
    [convId, running, send, onRequestCreate],
  )

  // 无会话时 App 转发首发消息
  useEffect(() => {
    if (initialSend) {
      setPrompt(initialSend)
      if (convId) void doSend(initialSend)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSend, convId])

  const fillPrompt = (text: string) => setPrompt(text)

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

  return (
    <UploadDropzone>
      <div className="relative flex h-full w-full flex-col">
        <div ref={scrollRef} onScroll={handleScroll} className="chat-scroll">
          <div className="chat">
            {isLoading && <MessageSkeletons />}
            {empty && <WelcomeScreen onPickFile={openFilePicker} onPrompt={fillPrompt} />}
            <MessageList messages={messages} convArtifacts={convArtifacts} onOpenArtifact={onOpenArtifact} />
            {running && (
              <RunMessage running={running} tools={tools} todos={todos} done={done} total={total} text={streamText} reasoningText={reasoningText} />
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
          onSend={doSend}
          value={prompt}
          onChange={setPrompt}
        />
      </div>
    </UploadDropzone>
  )
}

/** 运行中的助手消息：头像 + 状态 + 执行过程（Reasoning 折叠）+ 任务清单时间线（Steps）+ 流式正文。 */
function RunMessage({
  running,
  tools,
  todos,
  done,
  total,
  text,
  reasoningText,
}: {
  running: boolean
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
            {tools.length > 0 && (
              <ChainOfThought>
                {tools.map((s) => {
                  const displayName = TOOL_DISPLAY[s.tool] ?? s.tool
                  const statusText =
                    s.status === 'running' ? '执行中' : s.status === 'error' ? '失败' : '成功'
                  return (
                    <ChainOfThoughtStep key={s.id} defaultOpen={s.status !== 'done'}>
                      <ChainOfThoughtTrigger>
                        {displayName} · {statusText}
                      </ChainOfThoughtTrigger>
                      <ChainOfThoughtContent>
                        {s.status === 'error' && s.error ? (
                          <div className="art-result" style={{ color: 'var(--error)' }}>
                            {s.error}
                          </div>
                        ) : s.summary ? (
                          <div className="art-result">{s.summary}</div>
                        ) : null}
                      </ChainOfThoughtContent>
                    </ChainOfThoughtStep>
                  )
                })}
              </ChainOfThought>
            )}
            {todos.length > 0 && (
              <Steps defaultOpen className="mt-2">
                <StepsTrigger className="text-xs">
                  任务清单 · {done} / {total} 完成
                </StepsTrigger>
                <StepsContent>
                  {todos.map((t, i) => {
                    const isDone = t.status === 'completed'
                    const isDoing = t.status === 'in_progress'
                    return (
                      <StepsItem key={i}>
                        <span className="flex items-center gap-2">
                          <span
                            className={cn(
                              'flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px]',
                              isDone
                                ? 'bg-primary text-primary-foreground'
                                : isDoing
                                  ? 'bg-muted text-muted-foreground'
                                  : 'border border-line text-transparent',
                            )}
                          >
                            {isDone ? '✓' : isDoing ? '●' : '○'}
                          </span>
                          <span className={cn(isDone && 'text-muted-foreground/70 line-through')}>
                            {t.content}
                          </span>
                        </span>
                      </StepsItem>
                    )
                  })}
                </StepsContent>
              </Steps>
            )}
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
    nodes.push(<ArtifactCard key={a.id} artifact={a} onOpen={onOpenArtifact} />)
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
