import { PromptSuggestion } from '@/components/ai/PromptSuggestion'
import { PROMPT_SUGGESTIONS } from '@/data/promptCatalog'

/** 空状态（新对话）：普通 pill 建议列表。 */
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
        <p className="mt-1.5 text-sm text-muted-foreground">上传招标文件，或直接开始对话</p>
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
