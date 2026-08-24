import type { ReactNode } from 'react'
import { ChevronDown, Sparkles } from 'lucide-react'

export interface ModelSelectProps {
  label: string
  icon?: ReactNode
  onClick?: () => void
}

/** 输入区模型胶囊：图标 + 模型名 + chevron。 */
export function ModelSelect({ label, icon, onClick }: ModelSelectProps) {
  return (
    <button type="button" className="model-select" onClick={onClick} title="切换模型">
      {icon ?? <Sparkles className="model-icon" />}
      <span>{label}</span>
      <ChevronDown className="chev" />
    </button>
  )
}
