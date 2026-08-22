import { useEffect, useRef, useState } from 'react'
import { Loader2, SendHorizonal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ChatMessage, StreamingMessage } from '@/components/ChatMessage'
import { ToolTimeline } from '@/components/ToolTimeline'
import { useMessages } from '@/hooks/useMessages'
import { useRun } from '@/hooks/useRun'

export function ChatView({ convId }: { convId: string }) {
  const { data: messages = [], isLoading } = useMessages(convId)
  const { running, streamText, tools, error, send } = useRun(convId)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, streamText, tools])

  const handleSend = async () => {
    const text = input
    if (!text.trim() || running) return
    setInput('')
    try {
      await send(text)
    } catch {
      setInput(text) // 发送失败（409 等）恢复输入内容，错误信息由 useRun 展示
    }
  }

  return (
    <div className="flex h-full flex-1 flex-col">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
        )}
        {messages.length === 0 && !running && (
          <p className="text-center text-sm text-muted-foreground">开始一段新的对话，或发送一份招标文件路径让我分析。</p>
        )}
        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}
        {running && <ToolTimeline tools={tools} />}
        {running && <StreamingMessage text={streamText} />}
        {error && <p className="text-sm text-red-600">出错了：{error}</p>}
      </div>
      <div className="border-t p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            rows={2}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            className="flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button onClick={handleSend} disabled={running || !input.trim()} size="icon">
            <SendHorizonal className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
