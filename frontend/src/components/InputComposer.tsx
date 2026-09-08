import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowUp, FileText, Paperclip, Square, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useFileUpload } from '@/context/FileUpload'
import { formatSize, cn } from '@/lib/utils'
import { ModelSelect } from '@/components/workspace/ModelSelect'
import { ThinkingSelect } from '@/components/ThinkingSelect'
import { PromptSuggestionPopover } from '@/components/PromptSuggestionPopover'
import { PROMPT_SUGGESTIONS, type PromptSuggestionItem } from '@/data/promptCatalog'
import { getSettings, type ThinkingLevel } from '@/api/client'

/** 输入时提示词联想弹层：2026-09-07 用户要求暂时禁用；恢复改回 true（showSuggestions 单点闸门，其余接线原样保留） */
const SUGGESTIONS_ENABLED = false

/** Workspace 输入区：圆角 24 输入框（自适应高度）+ 附件钮 + 模型胶囊 + 圆形发送 + 上传 chip 行 + 免责声明。 */
export function InputComposer({
  running,
  waiting = false,
  waitingHint,
  disabled = false,
  stopping = false,
  onSend,
  value,
  onChange,
  leftSlot,
  thinking,
  onThinkingChange,
  model,
  onModelChange,
  onOpenSettings,
  onStop,
}: {
  running: boolean
  /** HITL 等待用户回答/确认：发送钮保持发送语义（waiting 态配 disabled 使用） */
  waiting?: boolean
  /** 覆盖 waiting 态 placeholder（HITL 卡内作答的指引） */
  waitingHint?: string
  /** 整体禁用输入与发送（HITL 等待期间作答在卡内；上传钮不受影响） */
  disabled?: boolean
  /** 已请求停止、等待收尾（协作式取消的事件边界窗口）：停止钮转「正在停止…」 */
  stopping?: boolean
  onSend: (text: string) => void | Promise<void>
  value: string | null
  onChange: (v: string | null) => void
  /** 输入框左上角附加行（新会话草稿页的任务选择胶囊，ZCode 输入框顶部条同款）；空=不渲染顶行 */
  leftSlot?: ReactNode
  /** 思考档位（胶囊展示与切换；随消息发送由持有方 ChatView 接线） */
  thinking: ThinkingLevel
  onThinkingChange: (level: ThinkingLevel) => void
  /** 模型 profile 选中（多模型选择器；未选/undefined 落到 default_model） */
  model?: string
  onModelChange: (id: string) => void
  /** 打开设置（模型菜单「管理模型…」入口） */
  onOpenSettings?: () => void
  /** 停止当前 run（running 且非 HITL 等待时，发送钮变停止钮） */
  onStop?: () => void
}) {
  const text = value ?? ''
  const taRef = useRef<HTMLTextAreaElement>(null)
  const [focused, setFocused] = useState(false)
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [activeSuggestion, setActiveSuggestion] = useState(0)
  const [sending, setSending] = useState(false)
  const suggestionListId = 'prompt-suggestion-list'
  const { uploads, taskScope, openFilePicker, retryUpload, dismissUpload, acknowledgeUploads } = useFileUpload()
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    staleTime: 5 * 60_000,
    retry: false,
  })

  // 上传中/失败 chip 只显示当前任务的（AGENTS 约定「文件 chips 只显示当前任务的文件」）：
  // 错误 chip 不随任务切换泄漏到别的任务输入区（上传目标仍锁原任务，重试不受影响）
  const inFlight = uploads.filter((u) => u.status !== 'done' && u.taskId === taskScope)
  // 本任务新上传、尚未随任何消息「告知」助手的文件：空文本发送时自动合成文件通知消息。
  // 已告知状态由 FileUpload context 持有（acknowledgeUploads 发送后移除上传项）：
  // 组件重挂载（切会话/进出草稿页）不复活、不跨任务串扰
  const freshFiles = useMemo(
    () => uploads.filter((u) => u.status === 'done' && u.taskId === taskScope),
    [uploads, taskScope],
  )
  const query = text.trim()
  const filteredSuggestions = useMemo(() => {
    if (!query) return []
    const normalizedQuery = query.toLocaleLowerCase()
    return PROMPT_SUGGESTIONS.filter((item) =>
      [item.label, item.prompt, ...item.keywords].some((field) => field.toLocaleLowerCase().includes(normalizedQuery)),
    )
  }, [query])
  const showSuggestions = SUGGESTIONS_ENABLED && focused && suggestionsOpen && filteredSuggestions.length > 0

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

  // 任务文件在产物面板「任务文件」区查看；输入框上方只保留待发送的新上传高亮 chip
  const handleSend = async () => {
    if (disabled || sending) return
    if (running && !waiting) return
    const fileNames = freshFiles.map((f) => f.name)
    // 空文本兜底：有刚上传的文件 → 合成文件通知（驱动助手处理新文件）
    const canSendFiles = fileNames.length > 0
    if (!text.trim() && !canSendFiles) return
    const effective = text.trim() || (canSendFiles ? `我上传了文件：${fileNames.join('、')}，请查收处理` : '')
    if (!effective) return
    setSending(true)
    try {
      // 发送成功才清空：失败（网络/409/超时）时输入与新上传 chip 原样保留，
      // 错误已由 useRun 置错误卡（带重试），用户可改可重发
      await onSend(effective)
    } catch {
      return
    } finally {
      setSending(false)
    }
    // 发送后输入区收敛：新上传 chip 已随 acknowledge 移除
    acknowledgeUploads(freshFiles.map((f) => f.id))
    onChange(null)
  }

  const runningBlock = running && !waiting
  const sendDisabled = disabled || sending || (!text.trim() && freshFiles.length === 0)

  return (
    <div className="composer">
      <div className="box">
        {leftSlot && <div className="box-top">{leftSlot}</div>}
        <div className="box-inner">
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
                    <>
                      <span className="max-w-[220px] truncate" title={u.error}>
                        {u.error}
                      </span>
                      {/* statusCode 缺省=网络层错误；400/413 是永久性失败，重试无意义，只留关闭 */}
                      {(u.statusCode == null || u.statusCode >= 500) && (
                        <button type="button" onClick={() => retryUpload(u.id)} className="text-error hover:underline">
                          重试
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => dismissUpload(u.id)}
                        className="opacity-60 hover:opacity-100"
                        aria-label={`移除 ${u.name}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
          {/* 新上传（未随消息告知）：高亮 chip，发送后随 acknowledgeUploads 消失 */}
          {freshFiles.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {freshFiles.map((f) => (
                <div
                  key={f.id}
                  title="新上传：发送消息时会随消息告知助手"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-primary/60 bg-secondary px-2 py-0.5 text-xs text-foreground"
                >
                  <FileText className="h-3.5 w-3.5 text-primary" />
                  <span className="max-w-[180px] truncate">{f.name}</span>
                  <span className="text-muted-foreground">{formatSize(f.size)}</span>
                </div>
              ))}
            </div>
          )}
          {/* 任务文件管理收进底栏「文件 N」胶囊的浮层；输入框上方只保留待发送的新上传高亮 chip */}
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
            disabled={disabled}
            placeholder={
              stopping
                ? '正在停止任务，收尾后即可继续发送…'
                : waiting
                  ? waitingHint ??
                    (freshFiles.length > 0
                      ? '直接发送＝把刚上传的文件作为回答告知助手…'
                      : '回答助手，回车发送后任务继续…')
                  : freshFiles.length > 0
                    ? '直接发送＝通知助手处理刚上传的文件…'
                    : '输入消息，可上传招标文件…'
            }
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
            <div className="left">
              <button
                type="button"
                className="composer-plus disabled:opacity-40"
                title={taskScope ? '上传文件到当前任务' : '请先选择所属任务'}
                onClick={openFilePicker}
                disabled={!taskScope}
              >
                <Paperclip />
              </button>
            </div>
            <div className="right">
              <ModelSelect
                options={
                  settings?.models.map((m) => ({
                    id: m.id,
                    name: m.name,
                    model: m.model,
                    imageSupport: m.image_support,
                  })) ?? []
                }
                value={model ?? settings?.default_model ?? ''}
                onChange={onModelChange}
                onManage={() => onOpenSettings?.()}
              />
              <ThinkingSelect value={thinking} onChange={onThinkingChange} />
              {runningBlock ? (
                <button
                  type="button"
                  className="send-btn disabled:opacity-40"
                  onClick={() => onStop?.()}
                  disabled={stopping || !onStop}
                  title={stopping ? '正在停止…' : '停止任务'}
                >
                  <Square />
                </button>
              ) : (
                <button
                  type="button"
                  className="send-btn disabled:opacity-40"
                  onClick={handleSend}
                  disabled={sendDisabled}
                  title={waiting ? '发送回答' : '发送'}
                >
                  <ArrowUp />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
