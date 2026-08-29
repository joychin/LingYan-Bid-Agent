import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'

/**
 * prompt-kit Loader 移植：circular / classic / pulse / pulse-dot / dots / typing / wave /
 * bars / terminal / text-blink / text-shimmer / loading-dots。
 * 纯 CSS（keyframes 在 styles/ai.css），无第三方依赖。
 */
export interface LoaderProps {
  variant?:
    | 'circular'
    | 'classic'
    | 'pulse'
    | 'pulse-dot'
    | 'dots'
    | 'typing'
    | 'wave'
    | 'bars'
    | 'terminal'
    | 'text-blink'
    | 'text-shimmer'
    | 'loading-dots'
  size?: 'sm' | 'md' | 'lg'
  text?: string
  className?: string
}

type Size = 'sm' | 'md' | 'lg'

const sizeClass: Record<Size, string> = { sm: 'size-4', md: 'size-5', lg: 'size-6' }

/** 用 inline animation 替代 prompt-kit 的 animate-[...] 任意值，避免依赖 Tailwind 编译。 */
const anim = (name: string, dur: string, timing = 'linear', iter = 'infinite'): CSSProperties => ({
  animation: `${name} ${dur} ${timing} ${iter}`,
})

function LoaderShell({ children, srText = 'Loading' }: { children?: React.ReactNode; srText?: string }) {
  return (
    <>
      {children}
      <span className="sr-only">{srText}</span>
    </>
  )
}

export function CircularLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  return (
    <div
      className={cn(
        'animate-spin rounded-full border-2 border-t-transparent',
        sizeClass[size],
        className,
      )}
      style={{ borderColor: 'var(--Color-brand-primary)', borderTopColor: 'transparent' }}
    >
      <LoaderShell />
    </div>
  )
}

export function ClassicLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const bar = { sm: { h: '6px', w: '1.5px', ml: '-0.75px', or: '0.75px 10px' }, md: { h: '8px', w: '2px', ml: '-1px', or: '1px 12px' }, lg: { h: '10px', w: '2.5px', ml: '-1.25px', or: '1.25px 14px' } }[size]
  return (
    <div className={cn('relative', sizeClass[size], className)}>
      {[...Array(12)].map((_, i) => (
        <div
          key={i}
          className="absolute left-1/2 top-0 rounded-full"
          style={{
            background: 'var(--Color-brand-primary)',
            height: bar.h,
            width: bar.w,
            marginLeft: bar.ml,
            transformOrigin: bar.or,
            transform: `rotate(${i * 30}deg)`,
            ...anim('spinner-fade', '1.2s'),
            animationDelay: `${i * 0.1}s`,
          }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function PulseLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  return (
    <div className={cn('relative', sizeClass[size], className)}>
      <div
        className="absolute inset-0 rounded-full border-2"
        style={{ borderColor: 'var(--Color-brand-primary)', ...anim('thin-pulse', '1.5s', 'ease-in-out') }}
      />
      <LoaderShell />
    </div>
  )
}

export function PulseDotLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const s = { sm: 'size-1', md: 'size-2', lg: 'size-3' }[size]
  return (
    <div
      className={cn('rounded-full', s, className)}
      style={{ background: 'var(--Color-brand-primary)', ...anim('pulse-dot', '1.2s', 'ease-in-out') }}
    >
      <LoaderShell />
    </div>
  )
}

export function DotsLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const dot = { sm: 'h-1.5 w-1.5', md: 'h-2 w-2', lg: 'h-2.5 w-2.5' }[size]
  const box = { sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  return (
    <div className={cn('flex items-center space-x-1', box, className)}>
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className={cn('rounded-full', dot)}
          style={{ background: 'var(--Color-brand-primary)', ...anim('bounce-dots', '1.4s', 'ease-in-out'), animationDelay: `${i * 160}ms` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function TypingLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const dot = { sm: 'h-1 w-1', md: 'h-1.5 w-1.5', lg: 'h-2 w-2' }[size]
  const box = { sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  return (
    <div className={cn('flex items-center space-x-1', box, className)}>
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className={cn('rounded-full', dot)}
          style={{ background: 'var(--Color-brand-primary)', ...anim('typing', '1s'), animationDelay: `${i * 250}ms` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function WaveLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const widths = { sm: 'w-0.5', md: 'w-0.5', lg: 'w-1' }[size]
  const box = { sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  const heights = { sm: ['6px', '9px', '12px', '9px', '6px'], md: ['8px', '12px', '16px', '12px', '8px'], lg: ['10px', '15px', '20px', '15px', '10px'] }[size]
  return (
    <div className={cn('flex items-center gap-0.5', box, className)}>
      {[...Array(5)].map((_, i) => (
        <div
          key={i}
          className={cn('rounded-full', widths)}
          style={{ background: 'var(--Color-brand-primary)', height: heights[i], ...anim('wave', '1s', 'ease-in-out'), animationDelay: `${i * 100}ms` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function BarsLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const widths = { sm: 'w-1', md: 'w-1.5', lg: 'w-2' }[size]
  const box = { sm: 'h-4 gap-1', md: 'h-5 gap-1.5', lg: 'h-6 gap-2' }[size]
  return (
    <div className={cn('flex', box, className)}>
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className={cn('h-full', widths)}
          style={{ background: 'var(--Color-brand-primary)', ...anim('wave-bars', '1.2s', 'ease-in-out'), animationDelay: `${i * 0.2}s` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function TerminalLoader({ className, size = 'md' }: { className?: string; size?: Size }) {
  const cursor = { sm: 'h-3 w-1.5', md: 'h-4 w-2', lg: 'h-5 w-2.5' }[size]
  const text = { sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  const box = { sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  return (
    <div className={cn('flex items-center space-x-1', box, className)}>
      <span className={cn('font-mono', text)} style={{ color: 'var(--Color-brand-primary)' }}>
        {'>'}
      </span>
      <div className={cn(cursor)} style={{ background: 'var(--Color-brand-primary)', ...anim('blink', '1s', 'step-end') }} />
      <LoaderShell />
    </div>
  )
}

export function TextBlinkLoader({ text = 'Thinking', className, size = 'md' }: { text?: string; className?: string; size?: Size }) {
  const textSize = { sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  return (
    <div className={cn('font-medium', textSize, className)} style={anim('text-blink', '2s', 'ease-in-out')}>
      {text}
    </div>
  )
}

export function TextShimmerLoader({ text = 'Thinking', className, size = 'md' }: { text?: string; className?: string; size?: Size }) {
  const textSize = { sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  return (
    <div
      className={cn('text-shimmer font-medium', textSize, className)}
      style={{
        backgroundImage: 'linear-gradient(to right, var(--Color-text-secondary) 40%, var(--Color-text-primary) 60%, var(--Color-text-secondary) 80%)',
      }}
    >
      {text}
    </div>
  )
}

export function TextDotsLoader({ className, text = 'Thinking', size = 'md' }: { className?: string; text?: string; size?: Size }) {
  const textSize = { sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  return (
    <div className={cn('inline-flex items-center', className)}>
      <span className={cn('font-medium', textSize)} style={{ color: 'var(--Color-brand-primary)' }}>
        {text}
      </span>
      <span className="inline-flex">
        {[0.2, 0.4, 0.6].map((d) => (
          <span key={d} style={{ color: 'var(--Color-brand-primary)', ...anim('loading-dots', '1.4s'), animationDelay: `${d}s` }}>
            .
          </span>
        ))}
      </span>
    </div>
  )
}

export function Loader({ variant = 'circular', size = 'md', text, className }: LoaderProps) {
  switch (variant) {
    case 'circular':
      return <CircularLoader size={size} className={className} />
    case 'classic':
      return <ClassicLoader size={size} className={className} />
    case 'pulse':
      return <PulseLoader size={size} className={className} />
    case 'pulse-dot':
      return <PulseDotLoader size={size} className={className} />
    case 'dots':
      return <DotsLoader size={size} className={className} />
    case 'typing':
      return <TypingLoader size={size} className={className} />
    case 'wave':
      return <WaveLoader size={size} className={className} />
    case 'bars':
      return <BarsLoader size={size} className={className} />
    case 'terminal':
      return <TerminalLoader size={size} className={className} />
    case 'text-blink':
      return <TextBlinkLoader text={text} size={size} className={className} />
    case 'text-shimmer':
      return <TextShimmerLoader text={text} size={size} className={className} />
    case 'loading-dots':
      return <TextDotsLoader text={text} size={size} className={className} />
    default:
      return <CircularLoader size={size} className={className} />
  }
}
