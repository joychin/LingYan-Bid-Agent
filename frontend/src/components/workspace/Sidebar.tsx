import { useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown, Folder, PanelLeftClose, Plus, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { NavRow } from './NavRow'
import { NavItem } from './NavItem'
import { UserBar } from './UserBar'
import { IconButton } from './IconButton'

export interface SidebarItem {
  id: string
  title: string
  meta?: string
}

export interface SidebarFolder {
  id: string
  name: string
  items: SidebarItem[]
  moreLabel?: string
  onMore?: () => void
}

export interface SidebarSection {
  id: string
  title: string
  count?: number
  folders?: SidebarFolder[]
}

export interface QuickNavItem {
  id: string
  icon: ReactNode
  label: string
  hint?: string
}

export interface SidebarProps {
  title?: string
  quickNav?: QuickNavItem[]
  sections?: SidebarSection[]
  selectedId?: string
  userName?: string
  userActions?: ReactNode
  collapsed?: boolean
  onCollapse?: () => void
  onNew?: () => void
  onSelect?: (id: string) => void
}

/** 完整侧栏组合：head「工作区」+ 快捷导航 + 任务分区（文件夹树）+ 新建任务 + 用户栏。 */
export function Sidebar({
  title = '工作区',
  quickNav = [],
  sections = [],
  selectedId,
  userName = '用户',
  userActions,
  collapsed = false,
  onCollapse,
  onNew,
  onSelect,
}: SidebarProps) {
  return (
    <aside className={cn('side', collapsed && 'collapsed')}>
      <div className="side-head">
        <span>{title}</span>
        <button type="button" title="收起侧栏" onClick={onCollapse}>
          <PanelLeftClose />
        </button>
      </div>
      <div className="side-scroll">
        {quickNav.length > 0 && (
          <div className="quick-list">
            {quickNav.map((q) => (
              <NavRow key={q.id} icon={q.icon} label={q.label} hint={q.hint} />
            ))}
          </div>
        )}
        {sections.map((s) => (
          <SectionBlock key={s.id} section={s} selectedId={selectedId} onSelect={onSelect} />
        ))}
        {onNew && (
          <button type="button" className="new-btn" onClick={onNew}>
            <Plus />
            新建任务
          </button>
        )}
      </div>
      <UserBar
        name={userName}
        actions={
          userActions ?? (
            <IconButton title="设置">
              <Settings />
            </IconButton>
          )
        }
      />
    </aside>
  )
}

function SectionBlock({
  section,
  selectedId,
  onSelect,
}: {
  section: SidebarSection
  selectedId?: string
  onSelect?: (id: string) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className={cn('nav-section', !open && 'collapsed')}>
      <div className="nav-section-title" onClick={() => setOpen(!open)}>
        <span>
          {section.title}
          {typeof section.count === 'number' && (
            <>
              （<span className="count">{section.count}</span>）
            </>
          )}
        </span>
        <ChevronDown className="chev" />
      </div>
      {section.folders?.map((f) => (
        <FolderBlock key={f.id} folder={f} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  )
}

function FolderBlock({
  folder,
  selectedId,
  onSelect,
}: {
  folder: SidebarFolder
  selectedId?: string
  onSelect?: (id: string) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className={cn('nav-folder', !open && 'collapsed')}>
      <div className="folder-head" onClick={() => setOpen(!open)}>
        <ChevronDown className="folder-chev" />
        <Folder className="folder" />
        <span className="truncate">{folder.name}</span>
      </div>
      <div className="nav-sub">
        {folder.items.map((item) => (
          <NavItem
            key={item.id}
            title={item.title}
            meta={item.meta}
            active={item.id === selectedId}
            onClick={() => onSelect?.(item.id)}
          />
        ))}
        {folder.moreLabel && (
          <div className="nav-more" onClick={folder.onMore}>
            {folder.moreLabel}
          </div>
        )}
      </div>
    </div>
  )
}
