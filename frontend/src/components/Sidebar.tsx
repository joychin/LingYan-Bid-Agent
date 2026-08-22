import { Plus, Settings } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useConversations, useCreateConversation } from '@/hooks/useConversations'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/api/client'

export interface SidebarProps {
  selectedId: string | null
  onSelect: (id: string) => void
  onOpenSettings: () => void
}

export function Sidebar({ selectedId, onSelect, onOpenSettings }: SidebarProps) {
  const { data: conversations = [], isLoading } = useConversations()
  const createConv = useCreateConversation()

  const handleNew = async () => {
    const conv = await createConv.mutateAsync()
    onSelect(conv.id)
  }

  return (
    <aside className="flex h-full w-60 flex-col border-r bg-card">
      <div className="flex items-center justify-between px-3 py-3">
        <span className="text-sm font-semibold">会话</span>
        <Button size="sm" variant="ghost" onClick={handleNew} disabled={createConv.isPending}>
          <Plus className="h-4 w-4" />
          新建
        </Button>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-2">
        {isLoading && <p className="px-2 py-1 text-sm text-muted-foreground">加载中…</p>}
        {conversations.map((c: Conversation) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onSelect(c.id)}
            className={cn(
              'w-full truncate rounded-md px-3 py-2 text-left text-sm',
              c.id === selectedId ? 'bg-accent text-accent-foreground' : 'hover:bg-muted',
            )}
          >
            {c.title}
          </button>
        ))}
      </nav>
      <div className="border-t p-2">
        <Button variant="ghost" size="sm" className="w-full justify-start" onClick={onOpenSettings}>
          <Settings className="h-4 w-4" />
          设置
        </Button>
      </div>
    </aside>
  )
}
