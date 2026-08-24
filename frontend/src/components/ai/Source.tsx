import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { cn } from '@/lib/utils'

/** prompt-kit Source 移植：引用源 pill + hover 详情卡。HoverCard 用我们手写原语（零 radix）。 */
const SourceContext = createContext<{ href: string; domain: string } | null>(null)

function useSourceContext() {
  const ctx = useContext(SourceContext)
  if (!ctx) throw new Error('Source.* must be used inside <Source>')
  return ctx
}

export function Source({ href, children }: { href: string; children: ReactNode }) {
  let domain = ''
  try {
    domain = new URL(href).hostname
  } catch {
    domain = href.split('/').pop() || href
  }
  return (
    <SourceContext.Provider value={{ href, domain }}>
      <HoverCard openDelay={150} closeDelay={0}>
        {children}
      </HoverCard>
    </SourceContext.Provider>
  )
}

export function SourceTrigger({
  label,
  showFavicon = false,
  className,
}: {
  label?: string | number
  showFavicon?: boolean
  className?: string
}) {
  const { href, domain } = useSourceContext()
  const labelToShow = label ?? domain.replace('www.', '')

  return (
    <HoverCardTrigger>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          'inline-flex h-5 max-w-32 items-center gap-1 overflow-hidden rounded-full bg-muted px-1 py-0 text-xs text-muted-foreground no-underline transition-colors duration-150 hover:bg-muted-foreground/30 hover:text-primary',
          showFavicon && 'pr-2 pl-1',
          className,
        )}
      >
        {showFavicon && (
          <img
            src={`https://www.google.com/s2/favicons?sz=64&domain_url=${encodeURIComponent(href)}`}
            alt="favicon"
            width={14}
            height={14}
            className="size-3.5 rounded-full"
          />
        )}
        <span className="truncate text-center font-normal tabular-nums">{labelToShow}</span>
      </a>
    </HoverCardTrigger>
  )
}

export function SourceContent({
  title,
  description,
  className,
}: {
  title: string
  description: string
  className?: string
}) {
  const { href, domain } = useSourceContext()
  return (
    <HoverCardContent className={cn('w-80 p-0 shadow-xs', className)}>
      <a href={href} target="_blank" rel="noopener noreferrer" className="flex flex-col gap-2 p-3">
        <div className="flex items-center gap-1.5">
          <img
            src={`https://www.google.com/s2/favicons?sz=64&domain_url=${encodeURIComponent(href)}`}
            alt="favicon"
            className="size-4 rounded-full"
            width={16}
            height={16}
          />
          <div className="truncate text-sm text-primary">{domain.replace('www.', '')}</div>
        </div>
        <div className="line-clamp-2 text-sm font-medium">{title}</div>
        <div className="line-clamp-2 text-sm text-muted-foreground">{description}</div>
      </a>
    </HoverCardContent>
  )
}
