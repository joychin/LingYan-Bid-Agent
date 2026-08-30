import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'

/**
 * prompt-kit Loader 移植：circular / classic / pulse / pulse-dot / dots / typing / wave /
 * bars / terminal / text-blink / text-shimmer / loading-dots。
 * 纯 CSS（keyframes 在 styles/ai.css），无第三方依赖。
 * 本地扩展（官方仅 sm/md/lg、无配色分档）：tone 分语境配色 + xs 尺寸档。
 */
export type LoaderTone = 'brand' | 'muted' | 'current'

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
  size?: 'xs' | 'sm' | 'md' | 'lg'
  text?: string
  className?: string
  tone?: LoaderTone
}

type Size = 'xs' | 'sm' | 'md' | 'lg'

/** brand=品牌青（AI 执行语境）；muted=中性灰（面板列表/保存中等中性语境）；current=currentColor（按钮内随文字色自适应）。 */
const toneColor: Record<LoaderTone, string> = {
  brand: 'var(--Color-brand-primary)',
  muted: 'var(--Color-text-tertiary)',
  current: 'currentColor',
}

const sizeClass: Record<Size, string> = { xs: 'size-3', sm: 'size-4', md: 'size-5', lg: 'size-6' }

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

export function CircularLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  return (
    <div
      className={cn(
        'animate-spin rounded-full border-2 border-t-transparent',
        sizeClass[size],
        className,
      )}
      style={{ borderColor: toneColor[tone], borderTopColor: 'transparent' }}
    >
      <LoaderShell />
    </div>
  )
}

export function ClassicLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  // 容器叠加同周期同步旋转（spinner-rotate）消掉 30° 阶跃；各档旋转中心一律取
  // 盒子几何中心（轮盘内切、不产生公转摆动）——官方「中心+2」的溢出标定在旋转下会
  // 摆动，弃用。xs=14px 侧栏行内用（08-30 定稿：0.9s 显快、1.44s 偏慢，1.12s 终稿）；
  // 辐条数随尺寸分档：14px 下 12 根间隙仅 ~2px 糊成一盘，xs 减到 8 根（45° 间距），
  // sm+ 有空间保持官方 12 根。步进 = 周期/根数，与旋转严格同步
  const period = 1.12
  const spokes = { xs: 8, sm: 12, md: 12, lg: 12 }[size]
  const step = period / spokes
  const box = { xs: 'size-3.5', sm: 'size-4', md: 'size-5', lg: 'size-6' }[size]
  const bar = {
    xs: { h: '5px', w: '1.5px', ml: '-0.75px', or: '0.5px 7px' },
    sm: { h: '6px', w: '1.5px', ml: '-0.75px', or: '0.75px 8px' },
    md: { h: '8px', w: '2px', ml: '-1px', or: '1px 10px' },
    lg: { h: '10px', w: '2.5px', ml: '-1.25px', or: '1.25px 12px' },
  }[size]
  return (
    <div
      className={cn('relative', box, className)}
      style={anim('spinner-rotate', `${period}s`)}
    >
      {[...Array(spokes)].map((_, i) => (
        <div
          key={i}
          className="absolute left-1/2 top-0 rounded-full"
          style={{
            background: toneColor[tone],
            height: bar.h,
            width: bar.w,
            marginLeft: bar.ml,
            transformOrigin: bar.or,
            transform: `rotate(${i * (360 / spokes)}deg)`,
            ...anim('spinner-fade', `${period}s`),
            animationDelay: `${i * step}s`,
          }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function PulseLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  return (
    <div className={cn('relative', sizeClass[size], className)}>
      <div
        className="absolute inset-0 rounded-full border-2"
        style={{ borderColor: toneColor[tone], ...anim('thin-pulse', '1.5s', 'ease-in-out') }}
      />
      <LoaderShell />
    </div>
  )
}

export function PulseDotLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  const s = { xs: 'size-1', sm: 'size-1', md: 'size-2', lg: 'size-3' }[size]
  return (
    <div
      className={cn('rounded-full', s, className)}
      style={{ background: toneColor[tone], ...anim('pulse-dot', '1.2s', 'ease-in-out') }}
    >
      <LoaderShell />
    </div>
  )
}

export function DotsLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  const dot = { xs: 'h-1 w-1', sm: 'h-1.5 w-1.5', md: 'h-2 w-2', lg: 'h-2.5 w-2.5' }[size]
  const box = { xs: 'h-3', sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  return (
    <div className={cn('flex items-center space-x-1', box, className)}>
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className={cn('rounded-full', dot)}
          style={{ background: toneColor[tone], ...anim('bounce-dots', '1.4s', 'ease-in-out'), animationDelay: `${i * 160}ms` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function TypingLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  const dot = { xs: 'h-1 w-1', sm: 'h-1 w-1', md: 'h-1.5 w-1.5', lg: 'h-2 w-2' }[size]
  const box = { xs: 'h-3', sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  return (
    <div className={cn('flex items-center space-x-1', box, className)}>
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className={cn('rounded-full', dot)}
          style={{ background: toneColor[tone], ...anim('typing', '1s'), animationDelay: `${i * 250}ms` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function WaveLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  const widths = { xs: 'w-0.5', sm: 'w-0.5', md: 'w-0.5', lg: 'w-1' }[size]
  const box = { xs: 'h-3', sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  const heights = {
    xs: ['4px', '6px', '8px', '6px', '4px'],
    sm: ['6px', '9px', '12px', '9px', '6px'],
    md: ['8px', '12px', '16px', '12px', '8px'],
    lg: ['10px', '15px', '20px', '15px', '10px'],
  }[size]
  return (
    <div className={cn('flex items-center gap-0.5', box, className)}>
      {[...Array(5)].map((_, i) => (
        <div
          key={i}
          className={cn('rounded-full', widths)}
          style={{ background: toneColor[tone], height: heights[i], ...anim('wave', '1s', 'ease-in-out'), animationDelay: `${i * 100}ms` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function BarsLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  const widths = { xs: 'w-1', sm: 'w-1', md: 'w-1.5', lg: 'w-2' }[size]
  const box = { xs: 'h-3 gap-1', sm: 'h-4 gap-1', md: 'h-5 gap-1.5', lg: 'h-6 gap-2' }[size]
  return (
    <div className={cn('flex', box, className)}>
      {[...Array(3)].map((_, i) => (
        <div
          key={i}
          className={cn('h-full', widths)}
          style={{ background: toneColor[tone], ...anim('wave-bars', '1.2s', 'ease-in-out'), animationDelay: `${i * 0.2}s` }}
        />
      ))}
      <LoaderShell />
    </div>
  )
}

export function TerminalLoader({
  className,
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  size?: Size
  tone?: LoaderTone
}) {
  const cursor = { xs: 'h-2.5 w-1', sm: 'h-3 w-1.5', md: 'h-4 w-2', lg: 'h-5 w-2.5' }[size]
  const text = { xs: 'text-[10px]', sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  const box = { xs: 'h-3', sm: 'h-4', md: 'h-5', lg: 'h-6' }[size]
  return (
    <div className={cn('flex items-center space-x-1', box, className)}>
      <span className={cn('font-mono', text)} style={{ color: toneColor[tone] }}>
        {'>'}
      </span>
      <div className={cn(cursor)} style={{ background: toneColor[tone], ...anim('blink', '1s', 'step-end') }} />
      <LoaderShell />
    </div>
  )
}

export function TextBlinkLoader({
  text = 'Thinking',
  className,
  size = 'md',
}: {
  text?: string
  className?: string
  size?: Size
}) {
  const textSize = { xs: 'text-xs', sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  return (
    <div className={cn('font-medium', textSize, className)} style={anim('text-blink', '2s', 'ease-in-out')}>
      {text}
    </div>
  )
}

export function TextShimmerLoader({
  text = 'Thinking',
  className,
  size = 'md',
}: {
  text?: string
  className?: string
  size?: Size
}) {
  const textSize = { xs: 'text-xs', sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
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

export function TextDotsLoader({
  className,
  text = 'Thinking',
  size = 'md',
  tone = 'brand',
}: {
  className?: string
  text?: string
  size?: Size
  tone?: LoaderTone
}) {
  const textSize = { xs: 'text-xs', sm: 'text-xs', md: 'text-sm', lg: 'text-base' }[size]
  return (
    <div className={cn('inline-flex items-center', className)}>
      <span className={cn('font-medium', textSize)} style={{ color: toneColor[tone] }}>
        {text}
      </span>
      <span className="inline-flex">
        {[0.2, 0.4, 0.6].map((d) => (
          <span key={d} style={{ color: toneColor[tone], ...anim('loading-dots', '1.4s'), animationDelay: `${d}s` }}>
            .
          </span>
        ))}
      </span>
    </div>
  )
}

export function Loader({ variant = 'circular', size = 'md', text, className, tone }: LoaderProps) {
  switch (variant) {
    case 'circular':
      return <CircularLoader size={size} className={className} tone={tone} />
    case 'classic':
      return <ClassicLoader size={size} className={className} tone={tone} />
    case 'pulse':
      return <PulseLoader size={size} className={className} tone={tone} />
    case 'pulse-dot':
      return <PulseDotLoader size={size} className={className} tone={tone} />
    case 'dots':
      return <DotsLoader size={size} className={className} tone={tone} />
    case 'typing':
      return <TypingLoader size={size} className={className} tone={tone} />
    case 'wave':
      return <WaveLoader size={size} className={className} tone={tone} />
    case 'bars':
      return <BarsLoader size={size} className={className} tone={tone} />
    case 'terminal':
      return <TerminalLoader size={size} className={className} tone={tone} />
    case 'text-blink':
      return <TextBlinkLoader text={text} size={size} className={className} />
    case 'text-shimmer':
      return <TextShimmerLoader text={text} size={size} className={className} />
    case 'loading-dots':
      return <TextDotsLoader text={text} size={size} className={className} tone={tone} />
    default:
      return <CircularLoader size={size} className={className} tone={tone} />
  }
}
