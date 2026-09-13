import { useEffect, useMemo, useRef, useState } from 'react'
import type { ClipboardEvent, DragEvent } from 'react'
import { ArrowUp, Paperclip, Square } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useFileUpload } from '@/context/FileUpload'
import { UploadChips } from '@/components/UploadChips'
import { ModelSelect } from '@/components/workspace/ModelSelect'
import { ThinkingSelect } from '@/components/ThinkingSelect'
import { PromptSuggestionPopover } from '@/components/PromptSuggestionPopover'
import { PROMPT_SUGGESTIONS, type PromptSuggestionItem } from '@/data/promptCatalog'
import { renameClipboardFiles } from '@/lib/clipboardFiles'
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
  thinking,
  onThinkingChange,
  model,
  onModelChange,
  onOpenSettings,
  onStop,
  idlePlaceholder,
}: {
  running: boolean
  /** 已请求停止、等待收尾（协作式取消的事件边界窗口）：停止钮转「正在停止…」 */
  stopping?: boolean
  onSend: (text: string) => void | Promise<void>
  value: string | null
  onChange: (v: string | null) => void
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
  /** 空闲态占位文案（ChatView 传任务感知版「在「XX」中输入消息…」；缺省通用文案） */
  idlePlaceholder?: string
}) {
  const text = value ?? ''
  const taRef = useRef<HTMLTextAreaElement>(null)
  const [focused, setFocused] = useState(false)
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [activeSuggestion, setActiveSuggestion] = useState(0)
  const [sending, setSending] = useState(false)
  /** 文件拖到输入框上（drag-over 高亮 + placeholder 提示）：文件拖放本就有聊天区
   *  整层 UploadDropzone 兜底，这里只给输入框局部反馈；`data-drag-target` 供外层
   *  覆盖层识别「现在是输入框在自己的边界内接」从而让位（双反馈打架） */
  const [dragOver, setDragOver] = useState(false)
  const suggestionListId = 'prompt-suggestion-list'
  const { uploads, taskScope, openFilePicker, dropFiles, acknowledgeUploads } = useFileUpload()
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

  // 文件拖放/文字拖放分流：只拦 Files（types 含 'Files'），框内选中文字的拖放
  // 走原生行为；preventDefault 是 drop 能落到本元素的前提。dragover 不 stopPropagation
  // ——外层 UploadDropzone 要靠它按拖拽目标让位（两层同时亮=双反馈）；drop 必须
  // stopPropagation 防外层再收一次（双上传），外层另用 onDropCapture 收尾覆盖层
  const boxDragHandlers = {
    onDragOver: (e: DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer.types.includes('Files')) return
      e.preventDefault()
      setDragOver(true)
    },
    onDragLeave: (e: DragEvent<HTMLDivElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false)
    },
    onDrop: (e: DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer.types.includes('Files') || e.dataTransfer.files.length === 0) return
      e.preventDefault()
      e.stopPropagation()
      setDragOver(false)
      dropFiles(Array.from(e.dataTransfer.files))
    },
  }

  // 粘贴文件（截图/复制的文件）：有文件才拦截，纯文本粘贴走默认行为。剪贴板
  // 截图默认名都是 image.png（任务内同名覆盖语义），renameClipboardFiles 改名保共存
  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files ?? [])
    if (files.length === 0) return
    e.preventDefault()
    dropFiles(renameClipboardFiles(files))
  }

  return (
    <div className="composer">
      <div className={dragOver ? 'box drag-over' : 'box'} data-drag-target="" {...boxDragHandlers}>
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
            onPaste={handlePaste}
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
              dragOver
                ? '松开以上传到当前任务…'
                : stopping
                  ? '正在停止任务，收尾后即可继续发送…'
                  : freshFiles.length > 0
                    ? '直接发送：通知助手处理刚上传的文件…'
                    : idlePlaceholder ?? '输入消息，可上传招标文件…'
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
