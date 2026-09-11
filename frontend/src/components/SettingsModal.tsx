import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, Eye, EyeOff, FileText, FolderOpen, Image as ImageIcon, Pencil, Plus, Search, Sparkles, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Loader } from '@/components/ai/Loader'
import { Input } from '@/components/ui/input'
import { ModalShell } from '@/components/ui/ModalShell'
import {
  copyModelKey,
  fetchAvailableModels,
  getSettings,
  isTauri,
  putModelKey,
  putModels,
  putOcrKeys,
  revealInFolder,
  testModelConnection,
  testModelDraft,
  type DraftTestResult,
  type ModelBody,
} from '@/api/client'
import { findKeySource, mergeModelOptions } from '@/lib/modelSettings'
import { useToast } from '@/context/Toast'

export interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

type SectionId = 'models' | 'parse' | 'general'

const SECTIONS: { id: SectionId; title: string; icon: typeof Sparkles }[] = [
  { id: 'models', title: '模型', icon: Sparkles },
  { id: 'parse', title: 'PaddleOCR-VL设置', icon: FileText },
  { id: 'general', title: '通用', icon: FolderOpen },
]

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  // open gate 必须有：ModalShell 无 open 概念，丢了它设置窗会常驻渲染（关闭回调
  // 全部生效但 UI 永不卸载）——旧 ui/dialog.tsx 的同款门控在双栏重构时弄丢过一次
  if (!open) return null
  const [section, setSection] = useState<SectionId>('models')
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    enabled: open,
  })

  // 能力状态条：按配置现算，配置齐备时不显示（提示不是门禁）。
  // 识别路由 = 文档解析（百度云）→ 图片识别模型（VLM）→ 降级，两条能力互补：
  // 有云端则 VLM 缺位不报警；无云端时 VLM 覆盖图片/扫描件，唯 .doc 必须走云端。
  const notices: { level: 'error' | 'warn'; text: string }[] = []
  if (settings) {
    const withKey = settings.models.filter((m) => m.key_configured)
    if (withKey.length === 0) {
      notices.push({ level: 'error', text: '没有已配 Key 的模型，无法对话——请添加模型并保存 API Key' })
    }
    const hasVision = settings.models.some((m) => m.image_support && m.key_configured)
    if (!hasVision && !settings.ocr.configured) {
      notices.push({
        level: 'warn',
        text: '未配置图片识别能力：图片、扫描版 PDF、.doc 均无法识别，仅存档原件——可配置文档解析（百度云），或为模型开启「图片输入」',
      })
    } else if (hasVision && !settings.ocr.configured) {
      notices.push({
        level: 'warn',
        text: '未配置文档解析：仅 .doc 无法识别；图片与扫描版 PDF 将由图片识别模型转写（整本扫描件走云端效果更好）',
      })
    }
  }

  return (
    <ModalShell onClose={onClose} cardClassName="h-[min(85vh,660px)] w-[min(92vw,920px)]">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <h2 className="text-[17px] font-semibold">设置</h2>
        <button
          type="button"
          onClick={onClose}
          className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="关闭设置"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-48 shrink-0 flex-col gap-1 border-r bg-muted/40 p-3">
          {SECTIONS.map((s) => {
            const Icon = s.icon
            const active = section === s.id
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setSection(s.id)}
                className={`flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  active ? 'bg-secondary font-medium text-primary' : 'text-muted-foreground hover:bg-secondary/60'
                }`}
              >
                <Icon className="h-[18px] w-[18px] shrink-0" />
                {s.title}
              </button>
            )
          })}
        </nav>

        <div className="min-w-0 flex-1 overflow-y-auto px-6 py-5">
          {notices.length > 0 && (
            <div className="mb-4 space-y-1.5">
              {notices.map((n) => (
                <p
                  key={n.text}
                  className={`rounded-lg border px-3.5 py-2 text-[13px] leading-relaxed ${
                    n.level === 'error'
                      ? 'border-error/40 bg-error/5 text-error'
                      : 'border-line bg-muted/50 text-muted-foreground'
                  }`}
                >
                  {n.text}
                </p>
              ))}
            </div>
          )}

          {section === 'models' && <ModelsSection settings={settings} />}
          {section === 'parse' && <ParseSection />}
          {section === 'general' && <GeneralSection settings={settings} />}
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// 模型区：profile 列表制（多模型；Key 存本地库 app_settings，只写不回读）。
// 添加/编辑是二级弹窗（WorkBuddy 式）：提供商可搜索下拉 → 厂商预设只填 Key+选模型，
// 自定义才露接口地址；厂商预设只是填表快捷方式不当真值。
// ---------------------------------------------------------------------------

/** 列表/表单共用的本地形状（编辑中的草稿；保存时全量 PUT） */
interface LocalModel {
  id: string
  name: string
  baseUrl: string
  model: string
  imageSupport: boolean
  /** 上下文窗口（token）；null=未设置（自动）。高级选项里显式保存才生效 */
  contextWindow: number | null
  keySaved: boolean
}

interface VendorPreset {
  key: string
  /** 下拉里显示的全名 */
  label: string
  /** 列表行 / 自动命名用的短名 */
  short: string
  baseUrl: string
  mono: string
  color: string
  models: { name: string; imageSupport: boolean; contextWindow?: number }[]
}

/** 上下文窗口预设档（值=token 数；null=自动/未知）。下限 256K（2026-09-08 用户拍板，
 *  更小的档位在标书场景只有误配风险）。「自动」= 不干预压缩触发档位：langchain 注册表
 *  认识模型名（deepseek 系等）走窗口 85% 比例档，不认识的走保守固定线（17 万 token）+超限自愈 */
const CONTEXT_WINDOW_OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: '自动（默认）' },
  { value: 256000, label: '256K' },
  { value: 512000, label: '512K' },
  { value: 1000000, label: '1M' },
  { value: 2000000, label: '2M' },
]

/** 旧档案可能存有低于现行下限（256K）的窗口值：不在列表里时按数值格式化显示，不冒充「自动」 */
function formatContextWindow(v: number): string {
  return v >= 1000000 ? `${v / 1000000}M` : `${Math.round(v / 1000)}K`
}

const VENDOR_PRESETS: VendorPreset[] = [
  {
    key: 'deepseek',
    label: '深度求索 / DeepSeek',
    short: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    mono: 'D',
    color: '#4D6BFE',
    models: [
      { name: 'deepseek-v4-flash', imageSupport: false },
      { name: 'deepseek-v4-pro', imageSupport: false },
      { name: 'deepseek-v4-flash-vision-exp', imageSupport: true },
    ],
  },
  {
    key: 'moonshot',
    label: 'Kimi / Moonshot',
    short: 'Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    mono: 'K',
    color: '#16191E',
    models: [
      { name: 'kimi-k3', imageSupport: true, contextWindow: 256000 },
      { name: 'kimi-k2-thinking', imageSupport: false, contextWindow: 256000 },
      { name: 'kimi-k2.7-code', imageSupport: false, contextWindow: 256000 },
    ],
  },
  {
    key: 'dashscope',
    label: '阿里云百炼 / DashScope',
    short: '百炼',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    mono: 'A',
    color: '#FF6A00',
    models: [
      { name: 'qwen3-max', imageSupport: false, contextWindow: 256000 },
      { name: 'qwen-plus', imageSupport: false },
      { name: 'qwen3-vl-plus', imageSupport: true },
    ],
  },
  {
    key: 'zhipu',
    label: '智谱 / GLM',
    short: '智谱',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    mono: 'Z',
    color: '#3859FF',
    models: [
      { name: 'glm-5.1', imageSupport: false, contextWindow: 256000 },
      { name: 'glm-5', imageSupport: false, contextWindow: 256000 },
      { name: 'glm-4.6v', imageSupport: true },
    ],
  },
  {
    key: 'volc',
    label: '火山方舟 / Volcengine',
    short: '方舟',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    mono: 'V',
    color: '#1664FF',
    models: [
      { name: 'doubao-seed-1.6', imageSupport: true, contextWindow: 256000 },
      { name: 'doubao-seed-1.6-flash', imageSupport: true, contextWindow: 256000 },
    ],
  },
  {
    key: 'minimax',
    label: 'MiniMax',
    short: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    mono: 'M',
    color: '#E8503A',
    models: [
      { name: 'MiniMax-M2.5', imageSupport: false },
      { name: 'MiniMax-M2.5-highspeed', imageSupport: false },
    ],
  },
  {
    key: 'openai',
    label: 'OpenAI',
    short: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    mono: 'O',
    color: '#10A37F',
    models: [
      { name: 'gpt-5.6', imageSupport: true },
      { name: 'gpt-5.5', imageSupport: true },
      { name: 'gpt-5', imageSupport: true },
    ],
  },
]

const CUSTOM_PRESET: VendorPreset = {
  key: 'custom',
  label: '自定义 / Custom',
  short: '自定义',
  baseUrl: '',
  mono: '',
  color: '',
  models: [],
}

const ALL_PRESETS = [...VENDOR_PRESETS, CUSTOM_PRESET]

const presetOfBaseUrl = (url: string | undefined): VendorPreset | undefined =>
  ALL_PRESETS.find((p) => p.baseUrl && p.baseUrl === url)

const toModelBody = (m: LocalModel): ModelBody => ({
  id: m.id,
  name: m.name || m.id,
  base_url: m.baseUrl,
  model: m.model,
  image_support: m.imageSupport,
  ...(m.contextWindow != null ? { context_window: m.contextWindow } : {}),
})

/** 显示名自动派生：厂商=preset 短名（同厂商第二个起追加模型名）；自定义=模型名 */
const deriveName = (list: LocalModel[], id: string, preset: VendorPreset, model: string): string => {
  const m = model.trim()
  if (preset.key === 'custom') return m || '自定义模型'
  return list.some((x) => x.id !== id && x.name === preset.short) ? `${preset.short} · ${m}` : preset.short
}

function PresetAvatar({ p, className }: { p: VendorPreset; className?: string }) {
  if (p.key === 'custom') {
    return (
      <span className={cn('grid h-5 w-5 shrink-0 place-items-center rounded border border-dashed border-line text-muted-foreground', className)}>
        <Plus className="h-3 w-3" />
      </span>
    )
  }
  return (
    <span
      className={cn('grid h-5 w-5 shrink-0 place-items-center rounded text-[11px] font-semibold text-white', className)}
      style={{ backgroundColor: p.color }}
    >
      {p.mono}
    </span>
  )
}

// --- 排版基本件（WorkBuddy 式）：卡片外框 / 设置行 / 开关，三个 section 共用 ----

/** 设置卡片统一外框：白底靠描边区分层级（不用灰底强调），内边距放大 */
function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('rounded-xl border border-line px-5 py-4', className)}>{children}</div>
}

/** 设置行：左「标题+描述」右控件。 */
function SettingRow({
  title,
  desc,
  children,
  className,
}: {
  title: React.ReactNode
  desc?: React.ReactNode
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-center justify-between gap-4', className)}>
      <div className="min-w-0">
        <p className="text-sm font-medium leading-snug">{title}</p>
        {desc && <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{desc}</p>}
      </div>
      {children != null && <div className="shrink-0">{children}</div>}
    </div>
  )
}

/** 开关（替代原生 checkbox）：off 中性墨系——ink 20% 轨道+1px 内描边（边界清晰、
 *  白圆点不发虚），on 品牌色轨道（2026-09-08 用户拍板，推翻 09-07 的去彩色审计）；
 *  焦点 = 1px 细描边（克制铁则，禁光晕） */
function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'group relative h-[22px] w-10 shrink-0 rounded-full transition-colors',
        'focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-ring',
        checked
          ? 'bg-primary hover:bg-primary-hover'
          : 'bg-ink/20 hover:bg-ink/30 ring-1 ring-inset ring-line-2',
      )}
    >
      <span
        className={cn(
          'absolute left-0.5 top-0.5 h-[18px] w-[18px] rounded-full bg-background shadow-sm transition-transform group-active:scale-90',
          checked && 'translate-x-[18px]',
        )}
      />
    </button>
  )
}

function ModelsSection({ settings }: { settings: Awaited<ReturnType<typeof getSettings>> | undefined }) {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [models, setModels] = useState<LocalModel[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [roles, setRoles] = useState<{ extract: string; vision: string }>({ extract: '', vision: '' })
  // null=列表态；'new'=新增；否则=编辑该 id（弹窗盖在列表上）
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 两步删除（arming 中的行 id，3 秒复位）与高级区展开态
  const [confirmDelId, setConfirmDelId] = useState<string | null>(null)
  const [rolesOpen, setRolesOpen] = useState(false)

  useEffect(() => {
    if (settings) {
      setModels(
        settings.models.map((m) => ({
          id: m.id,
          name: m.name,
          baseUrl: m.base_url,
          model: m.model,
          imageSupport: m.image_support,
          contextWindow: m.context_window ?? null,
          keySaved: m.key_configured,
        })),
      )
      setDefaultModel(settings.default_model)
      setRoles({
        extract: settings.background_roles?.extract || '',
        vision: settings.background_roles?.vision || '',
      })
    }
  }, [settings])

  const commit = (list: LocalModel[], dflt: string) => {
    setModels(list)
    setDefaultModel(dflt)
    void queryClient.invalidateQueries({ queryKey: ['settings'] })
  }

  const persistList = async (
    list: LocalModel[],
    dflt: string,
    rolesOverride?: { extract: string; vision: string },
  ): Promise<boolean> => {
    setError(null)
    try {
      const r = rolesOverride ?? roles
      await putModels(list.map(toModelBody), dflt, { extract: r.extract, vision: r.vision })
      commit(list, dflt)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    }
  }

  // 二次确认在行内（两步删除），此处不再弹原生 confirm
  const removeModel = async (m: LocalModel) => {
    const list = models.filter((x) => x.id !== m.id)
    let dflt = defaultModel
    if (dflt === m.id) dflt = list[0]?.id ?? ''
    // 被删模型若被指派为后台角色，一并清空（服务端对未知 id 也会回落，双保险）
    const nextRoles = { ...roles }
    if (nextRoles.extract === m.id) nextRoles.extract = ''
    if (nextRoles.vision === m.id) nextRoles.vision = ''
    setRoles(nextRoles)
    if (!(await persistList(list, dflt, nextRoles))) return
    toast('模型已删除', 'success')
  }

  const changeRole = async (key: 'extract' | 'vision', pid: string) => {
    if (roles[key] === pid) return
    const next = { ...roles, [key]: pid }
    setRoles(next)
    if (!(await persistList(models, defaultModel, next))) return
    toast('后台任务模型已更新，即时生效', 'success')
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <p className="text-[13px] text-muted-foreground">模型与 API Key 只保存在本机，不上传</p>
        <Button size="sm" onClick={() => setEditing('new')}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加模型
        </Button>
      </div>

      {models.length === 0 && (
        <p className="rounded-xl border border-dashed border-line p-6 text-center text-sm text-muted-foreground">
          还没有配置模型——点击「添加模型」，选一家厂商后填写 API Key 与模型名
        </p>
      )}

      {models.map((m) => {
        return (
          <div key={m.id} className="flex items-center gap-3 rounded-xl border border-line px-4 py-3.5">
            <PresetAvatar p={presetOfBaseUrl(m.baseUrl) ?? CUSTOM_PRESET} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-sm font-medium">{m.name}</span>
                {m.imageSupport && (
                  <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-accent-soft px-1.5 py-px text-[11px] text-primary">
                    <ImageIcon className="h-2.5 w-2.5" />
                    图片
                  </span>
                )}
                <span className={cn('ml-auto shrink-0 text-[11px]', m.keySaved ? 'text-success' : 'text-error')}>
                  {m.keySaved ? 'Key 已配置' : 'Key 未配置'}
                </span>
              </div>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {m.model} · {m.baseUrl.replace(/^https?:\/\//, '')}
              </p>
            </div>
            <button
              type="button"
              title="编辑"
              aria-label="编辑"
              onClick={() => setEditing(m.id)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Pencil className="h-4 w-4" />
            </button>
            {confirmDelId === m.id ? (
              <span className="flex shrink-0 items-center gap-1 text-xs">
                <button
                  type="button"
                  onClick={() => {
                    setConfirmDelId(null)
                    void removeModel(m)
                  }}
                  className="rounded-md bg-destructive px-2 py-1 font-medium text-destructive-foreground hover:opacity-90"
                >
                  确认删除
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDelId(null)}
                  className="rounded-md px-2 py-1 text-muted-foreground hover:bg-muted"
                >
                  取消
                </button>
              </span>
            ) : (
              <button
                type="button"
                title="删除"
                aria-label="删除"
                onClick={() => {
                  setConfirmDelId(m.id)
                  window.setTimeout(() => setConfirmDelId((cur) => (cur === m.id ? null : cur)), 3000)
                }}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-error"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        )
      })}

      {error && <p className="text-sm text-error">{error}</p>}

      <div className="rounded-xl border border-line px-5 py-4">
        <button
          type="button"
          onClick={() => setRolesOpen(!rolesOpen)}
          aria-expanded={rolesOpen}
          className="flex w-full cursor-pointer items-center gap-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          后台任务模型（高级）
          <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', rolesOpen && 'rotate-180')} />
        </button>
        {rolesOpen && (
          <div className="space-y-4 pt-4">
            <SettingRow title="知识库 metadata 抽取" desc="为上传条目建议类型与字段（可指定便宜模型省 token）">
              <RoleSelect
                value={roles.extract}
                emptyLabel="跟随默认模型"
                options={models.map((m) => ({ id: m.id, label: m.name }))}
                onChange={(pid) => void changeRole('extract', pid)}
              />
            </SettingRow>
            <SettingRow title="知识库视觉转写" desc="图片 / 扫描页转文字（仅列已开启「图片输入」的模型）">
              <RoleSelect
                value={roles.vision}
                emptyLabel="自动（默认模型优先）"
                options={models.filter((m) => m.imageSupport).map((m) => ({ id: m.id, label: m.name }))}
                onChange={(pid) => void changeRole('vision', pid)}
              />
            </SettingRow>
            <p className="text-xs leading-relaxed text-muted-foreground">
              文档解析本身不走大模型（本地确定性解析 + PaddleOCR-VL 云端）；这里的模型只用于解析后的后台轻任务。
            </p>
          </div>
        )}
      </div>

      {editing !== null && (
        <ModelDialog
          key={editing}
          isNew={editing === 'new'}
          initial={editing === 'new' ? null : (models.find((m) => m.id === editing) ?? null)}
          models={models}
          defaultModel={defaultModel}
          onCommit={commit}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

// --- 后台任务角色下拉（小面板向上弹，避免被设置窗底边裁掉） -----------------

function RoleSelect({
  value,
  emptyLabel,
  options,
  onChange,
}: {
  value: string
  emptyLabel: string
  options: { id: string; label: string }[]
  onChange: (pid: string) => void
}) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null
      if (t && !t.closest('[data-role-select]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  const current = options.find((o) => o.id === value)

  const item = (pid: string, label: string) => (
    <button
      key={pid || '__empty__'}
      type="button"
      onClick={() => {
        onChange(pid)
        setOpen(false)
      }}
      className={cn(
        'flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]',
        pid === value ? 'bg-accent-soft' : 'hover:bg-secondary',
      )}
    >
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {pid === value && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
    </button>
  )

  return (
    <div
      className="relative shrink-0"
      data-role-select
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation()
          setOpen(false)
        }
      }}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex h-8 items-center gap-1.5 rounded-lg border border-line bg-card px-2.5 text-[13px] transition-colors hover:bg-secondary/50"
        title="后台任务使用的模型"
      >
        <span className="max-w-[180px] truncate">{value ? (current?.label ?? value) : emptyLabel}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute bottom-full right-0 z-20 mb-1.5 w-56 rounded-lg border border-line bg-card py-1 shadow-md">
          {item('', emptyLabel)}
          {options.length > 0 && <div className="my-1 border-t border-line" />}
          {options.map((o) => item(o.id, o.label))}
        </div>
      )}
    </div>
  )
}

// --- 添加/编辑模型二级弹窗 -------------------------------------------------

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-[13px] font-medium">{label}</label>
      {children}
    </div>
  )
}

/** 提供商下拉：可搜索、带厂商色块；分组=API 厂商 / 其他（自定义） */
function ProviderSelect({ value, onChange }: { value: string; onChange: (key: string) => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null
      if (t && !t.closest('[data-provider-select]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  const kw = q.trim().toLowerCase()
  const hit = ALL_PRESETS.filter(
    (p) => !kw || p.label.toLowerCase().includes(kw) || p.short.toLowerCase().includes(kw),
  )
  const vendors = hit.filter((p) => p.key !== 'custom')
  const hasCustom = hit.some((p) => p.key === 'custom')

  const row = (p: VendorPreset) => (
    <button
      key={p.key}
      type="button"
      onClick={() => {
        onChange(p.key)
        setOpen(false)
        setQ('')
      }}
      className={cn(
        'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm',
        p.key === value ? 'bg-accent-soft' : 'hover:bg-secondary',
      )}
    >
      <PresetAvatar p={p} />
      <span className="min-w-0 flex-1 truncate">{p.label}</span>
      {p.key === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
    </button>
  )

  return (
    <div
      className="relative"
      data-provider-select
      data-dropdown-open={open || undefined}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation() // 只关下拉，不关弹窗（closed 时放行给上层）
          setOpen(false)
        }
      }}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex h-9 w-full items-center gap-2.5 rounded-lg border border-line bg-card px-3 text-sm transition-colors hover:bg-secondary/50"
      >
        <PresetAvatar p={ALL_PRESETS.find((p) => p.key === value) ?? CUSTOM_PRESET} />
        <span className="min-w-0 flex-1 truncate text-left">
          {(ALL_PRESETS.find((p) => p.key === value) ?? CUSTOM_PRESET).label}
        </span>
        <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1.5 rounded-xl border border-line bg-card py-1 shadow-md">
          <div className="flex items-center gap-2 border-b border-line px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索提供商"
              className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div className="max-h-60 overflow-y-auto py-1">
            {vendors.length > 0 && <p className="px-3 pb-1 pt-1.5 text-[11px] text-muted-foreground">API 厂商</p>}
            {vendors.map(row)}
            {hasCustom && (
              <>
                <div className="my-1 border-t border-line" />
                <p className="px-3 pb-1 pt-1 text-[11px] text-muted-foreground">其他</p>
                {ALL_PRESETS.filter((p) => p.key === 'custom').map(row)}
              </>
            )}
            {hit.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">无匹配的提供商</p>}
          </div>
        </div>
      )}
    </div>
  )
}

/** 模型名下拉：服务商实际清单（拉取成功时）+ 内置常用预设，分组展示（拉取多时可搜）；
 *  尾部「自定义模型名…」逃生口。未拉取到清单时退回纯预设列表（与旧行为一致）。 */
function ModelNameSelect({
  preset,
  fetched,
  value,
  onPick,
  onCustom,
}: {
  preset: VendorPreset
  fetched: string[]
  value: string
  onPick: (m: { name: string; imageSupport?: boolean }) => void
  onCustom: () => void
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null
      if (t && !t.closest('[data-model-name-select]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  const groups = mergeModelOptions(fetched, preset.models)
  const kw = q.trim().toLowerCase()
  const shown = groups
    .map((g) => ({ ...g, models: kw ? g.models.filter((m) => m.name.toLowerCase().includes(kw)) : g.models }))
    .filter((g) => g.models.length > 0)
  const showSearch = groups.some((g) => g.models.length > 8)

  return (
    <div
      className="relative flex-1"
      data-model-name-select
      data-dropdown-open={open || undefined}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation() // 只关下拉，不关弹窗（closed 时放行给上层）
          setOpen(false)
        }
      }}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-line bg-card px-3 text-sm transition-colors hover:bg-secondary/50"
      >
        <span className="min-w-0 flex-1 truncate text-left font-mono text-[13px]">{value || '选择模型'}</span>
        <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1.5 max-h-64 overflow-y-auto rounded-xl border border-line bg-card py-1 shadow-md">
          {showSearch && (
            <div className="sticky top-0 flex items-center gap-2 border-b border-line bg-card px-3 py-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索模型"
                className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
          )}
          {shown.map((g) => (
            <div key={g.label}>
              <p className="px-3 pb-1 pt-1.5 text-[11px] text-muted-foreground">{g.label}</p>
              {g.models.map((m) => (
                <button
                  key={`${g.label}:${m.name}`}
                  type="button"
                  onClick={() => {
                    onPick(m)
                    setOpen(false)
                  }}
                  className={cn(
                    'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm',
                    m.name === value ? 'bg-accent-soft' : 'hover:bg-secondary',
                  )}
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{m.name}</span>
                  {m.imageSupport && <ImageIcon className="h-3 w-3 shrink-0 text-muted-foreground" aria-label="支持图片" />}
                  {m.name === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
                </button>
              ))}
            </div>
          ))}
          {shown.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">无匹配模型</p>}
          <div className="my-1 border-t border-line" />
          <button
            type="button"
            onClick={() => {
              onCustom()
              setOpen(false)
            }}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-muted-foreground hover:bg-secondary"
          >
            <Plus className="h-3.5 w-3.5" />
            自定义模型名…
          </button>
        </div>
      )}
    </div>
  )
}

/** 上下文窗口下拉（克隆 ModelNameSelect 模式：data-dropdown-open 让位弹窗 Escape、
 *  top-full 面板；卡片无 overflow-hidden 是面板不被裁剪的前提，勿加） */
function ContextWindowSelect({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  const [open, setOpen] = useState(false)
  const current =
    CONTEXT_WINDOW_OPTIONS.find((o) => o.value === value) ??
    (value != null ? { value, label: formatContextWindow(value) } : CONTEXT_WINDOW_OPTIONS[0])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null
      if (t && !t.closest('[data-context-window-select]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  return (
    <div
      className="relative"
      data-context-window-select
      data-dropdown-open={open || undefined}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation() // 只关下拉，不关弹窗（closed 时放行给上层）
          setOpen(false)
        }
      }}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-line bg-card px-3 text-sm transition-colors hover:bg-secondary/50"
      >
        <span className="min-w-0 flex-1 truncate text-left">{current.label}</span>
        <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1.5 max-h-64 overflow-y-auto rounded-xl border border-line bg-card py-1 shadow-md">
          {CONTEXT_WINDOW_OPTIONS.map((o) => (
            <button
              key={o.label}
              type="button"
              onClick={() => {
                onChange(o.value)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm',
                o.value === value ? 'bg-accent-soft' : 'hover:bg-secondary',
              )}
            >
              <span className="min-w-0 flex-1 truncate">{o.label}</span>
              {o.value === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ModelDialog({
  initial,
  isNew,
  models,
  defaultModel,
  onCommit,
  onClose,
}: {
  initial: LocalModel | null
  isNew: boolean
  models: LocalModel[]
  defaultModel: string
  onCommit: (list: LocalModel[], dflt: string) => void
  onClose: () => void
}) {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  // 新增默认第一家厂商预设（地址/模型一并预填），编辑按 baseUrl 反推
  const [providerKey, setProviderKey] = useState(
    () => presetOfBaseUrl(initial?.baseUrl)?.key ?? (initial ? 'custom' : VENDOR_PRESETS[0].key),
  )
  const preset = ALL_PRESETS.find((p) => p.key === providerKey) ?? CUSTOM_PRESET
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? (VENDOR_PRESETS[0].baseUrl as string))
  const [model, setModel] = useState(initial?.model ?? VENDOR_PRESETS[0].models[0]?.name ?? '')
  const [customModel, setCustomModel] = useState(() => {
    if (!initial) return false
    const p = presetOfBaseUrl(initial.baseUrl)
    return !p || !p.models.some((m) => m.name === initial.model)
  })
  const [imageSupport, setImageSupport] = useState(
    initial?.imageSupport ?? (VENDOR_PRESETS[0].models[0]?.imageSupport ?? false),
  )
  const [contextWindow, setContextWindow] = useState<number | null>(initial?.contextWindow ?? null)
  const [advOpen, setAdvOpen] = useState(false)
  const [key, setKey] = useState('')
  const [keySaved, setKeySaved] = useState(initial?.keySaved ?? false)
  const [showKey, setShowKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 服务商实际模型清单（「获取模型列表」拉到后填充；失败保持空=回落常用预设）
  const [fetched, setFetched] = useState<string[]>([])
  const [fetching, setFetching] = useState(false)
  // 连通性测试结果（就地展示，不落 toast、不保存）
  const [testResult, setTestResult] = useState<DraftTestResult | null>(null)

  // 已保存过的 profile id 沿用（Key 按模型 id 存本地库）；新模型生成 uuid
  const [pid] = useState(initial?.id ?? `m_${crypto.randomUUID().slice(0, 8)}`)

  // 同厂商已配 Key 的兄弟：Key 留空时复用其 Key（测试借用 / 保存时服务端 copy）
  const keySource = findKeySource(models, baseUrl, isNew ? undefined : pid)
  // key_ref 兜底：编辑已配 Key 的模型时借用自身已存 Key
  const keyRef = key.trim() ? undefined : (keySource?.id ?? (keySaved ? pid : undefined))
  const canFetch = !!key.trim() || !!keyRef

  // Escape 关本弹窗：必须挂 window 捕获段——点「添加模型」后焦点常停在弹窗后面的
  // 列表按钮上，keydown 目标不在卡片子树，卡片上的 React onKeyDown 不在传播路径里，
  // 事件会直达 window 把设置窗一起关掉。下拉打开时让位（下拉的 React handler
  // 会 stopPropagation 截停在 React root，同样到不了 ModalShell 的 window 监听）。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const t = e.target as HTMLElement | null
      if (t && t.closest('[data-dropdown-open]')) return
      e.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const applyProvider = (k: string) => {
    setProviderKey(k)
    const p = ALL_PRESETS.find((x) => x.key === k) ?? CUSTOM_PRESET
    if (p.baseUrl) setBaseUrl(p.baseUrl)
    if (p.models.length > 0) {
      setModel(p.models[0].name)
      setImageSupport(p.models[0].imageSupport)
      setCustomModel(false)
    } else {
      setCustomModel(true) // 自定义：保留当前地址供编辑
    }
    setFetched([]) // 换厂商：旧的拉取清单作废
    setTestResult(null)
    setError(null)
  }

  /** 用草稿/兄弟 Key 调服务商 /models，填充模型名下拉；失败静默回落常用预设。 */
  const fetchModels = async () => {
    setError(null)
    setFetching(true)
    try {
      const r = await fetchAvailableModels({
        base_url: baseUrl.trim(),
        ...(key.trim() ? { api_key: key.trim() } : { key_ref: keyRef }),
      })
      if (r.ok && r.models.length > 0) {
        setFetched(r.models)
        setCustomModel(false)
        // 只填空、不覆盖：用户已填的模型名保持不动（拉取只是给他更多候选）
        if (!model.trim()) {
          setModel(r.models[0])
          const meta = preset.models.find((m) => m.name === r.models[0])
          if (meta) setImageSupport(meta.imageSupport)
        }
        toast(`已获取 ${r.models.length} 个模型`, 'success')
      } else {
        toast('无法获取模型列表，请手动填写模型名', 'error')
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setFetching(false)
    }
  }

  /** 展开高级选项那一刻预填厂商建议窗口值（仅草稿层，点保存才落库；已手动选过不跟随）。
   *  不在切模型/切厂商时跟随，保持「用户看到的选择即他所做的选择」。 */
  const changeAdvOpen = (open: boolean) => {
    setAdvOpen(open)
    if (open && contextWindow == null) {
      const entry = preset.models.find((m) => m.name === model.trim())
      if (entry?.contextWindow) setContextWindow(entry.contextWindow)
    }
  }

  /** 保存模型配置（+ 可选的新 Key）。返回错误文案，null=成功（不关弹窗，由调用方决定） */
  const persist = async (): Promise<string | null> => {
    const draft: LocalModel = {
      id: pid,
      name: deriveName(models, pid, preset, model),
      baseUrl: baseUrl.trim(),
      model: model.trim(),
      imageSupport,
      contextWindow,
      keySaved: keySaved || !!key.trim(),
    }
    if (!draft.model) return '请填写模型名称'
    if (!draft.baseUrl) return '请填写接口地址'
    const list = isNew ? [...models, draft] : models.map((m) => (m.id === pid ? draft : m))
    // 唯一一条时自动设为默认；默认模型被删时回落第一条
    let dflt = defaultModel
    if (!list.some((m) => m.id === dflt)) dflt = list[0]?.id ?? ''
    if (list.length === 1) dflt = list[0].id
    try {
      await putModels(list.map(toModelBody), dflt)
      // Key 处理：填了新值 → 写入；留空但有同厂商兄弟 Key → 复用（服务端读源写目标）
      if (key.trim()) {
        try {
          await putModelKey(pid, key.trim())
          setKey('')
          setKeySaved(true)
        } catch (e) {
          // 半成功：模型列表已在服务器生效——照常提交本地并失效缓存保持两边一致，
          // 文案明确半成功；重按保存只重试 Key（putModels 幂等重放，无重复副作用）
          onCommit(list, dflt)
          void queryClient.invalidateQueries({ queryKey: ['settings'] })
          const msg = e instanceof Error ? e.message : String(e)
          return `模型配置已保存，但 API Key 保存失败：${msg}`
        }
      } else if (!keySaved && keySource) {
        try {
          await copyModelKey(keySource.id, pid)
          setKeySaved(true)
        } catch (e) {
          onCommit(list, dflt)
          void queryClient.invalidateQueries({ queryKey: ['settings'] })
          const msg = e instanceof Error ? e.message : String(e)
          return `模型配置已保存，但复用「${keySource.name}」的 Key 失败：${msg}`
        }
      }
      onCommit(list, dflt)
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return null
    } catch (e) {
      return e instanceof Error ? e.message : String(e)
    }
  }

  const save = async () => {
    setError(null)
    setSaving(true)
    const err = await persist()
    setSaving(false)
    if (err) {
      setError(err)
      return
    }
    toast(isNew ? '模型已添加' : '模型已保存', 'success')
    onClose()
  }

  /** 测「表单当前值」：填好即测，不保存、不落库（保存归「保存」按钮）。
   *  Key 留空时借用同厂商兄弟的 Key（key_ref），与保存时的复用语义一致。 */
  const test = async () => {
    setError(null)
    setTestResult(null)
    const url = baseUrl.trim()
    const name = model.trim()
    if (!url) {
      setError('请填写接口地址')
      return
    }
    if (!name) {
      setError('请填写模型名称')
      return
    }
    if (!key.trim() && !keySource && !keySaved) {
      setError('请填写 API Key（或先为同厂商的模型配置 Key 以便复用）')
      return
    }
    setTesting(true)
    try {
      const r = await testModelDraft({
        base_url: url,
        model: name,
        ...(key.trim() ? { api_key: key.trim() } : { key_ref: keyRef }),
        // 「图片输入」开关开启时附带图片探测（1×1 PNG ping），验证声明是否属实
        ...(imageSupport ? { with_image: true } : {}),
      })
      setTestResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      {/* 不能加 overflow-hidden：提供商下拉要从卡片里溢出来，加了会把「自定义」裁掉 */}
      <div className="relative z-10 flex w-[min(92vw,480px)] flex-col rounded-2xl border bg-card shadow-md">
        <div className="flex items-center gap-2.5 border-b border-line px-5 py-4">
          <h3 className="text-base font-semibold">{isNew ? '添加模型' : '编辑模型'}</h3>
          <span className="rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground">
            仅支持 OpenAI 兼容协议 API
          </span>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5 px-5 py-5">
          <Field label="提供商">
            <ProviderSelect value={providerKey} onChange={applyProvider} />
          </Field>

          {preset.key === 'custom' && (
            <Field label="接口地址">
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </Field>
          )}

          <Field
            label={
              <>
                API Key {keySaved && <span className="ml-1 font-normal text-success">已保存</span>}
              </>
            }
          >
            <div className="relative">
              <Input
                type={showKey ? 'text' : 'password'}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={keySaved ? '已配置，输入新值可更换' : '输入你的 API Key'}
                className="pr-9"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showKey ? '隐藏 Key' : '显示 Key'}
              >
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {!key.trim() && keySource && (
              <p className="text-xs leading-relaxed text-muted-foreground">
                留空将复用「{keySource.name}」已保存的 Key（同一接口地址）
              </p>
            )}
          </Field>

          <Field label="模型名称">
            <div className="flex gap-2">
              {((preset.models.length > 0 || fetched.length > 0) && !customModel) ? (
                <ModelNameSelect
                  preset={preset}
                  fetched={fetched}
                  value={model}
                  onPick={(m) => {
                    setModel(m.name)
                    if (m.imageSupport != null) setImageSupport(m.imageSupport)
                  }}
                  onCustom={() => {
                    setCustomModel(true)
                    setModel('')
                  }}
                />
              ) : (
                <>
                  <Input
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="输入模型参数值，例如 gpt-4o 或 openai/gpt-4o"
                  />
                  {(preset.models.length > 0 || fetched.length > 0) && (
                    <Button size="sm" variant="outline" className="shrink-0" onClick={() => setCustomModel(false)}>
                      列表
                    </Button>
                  )}
                </>
              )}
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                disabled={fetching || !canFetch}
                title={canFetch ? '从服务商拉取可用模型清单' : '请先填写 API Key（或为同厂商模型配置 Key）'}
                onClick={() => void fetchModels()}
              >
                {fetching && <Loader variant="circular" size="xs" tone="current" />}
                {fetching ? '获取中…' : '获取列表'}
              </Button>
            </div>
          </Field>

          <SettingRow
            title="图片输入"
            desc="开启后用于知识库图片 / 扫描件识别（已配置文档解析时优先走百度云，此处为兜底）；「测试连接」会附带探测服务方是否接受图片"
          >
            <Switch checked={imageSupport} onChange={setImageSupport} label="图片输入" />
          </SettingRow>

          {/* 高级选项折叠区：条件渲染而非 Collapsible——后者的动画包装层自带
              overflow-hidden，会把内部下拉面板裁掉（浮层禁溢出铁则） */}
          <div className="border-t border-line pt-4">
            <button
              type="button"
              onClick={() => changeAdvOpen(!advOpen)}
              aria-expanded={advOpen}
              className="flex w-full cursor-pointer items-center gap-1.5 text-left text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              高级选项
              <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 transition-transform', advOpen && 'rotate-180')} />
            </button>
            {advOpen && (
              <div className="pt-4">
                <Field label="上下文窗口">
                  <ContextWindowSelect value={contextWindow} onChange={setContextWindow} />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    模型单次能读入的最大 token 量，影响长会话自动压缩的触发时机。不清楚请保持「自动」；选大了会晚于真实窗口、依赖超限自动恢复，选小了会过早压缩上下文。
                  </p>
                </Field>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-2 border-t border-line px-5 py-3.5">
          {testResult && !error && (
            <p
              className={cn(
                'whitespace-pre-line text-[13px] leading-relaxed',
                testResult.ok ? 'text-success' : 'text-error',
              )}
            >
              {testResult.ok
                ? `连接正常 · ${(testResult.latency_ms / 1000).toFixed(1)}s`
                : testResult.message}
            </p>
          )}
          {testResult && testResult.image_ok != null && (
            <p className={cn('text-[13px] leading-relaxed', testResult.image_ok ? 'text-success' : 'text-error')}>
              图片输入{testResult.image_message}
            </p>
          )}
          <div className="flex items-center gap-2">
            {error ? (
              <p className="min-w-0 flex-1 text-sm leading-relaxed text-error">{error}</p>
            ) : (
              <span className="flex-1" />
            )}
            <Button size="sm" variant="outline" disabled={testing} onClick={() => void test()}>
              {testing && <Loader variant="circular" size="xs" tone="current" />}
              {testing ? '测试中…' : '测试连接'}
            </Button>
            <Button size="sm" variant="outline" onClick={onClose}>
              取消
            </Button>
            <Button size="sm" disabled={saving} onClick={() => void save()}>
              {saving && <Loader variant="circular" size="xs" tone="current" />}
              {saving ? '保存中…' : '保存'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 文档解析区：百度云 PaddleOCR-VL（AK/SK 存本地库，只写不回读）
// ---------------------------------------------------------------------------

function ParseSection() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [apiKey, setApiKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [showSecret, setShowSecret] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const configured = settings?.ocr.configured ?? false

  const saveKeys = async () => {
    setError(null)
    try {
      await putOcrKeys(apiKey, secretKey)
      setApiKey('')
      setSecretKey('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      toast('文档解析凭证已保存，即时生效', 'success')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const testConnection = async () => {
    setError(null)
    setTesting(true)
    try {
      const r = await testModelConnection({ role: 'ocr' })
      toast(r.ok ? '连接正常' : '连接失败', r.ok ? 'success' : 'error')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="text-[15px] font-semibold">百度云文档解析（PaddleOCR-VL）</div>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
          用于扫描版 PDF、.doc 与图片的云端识别（任务文件区与知识库通用）。按量计费，
          文件内容将发送至百度智能云；数字版 PDF 与 .docx 始终本地解析、不受影响。
          未配置时 .doc 仅能存档，图片与扫描件回退给开启了「图片输入」的模型本地
          转写（两者都未配置才仅存档）。
        </p>
      </div>

      <Card className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-[13px] font-medium text-muted-foreground">
            API Key（AK）{configured && <span className="text-success">（已保存）</span>}
          </label>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={configured ? '已配置，输入新值可更换' : '百度智能云应用的 API Key'}
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[13px] font-medium text-muted-foreground">Secret Key（SK）</label>
          <div className="relative">
            <Input
              type={showSecret ? 'text' : 'password'}
              value={secretKey}
              onChange={(e) => setSecretKey(e.target.value)}
              placeholder={configured ? '已配置，输入新值可更换' : '百度智能云应用的 Secret Key'}
              className="pr-9"
            />
            <button
              type="button"
              onClick={() => setShowSecret(!showSecret)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showSecret ? '隐藏 SK' : '显示 SK'}
            >
              {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" disabled={!apiKey && !secretKey} onClick={saveKeys}>
            保存
          </Button>
          <Button size="sm" variant="outline" disabled={testing} onClick={testConnection}>
            {testing && <Loader variant="circular" size="xs" tone="current" />}
            {testing ? '测试中…' : '测试'}
          </Button>
        </div>
        {error && <p className="text-sm text-error">{error}</p>}
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 通用区：数据目录 / 日志 / 版本
// ---------------------------------------------------------------------------

function GeneralSection({ settings }: { settings: Awaited<ReturnType<typeof getSettings>> | undefined }) {
  const { toast } = useToast()
  const version = __APP_VERSION__

  const reveal = async (path: string) => {
    try {
      await revealInFolder(path)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <div className="text-[15px] font-semibold">存储与日志</div>
        {settings && (
          <>
            <PathRow
              label="数据目录"
              path={settings.paths.data_dir}
              hint="任务工作区、知识库、数据库与设置都存放在这里"
              onReveal={reveal}
            />
            <PathRow
              label="服务日志"
              path={settings.paths.log_file}
              hint="排查后端问题时把这份文件发给开发者"
              onReveal={reveal}
            />
          </>
        )}
      </Card>
      <Card className="text-sm">
        <span className="text-muted-foreground">版本</span>
        <span className="ml-2 font-mono text-xs">{version}</span>
      </Card>
    </div>
  )
}

function PathRow({
  label,
  path,
  hint,
  onReveal,
}: {
  label: string
  path: string
  hint: string
  onReveal: (path: string) => void
}) {
  const tauri = isTauri()
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="w-20 shrink-0 text-[13px] font-medium text-muted-foreground">{label}</span>
        <code className="min-w-0 flex-1 truncate rounded bg-muted/60 px-2 py-0.5 font-mono text-xs">{path}</code>
        {tauri && (
          <Button size="sm" variant="outline" onClick={() => onReveal(path)}>
            打开
          </Button>
        )}
      </div>
      <p className="pl-[5.5rem] text-xs leading-relaxed text-muted-foreground">{hint}</p>
    </div>
  )
}
