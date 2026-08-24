import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, FileText, Paperclip, Square, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useFiles, useDeleteFile } from '@/hooks/useFiles'
import { useFileUpload } from '@/context/FileUpload'
import { useToast } from '@/context/Toast'
import { formatSize, cn } from '@/lib/utils'
import { ModelSelect } from '@/components/workspace/ModelSelect'
import { PromptSuggestionPopover } from '@/components/PromptSuggestionPopover'
import { PROMPT_SUGGESTIONS, type PromptSuggestionItem } from '@/data/promptCatalog'
import { getSettings } from '@/api/client'

const PARSEABLE_EXT = ['.docx', '.doc', '.pdf']

/** Workspace 输入区：圆角 24 输入框（自适应高度）+ 附件钮 + 模型胶囊 + 圆形发送 + 文件/上传 chip 行 + 免责声明。 */
export function InputComposer({
  running,
  onSend,
  value,
  onChange,
}: {
  running: boolean
  onSend: (text: string) => void
  value: string | null
  onChange: (v: string | null) => void
}) {
  const text = value ?? ''
  const taRef = useRef<HTMLTextAreaElement>(null)
  const [focused, setFocused] = useState(false)
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [activeSuggestion, setActiveSuggestion] = useState(0)
  const suggestionListId = 'prompt-suggestion-list'
  const { data: files = [] } = useFiles()
  const { uploads, openFilePicker, retryUpload } = useFileUpload()
  const deleteFile = useDeleteFile()
  const { toast } = useToast()
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    staleTime: 5 * 60_000,
    retry: false,
  })

  const inFlight = uploads.filter((u) => u.status !== 'done')
  const query = text.trim()
  const filteredSuggestions = useMemo(() => {
    if (!query) return []
    const normalizedQuery = query.toLocaleLowerCase()
    return PROMPT_SUGGESTIONS.filter((item) =>
      [item.label, item.prompt, ...item.keywords].some((field) => field.toLocaleLowerCase().includes(normalizedQuery)),
    )
  }, [query])
  const showSuggestions = focused && suggestionsOpen && filteredSuggestions.length > 0

  useEffect(() => {
    setActiveSuggestion(0)
  }, [query])

  useEffect(() => {
    if (!showSuggestions && activeSuggestion !== 0) setActiveSuggestion(0)
  }, [activeSuggestion, showSuggestions])

  const selectSuggestion = (item: PromptSuggestionItem) => {
    onChange(item.prompt)
    setSuggestionsOpen(false)
    setActiveSuggestion(0)
    taRef.current?.focus()
  }

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 150)}px`
  }, [text])

  const handleSend = () => {
    if (!text.trim() || running) return
    onChange(null)
    onSend(text)
  }

  const fillParsePrompt = (name: string) => {
    onChange(`请使用 tender-toc 技能，对 ${name} 做完整分析，最后组装 JSON`)
    taRef.current?.focus()
  }

  const handleDeleteFile = async (name: string) => {
    try {
      await deleteFile.mutateAsync(name)
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  const sendDisabled = running || !text.trim()

  return (
    <div className="composer">
      <div className="box">
        {inFlight.length > 0 && (
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {inFlight.map((u) => (
              <div
                key={u.id}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 text-xs',
                  u.status === 'error' ? 'border-error/50 bg-error/5 text-error' : 'border-input bg-background',
                )}
              >
                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="max-w-[180px] truncate">{u.name}</span>
                <span className="text-muted-foreground">{formatSize(u.size)}</span>
                {u.status === 'uploading' && (
                  <span className="h-1 w-16 overflow-hidden rounded-full bg-muted">
                    <span
                      className={cn('block h-full bg-primary', u.progress < 0 && 'w-1/3 animate-pulse')}
                      style={u.progress >= 0 ? { width: `${u.progress}%` } : undefined}
                    />
                  </span>
                )}
                {u.status === 'error' && (
                  <button type="button" onClick={() => retryUpload(u.id)} className="text-error hover:underline">
                    重试
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {files.length > 0 && (
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {files.map((f) => (
              <div
                key={f.name}
                className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-2 py-0.5 text-xs"
              >
                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="max-w-[180px] truncate" title={f.name}>
                  {f.name}
                </span>
                <span className="text-muted-foreground">{formatSize(f.size)}</span>
                {PARSEABLE_EXT.some((ext) => f.name.toLowerCase().endsWith(ext)) && (
                  <button
                    type="button"
                    onClick={() => fillParsePrompt(f.name)}
                    className="rounded-md border border-line bg-panel px-1.5 py-0.5 text-[11px] font-medium text-ink-2 hover:border-line-2 hover:text-foreground"
                  >
                    解析此文件
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleDeleteFile(f.name)}
                  disabled={deleteFile.isPending}
                  className="text-muted-foreground hover:text-foreground disabled:opacity-50"
                  aria-label={`删除 ${f.name}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <textarea
          ref={taRef}
          value={text}
          onChange={(e) => {
            onChange(e.target.value)
            setSuggestionsOpen(true)
          }}
          onFocus={() => {
            setFocused(true)
            if (query) setSuggestionsOpen(true)
          }}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (showSuggestions && e.key === 'ArrowDown') {
              e.preventDefault()
              setActiveSuggestion((current) => (current + 1) % filteredSuggestions.length)
              return
            }
            if (showSuggestions && e.key === 'ArrowUp') {
              e.preventDefault()
              setActiveSuggestion((current) => (current - 1 + filteredSuggestions.length) % filteredSuggestions.length)
              return
            }
            if (showSuggestions && (e.key === 'Enter' || e.key === 'Tab')) {
              e.preventDefault()
              selectSuggestion(filteredSuggestions[activeSuggestion])
              return
            }
            if (e.key === 'Escape') {
              setSuggestionsOpen(false)
              return
            }
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          role="combobox"
          aria-autocomplete="list"
          aria-controls={suggestionListId}
          aria-expanded={showSuggestions}
          aria-activedescendant={showSuggestions ? `prompt-suggestion-${filteredSuggestions[activeSuggestion]?.id}` : undefined}
          rows={1}
          placeholder="输入消息，可上传招标文件…"
        />
        {showSuggestions && (
          <PromptSuggestionPopover
            listId={suggestionListId}
            query={query}
            items={filteredSuggestions}
            activeIndex={activeSuggestion}
            onSelect={selectSuggestion}
            onHover={setActiveSuggestion}
          />
        )}
        <div className="row">
          <button type="button" className="composer-plus" title="上传文件" onClick={openFilePicker}>
            <Paperclip />
          </button>
          <div className="right">
            <ModelSelect label={settings?.model ?? 'deepseek-v4-flash'} />
            <button
              type="button"
              className="send-btn disabled:opacity-40"
              onClick={handleSend}
              disabled={sendDisabled}
              title={running ? '任务进行中' : '发送'}
            >
              {running ? <Square /> : <ArrowUp />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
