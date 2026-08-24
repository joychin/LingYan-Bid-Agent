import { PromptSuggestion } from '@/components/ai/PromptSuggestion'
import type { PromptSuggestionItem } from '@/data/promptCatalog'

export function PromptSuggestionPopover({
  listId,
  query,
  items,
  activeIndex,
  onSelect,
  onHover,
}: {
  listId: string
  query: string
  items: PromptSuggestionItem[]
  activeIndex: number
  onSelect: (item: PromptSuggestionItem) => void
  onHover: (index: number) => void
}) {
  return (
    <div id={listId} className="prompt-suggestions" role="listbox" aria-label="相关提示">
      {items.map((item, index) => (
        <PromptSuggestion
          key={item.id}
          id={`prompt-suggestion-${item.id}`}
          role="option"
          aria-selected={index === activeIndex}
          highlight={query}
          className={index === activeIndex ? 'prompt-suggestion-active' : undefined}
          onMouseEnter={() => onHover(index)}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onSelect(item)}
        >
          {item.label}
        </PromptSuggestion>
      ))}
    </div>
  )
}
