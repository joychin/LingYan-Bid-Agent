import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowUp, Paperclip, Square } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useFileUpload } from '@/context/FileUpload'
import { UploadChips } from '@/components/UploadChips'
import { ModelSelect } from '@/components/workspace/ModelSelect'
import { ThinkingSelect } from '@/components/ThinkingSelect'
import { PromptSuggestionPopover } from '@/components/PromptSuggestionPopover'
import { PROMPT_SUGGESTIONS, type PromptSuggestionItem } from '@/data/promptCatalog'
import { getSettings, type ThinkingLevel } from '@/api/client'

/** 输入时提示词联想弹层：2026-09-07 用户要求暂时禁用；恢复改回 true（showSuggestions 单点闸门，其余接线原样保留） */
const SUGGESTIONS_ENABLED = false

/** Workspace 输入区：圆角 24 输入框（自适应高度）+ 附件钮 + 模型胶囊 + 圆形发送 + 上传 chip 行 + 免责声明。
 *  HITL 等待期本组件整体不渲染（提问卡原位替换，ChatView 条件渲染），故无 waiting/disabled 形态。 */
export function InputComposer({
  running,
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
  const { uploads, taskScope, openFilePicker, acknowledgeUploads } = useFileUpload()
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    staleTime: 5 * 60_000,
    retry: false,
  })

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
    if (sending) return
    if (running) return
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

  const runningBlock = running
  const sendDisabled = sending || (!text.trim() && freshFiles.length === 0)

  return (
    <div className="composer">
      <div className="box">
        {leftSlot && <div className="box-top">{leftSlot}</div>}
        <div className="box-inner">
          <UploadChips className="mb-2" />
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
            placeholder={
              stopping
                ? '正在停止任务，收尾后即可继续发送…'
                : freshFiles.length > 0
                  ? '直接发送：通知助手处理刚上传的文件…'
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
                  title="发送"
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
