import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Eye, EyeOff, FileText, FolderOpen, Image as ImageIcon, Pencil, Plus, Sparkles, Star, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ModalShell } from '@/components/ui/ModalShell'
import {
  getSettings,
  isTauri,
  putModelKey,
  putModels,
  putOcrKeys,
  revealInFolder,
  testModelConnection,
  type ModelBody,
} from '@/api/client'
import { useToast } from '@/context/Toast'

export interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

type SectionId = 'models' | 'parse' | 'general'

const SECTIONS: { id: SectionId; title: string; icon: typeof Sparkles }[] = [
  { id: 'models', title: '模型', icon: Sparkles },
  { id: 'parse', title: '文档解析', icon: FileText },
  { id: 'general', title: '通用', icon: FolderOpen },
]

/** 厂商预设：只是填表快捷方式不当真值，选中后任何字段都可改；模型列表会过时，少而精。 */
const VENDOR_PRESETS: { name: string; baseUrl: string; models: { name: string; imageSupport: boolean }[] }[] = [
  {
    name: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    models: [
      { name: 'deepseek-v4-flash', imageSupport: false },
      { name: 'deepseek-chat', imageSupport: false },
      { name: 'deepseek-reasoner', imageSupport: false },
    ],
  },
  {
    name: 'Moonshot（Kimi）',
    baseUrl: 'https://api.moonshot.cn/v1',
    models: [
      { name: 'kimi-k2', imageSupport: false },
      { name: 'kimi-latest', imageSupport: false },
    ],
  },
  {
    name: '阿里云百炼',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: [
      { name: 'qwen-max', imageSupport: false },
      { name: 'qwen-plus', imageSupport: false },
      { name: 'qwen-vl-max', imageSupport: true },
    ],
  },
  {
    name: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    models: [
      { name: 'gpt-4o', imageSupport: true },
      { name: 'gpt-4.1', imageSupport: true },
    ],
  },
  {
    name: '智谱',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    models: [
      { name: 'glm-4.6', imageSupport: false },
      { name: 'glm-4.5v', imageSupport: true },
    ],
  },
  {
    name: '火山方舟',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    models: [
      { name: 'doubao-seed-1.6', imageSupport: true },
      { name: 'doubao-1.5-pro', imageSupport: false },
    ],
  },
  { name: '自定义', baseUrl: '', models: [] },
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

  // 能力状态条：按配置现算，配置齐备时不显示（提示不是门禁）
  const notices: { level: 'error' | 'warn'; text: string }[] = []
  if (settings) {
    const withKey = settings.models.filter((m) => m.key_configured)
    if (withKey.length === 0) {
      notices.push({ level: 'error', text: '没有已配 Key 的模型，无法对话——请添加模型并保存 API Key' })
    }
    if (!settings.models.some((m) => m.image_support && m.key_configured)) {
      notices.push({ level: 'warn', text: '没有可用的图片识别模型：知识库图片 / 扫描件将无法识别，仅存档原件' })
    }
    if (!settings.ocr.configured) {
      notices.push({ level: 'warn', text: '未配置文档解析：扫描版 PDF 与 .doc 无法解析（仅能存档）' })
    }
  }

  return (
    <ModalShell onClose={onClose} cardClassName="h-[min(85vh,620px)] w-[min(92vw,860px)]">
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <h2 className="text-sm font-semibold">设置</h2>
        <button
          type="button"
          onClick={onClose}
          className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="关闭设置"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-40 shrink-0 flex-col gap-1 border-r bg-muted/40 p-2">
          {SECTIONS.map((s) => {
            const Icon = s.icon
            const active = section === s.id
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setSection(s.id)}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  active ? 'bg-secondary font-medium text-primary' : 'text-muted-foreground hover:bg-secondary/60'
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {s.title}
              </button>
            )
          })}
        </nav>

        <div className="min-w-0 flex-1 overflow-y-auto p-5">
          {notices.length > 0 && (
            <div className="mb-4 space-y-1.5">
              {notices.map((n) => (
                <p
                  key={n.text}
                  className={`rounded-md border px-3 py-1.5 text-xs ${
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
// 模型区：profile 列表制（多模型；key 走钥匙串 per-model account，永不进 HTTP）
// ---------------------------------------------------------------------------

/** 列表/表单共用的本地形状（编辑中的草稿；保存时全量 PUT） */
interface LocalModel {
  id: string
  name: string
  baseUrl: string
  model: string
  imageSupport: boolean
  keySaved: boolean
}

function ModelsSection({ settings }: { settings: Awaited<ReturnType<typeof getSettings>> | undefined }) {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [models, setModels] = useState<LocalModel[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  // null=列表态；'new'=新增；否则=编辑该 id
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settings) {
      setModels(
        settings.models.map((m) => ({
          id: m.id,
          name: m.name,
          baseUrl: m.base_url,
          model: m.model,
          imageSupport: m.image_support,
          keySaved: m.key_configured,
        })),
      )
      setDefaultModel(settings.default_model)
    }
  }, [settings])

  const persist = async (list: LocalModel[], dflt: string) => {
    setError(null)
    const body: ModelBody[] = list.map((m) => ({
      id: m.id,
      name: m.name || m.id,
      base_url: m.baseUrl,
      model: m.model,
      image_support: m.imageSupport,
    }))
    try {
      await putModels(body, dflt)
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    }
  }

  const saveFromForm = async (draft: LocalModel, isNew: boolean) => {
    const list = isNew ? [...models, draft] : models.map((m) => (m.id === draft.id ? draft : m))
    // 唯一一条时自动设为默认；默认模型被删时回落第一条
    let dflt = defaultModel
    if (!list.some((m) => m.id === dflt)) dflt = list[0]?.id ?? ''
    if (list.length === 1) dflt = list[0].id
    if (!(await persist(list, dflt))) return
    setDefaultModel(dflt)
    setEditing(null)
    toast(isNew ? '模型已添加' : '模型已保存', 'success')
  }

  const removeModel = async (m: LocalModel) => {
    if (!window.confirm(`删除模型「${m.name}」？（已保存的 API Key 会保留在钥匙串，重新添加同 id 可复用）`)) return
    const list = models.filter((x) => x.id !== m.id)
    let dflt = defaultModel
    if (dflt === m.id) dflt = list[0]?.id ?? ''
    if (!(await persist(list, dflt))) return
    setDefaultModel(dflt)
    toast('模型已删除', 'success')
  }

  const setAsDefault = async (m: LocalModel) => {
    if (!(await persist(models, m.id))) return
    setDefaultModel(m.id)
    toast(`「${m.name}」已设为默认`, 'success')
  }

  if (editing !== null) {
    const isNew = editing === 'new'
    const current = isNew ? null : (models.find((m) => m.id === editing) ?? null)
    return (
      <ModelForm
        key={editing}
        initial={current}
        isNew={isNew}
        error={error}
        onSave={saveFromForm}
        onCancel={() => setEditing(null)}
        onError={setError}
      />
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          可配置任意多个模型（不同供应商各配各的）；勾选「支持图片输入」的模型会用于知识库图片
          / 扫描件识别。带 ★ 的是默认模型（后台轻量任务与新会话使用）。
        </p>
        <Button size="sm" onClick={() => setEditing('new')}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加模型
        </Button>
      </div>

      {models.length === 0 && (
        <p className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-muted-foreground">
          还没有配置模型——点击「添加模型」，选一家厂商预设后只需填写 API Key
        </p>
      )}

      {models.map((m) => (
        <div key={m.id} className="flex items-center gap-3 rounded-lg border border-line p-3">
          <button
            type="button"
            onClick={() => void setAsDefault(m)}
            title={defaultModel === m.id ? '默认模型' : '设为默认'}
            className={`grid h-6 w-6 shrink-0 place-items-center rounded-md transition-colors ${
              defaultModel === m.id
                ? 'text-amber-500'
                : 'text-muted-foreground/40 hover:bg-muted hover:text-muted-foreground'
            }`}
          >
            <Star className={`h-4 w-4 ${defaultModel === m.id ? 'fill-current' : ''}`} />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium">{m.name}</span>
              {m.imageSupport && (
                <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-accent-soft px-1.5 py-px text-[10px] text-primary">
                  <ImageIcon className="h-2.5 w-2.5" />
                  图片
                </span>
              )}
              <span
                className={`ml-auto shrink-0 text-[10px] ${m.keySaved ? 'text-success' : 'text-error'}`}
              >
                {m.keySaved ? 'Key 已配置' : 'Key 未配置'}
              </span>
            </div>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {m.model} · {m.baseUrl.replace(/^https?:\/\//, '')}
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={() => setEditing(m.id)}>
            <Pencil className="mr-1 h-3 w-3" />
            编辑
          </Button>
          <Button size="sm" variant="outline" onClick={() => void removeModel(m)}>
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      ))}

      {error && <p className="text-sm text-error">{error}</p>}
    </div>
  )
}

/** 新增/编辑表单：厂商预设下拉 → 只需填 Key；模型从预设列表选或自定义 */
function ModelForm({
  initial,
  isNew,
  error,
  onSave,
  onCancel,
  onError,
}: {
  initial: LocalModel | null
  isNew: boolean
  error: string | null
  onSave: (draft: LocalModel, isNew: boolean) => void
  onCancel: () => void
  onError: (e: string | null) => void
}) {
  const { toast } = useToast()
  const [presetIdx, setPresetIdx] = useState(() => {
    if (initial) {
      const i = VENDOR_PRESETS.findIndex((p) => p.baseUrl && p.baseUrl === initial.baseUrl)
      if (i >= 0) return i
    }
    return VENDOR_PRESETS.length - 1 // 自定义
  })
  const [name, setName] = useState(initial?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? '')
  const [model, setModel] = useState(initial?.model ?? '')
  const [customModel, setCustomModel] = useState(() => {
    if (!initial) return false
    const p = VENDOR_PRESETS.find((p) => p.baseUrl && p.baseUrl === initial.baseUrl)
    return !p || !p.models.some((mm) => mm.name === initial.model)
  })
  const [imageSupport, setImageSupport] = useState(initial?.imageSupport ?? false)
  const [key, setKey] = useState('')
  const [keySaved, setKeySaved] = useState(initial?.keySaved ?? false)
  const [showKey, setShowKey] = useState(false)
  const [testing, setTesting] = useState(false)

  const preset = VENDOR_PRESETS[presetIdx]

  // 已保存过的 profile id 沿用（Key 按模型 id 存本地库）；新模型生成 uuid
  const [pid] = useState(initial?.id ?? `m_${crypto.randomUUID().slice(0, 8)}`)

  const applyPreset = (i: number) => {
    setPresetIdx(i)
    const p = VENDOR_PRESETS[i]
    if (p.baseUrl) setBaseUrl(p.baseUrl)
    if (!name && p.name !== '自定义') setName(p.name)
    if (p.models.length > 0) {
      setModel(p.models[0].name)
      setImageSupport(p.models[0].imageSupport)
      setCustomModel(false)
    } else {
      setCustomModel(true)
    }
  }

  const pickPresetModel = (m: { name: string; imageSupport: boolean } | null) => {
    if (m) {
      setModel(m.name)
      setImageSupport(m.imageSupport)
    } else {
      setCustomModel(true)
      setModel('')
    }
  }

  const saveKey = async () => {
    onError(null)
    try {
      await putModelKey(pid, key)
      setKey('')
      setKeySaved(true)
      toast('API Key 已保存，即时生效', 'success')
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const test = async () => {
    onError(null)
    setTesting(true)
    try {
      // 先保存表单值（进列表）再测试，避免「测的是旧配置」
      const draft: LocalModel = { id: pid, name: name.trim() || pid, baseUrl: baseUrl.trim(), model: model.trim(), imageSupport, keySaved }
      await onSave(draft, isNew)
      const r = await testModelConnection({ model: pid })
      toast(r.ok ? '连接正常' : '连接失败', r.ok ? 'success' : 'error')
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          ← 返回模型列表
        </button>
        <span className="text-sm font-medium">{isNew ? '添加模型' : `编辑：${initial?.name}`}</span>
      </div>

      <div className="space-y-3 rounded-lg border border-line p-3">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">厂商预设</label>
          <div className="flex flex-wrap gap-1.5">
            {VENDOR_PRESETS.map((p, i) => (
              <button
                key={p.name}
                type="button"
                onClick={() => applyPreset(i)}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                  presetIdx === i ? 'border-primary bg-accent-soft text-primary' : 'hover:bg-secondary'
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">
            选预设后只需填 API Key；模型、地址都可再改。
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">名称</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={preset.name === '自定义' ? '如：DeepSeek 主力' : preset.name} />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Base URL</label>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={preset.baseUrl || 'https://api.example.com/v1'}
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">模型</label>
          {preset.models.length > 0 && !customModel ? (
            <div className="flex flex-wrap gap-1.5">
              {preset.models.map((mm) => (
                <button
                  key={mm.name}
                  type="button"
                  onClick={() => pickPresetModel(mm)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    model === mm.name ? 'border-primary bg-accent-soft text-primary' : 'hover:bg-secondary'
                  }`}
                >
                  {mm.imageSupport && <ImageIcon className="h-3 w-3" />}
                  {mm.name}
                  {model === mm.name && <Check className="h-3 w-3" />}
                </button>
              ))}
              <button
                type="button"
                onClick={() => pickPresetModel(null)}
                className="rounded-full border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary"
              >
                自定义…
              </button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="模型名，如 deepseek-v4-flash" />
              {preset.models.length > 0 && (
                <Button size="sm" variant="outline" onClick={() => setCustomModel(false)}>
                  预设列表
                </Button>
              )}
            </div>
          )}
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={imageSupport}
            onChange={(e) => setImageSupport(e.target.checked)}
            className="accent-[var(--brand)]"
          />
          <span className="font-medium">支持图片输入</span>
          <span className="text-muted-foreground">
            （勾选后该模型将用于知识库图片 / 扫描件识别；能否真的读图以模型实际能力为准）
          </span>
        </label>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            API Key {keySaved && <span className="text-success">（已保存）</span>}
          </label>
          <div className="relative">
            <Input
              type={showKey ? 'text' : 'password'}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={keySaved ? '已配置，输入新值可更换' : 'sk-…（保存到本地库，只写不回读）'}
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
        </div>

        <div className="flex gap-2">
          <Button
            size="sm"
            disabled={!baseUrl.trim() || !model.trim()}
            onClick={() =>
              onSave(
                { id: pid, name: name.trim() || pid, baseUrl: baseUrl.trim(), model: model.trim(), imageSupport, keySaved },
                isNew,
              )
            }
          >
            保存
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!key}
            onClick={saveKey}
          >
            保存 Key
          </Button>
          <Button size="sm" variant="outline" disabled={testing} onClick={test}>
            {testing ? '测试中…' : '测试'}
          </Button>
          <Button size="sm" variant="outline" onClick={onCancel}>
            取消
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-error">{error}</p>}
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
        <div className="text-sm font-medium">百度云文档解析（PaddleOCR-VL）</div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          用于扫描版 PDF、.doc 与图片的云端识别（任务文件区与知识库通用）。按量计费，
          文件内容将发送至百度智能云；不配置时这些文件仅能存档，数字版 PDF 与
          .docx 不受影响（始终本地解析）。
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-line p-3">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
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
          <label className="text-xs font-medium text-muted-foreground">Secret Key（SK）</label>
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
            {testing ? '测试中…' : '测试'}
          </Button>
        </div>
        {error && <p className="text-sm text-error">{error}</p>}
      </div>
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
      <div className="space-y-3 rounded-lg border border-line p-3">
        <div className="text-sm font-medium">存储与日志</div>
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
      </div>
      <div className="rounded-lg border border-line p-3 text-sm">
        <span className="text-muted-foreground">版本</span>
        <span className="ml-2 font-mono text-xs">{version}</span>
      </div>
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
    <div className="space-y-0.5">
      <div className="flex items-center gap-2">
        <span className="w-16 shrink-0 text-xs font-medium text-muted-foreground">{label}</span>
        <code className="min-w-0 flex-1 truncate rounded bg-muted/60 px-2 py-0.5 font-mono text-xs">{path}</code>
        {tauri && (
          <Button size="sm" variant="outline" onClick={() => onReveal(path)}>
            打开
          </Button>
        )}
      </div>
      <p className="pl-[4.5rem] text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}
