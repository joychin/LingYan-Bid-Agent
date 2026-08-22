import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '@/api/client'
import { cn } from '@/lib/utils'

const markdownComponents = {
  table: (props: React.ComponentPropsWithoutRef<'table'>) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  th: (props: React.ComponentPropsWithoutRef<'th'>) => (
    <th className="border px-3 py-1.5 text-left font-semibold" {...props} />
  ),
  td: (props: React.ComponentPropsWithoutRef<'td'>) => (
    <td className="border px-3 py-1.5 align-top" {...props} />
  ),
  a: (props: React.ComponentPropsWithoutRef<'a'>) => (
    <a className="text-blue-600 underline" target="_blank" rel="noreferrer" {...props} />
  ),
  code: (props: React.ComponentPropsWithoutRef<'code'>) => (
    <code className="rounded bg-muted px-1 py-0.5 text-[0.9em]" {...props} />
  ),
}

export function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-lg px-4 py-2.5 text-sm leading-relaxed',
          isUser ? 'bg-primary text-primary-foreground' : 'border bg-card text-card-foreground',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}

/** 正在生成的 assistant 气泡（累积 SSE token）。 */
export function StreamingMessage({ text }: { text: string }) {
  return (
    <div className="flex w-full justify-start">
      <div className="max-w-[85%] rounded-lg border bg-card px-4 py-2.5 text-sm leading-relaxed">
        {text ? (
          <div className="prose-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {text}
            </ReactMarkdown>
          </div>
        ) : (
          <span className="text-muted-foreground">正在思考…</span>
        )}
      </div>
    </div>
  )
}
