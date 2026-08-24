export interface PromptSuggestionItem {
  id: string
  label: string
  prompt: string
  keywords: string[]
}

export const PROMPT_SUGGESTIONS: PromptSuggestionItem[] = [
  {
    id: 'analyze-scoring',
    label: '分析这份招标文件的评分办法',
    prompt: '请分析这份招标文件的评分办法，列出各评分项、分值占比与投标响应要点。',
    keywords: ['评分办法', '评分项', '分值', '投标响应'],
  },
  {
    id: 'capabilities',
    label: '了解我的能力与典型用法',
    prompt: '你能帮我做什么？请介绍你的能力与典型用法。',
    keywords: ['能力', '典型用法', '能做什么'],
  },
]
