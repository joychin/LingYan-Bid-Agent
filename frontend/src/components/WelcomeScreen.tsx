import { PromptSuggestion } from '@/components/ai/PromptSuggestion'
import { PROMPT_SUGGESTIONS } from '@/data/promptCatalog'

/** 空状态（无选中会话 / 新建会话草稿页）：欢迎文案 + 建议 pill；所属任务在输入框左侧胶囊选择或就地新建。 */
export function WelcomeScreen({
  onPickFile,
  onPrompt,
}: {
  onPickFile: () => void
  onPrompt: (text: string) => void
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-6">
      <div className="text-center">
        <h2 className="text-lg font-semibold text-foreground">欢迎使用 Tender Agent</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          在下方输入框选择或新建所属任务后开始对话，也可上传招标文件
        </p>
      </div>
      <div className="relative top-10 flex w-full max-w-2xl flex-wrap justify-center gap-2">
        <PromptSuggestion onClick={onPickFile}>解析招标文件目录</PromptSuggestion>
        {PROMPT_SUGGESTIONS.map((suggestion) => (
          <PromptSuggestion key={suggestion.id} onClick={() => onPrompt(suggestion.prompt)}>
            {suggestion.label}
          </PromptSuggestion>
        ))}
      </div>
    </div>
  )
}
