import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, FileText, FolderOpen, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ModalShell } from '@/components/ui/ModalShell'
import {
  getSettings,
  isTauri,
  putSettings,
  revealInFolder,
  testModelConnection,
  type ModelRole,
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

/** 厂商预设：只是填表快捷方式不当真值，选中后任何字段都可改；会过时，少而精。 */
const VENDOR_PRESETS = [
  { name: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-v4-flash', imageSupport: false },
  { name: 'Moonshot（Kimi）', baseUrl: 'https://api.moonshot.cn/v1', model: 'kimi-k2', imageSupport: false },
  { name: '阿里云百炼', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-max', imageSupport: false },
  { name: 'OpenAI', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o', imageSupport: true },
  { name: '智谱', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4.6', imageSupport: false },
  { name: '火山方舟', baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1.6', imageSupport: true },
]

/** 单角色表单状态：三字段 + key 已存标记 + 测试反馈 */
interface RoleFormState {
  baseUrl: string
  model: string
  key: string
  keySaved: boolean
  imageSupport: boolean
  testing: boolean
}

const emptyRole: RoleFormState = {
  baseUrl: '',
  model: '',
  key: '',
  keySaved: false,
  imageSupport: false,
  testing: false,
}

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
    if (!settings.llm.key_configured) {
      notices.push({ level: 'error', text: '未配置对话模型 API Key，无法对话' })
    }
    if (!settings.vlm.key_configured && !settings.llm.image_support) {
      notices.push({ level: 'warn', text: '没有可用的视觉能力：知识库图片 / 扫描件将无法识别，仅存档原件' })
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

          {section === 'models' && <ModelsSection open={open} settings={settings} />}
          {section === 'parse' && <ParseSection />}
          {section === 'general' && <GeneralSection settings={settings} />}
        </div>
      </div>
    </ModalShell>
  )
}

// ---------------------------------------------------------------------------
// 模型区：LLM / VLM 双角色表单（key 走钥匙串，永不进 HTTP）
// ---------------------------------------------------------------------------

function ModelsSection({
  open,
  settings,
}: {
  open: boolean
  settings: Awaited<ReturnType<typeof getSettings>> | undefined
}) {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [llm, setLlm] = useState<RoleFormState>(emptyRole)
  const [vlm, setVlm] = useState<RoleFormState>(emptyRole)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settings) {
      setLlm((s) => ({
        ...s,
        baseUrl: settings.llm.base_url,
        model: settings.llm.model,
        imageSupport: settings.llm.image_support,
      }))
      setVlm((s) => ({ ...s, baseUrl: settings.vlm.base_url, model: settings.vlm.model }))
    }
  }, [settings])

  useEffect(() => {
    if (open && isTauri()) {
      // Key 仅在 Tauri 环境经 command 存钥匙串，永不进入 HTTP 载荷；
      // 输入过程会瞬时存在于 JS state 与 IPC payload，保存后立即清空
      void Promise.all(
        (['llm', 'vlm'] as const).map(async (role) => {
          try {
            const has = await window.__TAURI_INTERNALS__?.invoke('get_api_key_has_value', { role })
            if (role === 'llm') setLlm((s) => ({ ...s, keySaved: Boolean(has) }))
            else setVlm((s) => ({ ...s, keySaved: Boolean(has) }))
          } catch {
            /* 查询失败按未配置显示 */
          }
        }),
      )
    }
  }, [open])

  const saveRole = async (role: ModelRole) => {
    setError(null)
    const form = role === 'llm' ? llm : vlm
    try {
      await putSettings(role, form.baseUrl, form.model, role === 'llm' ? form.imageSupport : undefined)
      // 模型胶囊（InputComposer）的 settings query staleTime 5min：不失效则标签不刷新
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      toast(role === 'llm' ? '对话模型已保存' : '视觉模型已保存', 'success')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const saveRoleKey = async (role: ModelRole) => {
    setError(null)
    const form = role === 'llm' ? llm : vlm
    try {
      await window.__TAURI_INTERNALS__?.invoke('set_model_settings', {
        role,
        baseUrl: form.baseUrl,
        model: form.model,
        apiKey: form.key,
      })
      if (role === 'llm') setLlm((s) => ({ ...s, key: '', keySaved: true }))
      else setVlm((s) => ({ ...s, key: '', keySaved: true }))
      toast('API Key 已保存到钥匙串，正在重启服务…', 'success')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const testRole = async (role: ModelRole) => {
    setError(null)
    const setTesting = (v: boolean) =>
      role === 'llm' ? setLlm((s) => ({ ...s, testing: v })) : setVlm((s) => ({ ...s, testing: v }))
    setTesting(true)
    try {
      // 先保存表单值再测试，避免「测的是旧配置」
      const form = role === 'llm' ? llm : vlm
      await putSettings(role, form.baseUrl, form.model, role === 'llm' ? form.imageSupport : undefined)
      const r = await testModelConnection(role)
      toast(r.ok ? '连接正常' : '连接失败', r.ok ? 'success' : 'error')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* 厂商预设：快捷填充 LLM 表单（字段选中后可改） */}
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <span className="shrink-0">预设：</span>
        {VENDOR_PRESETS.map((p) => (
          <button
            key={p.name}
            type="button"
            onClick={() => setLlm((s) => ({ ...s, baseUrl: p.baseUrl, model: p.model, imageSupport: p.imageSupport }))}
            className="rounded-full border px-2.5 py-0.5 transition-colors hover:bg-secondary"
          >
            {p.name}
          </button>
        ))}
      </div>

      {renderRole('llm', '对话模型（LLM）', '对话与标书生成的文本模型', llm, setLlm, saveRole, saveRoleKey, testRole, {
        baseUrl: 'https://api.deepseek.com/v1',
        model: 'deepseek-v4-flash',
        keyPlaceholder: '输入后保存到钥匙串并重启 sidecar',
      })}
      {renderRole('vlm', '视觉模型（VLM，可选）', '知识库图片 / 扫描件识别。不配置时仅保存原件，需手动填写信息', vlm, setVlm, saveRole, saveRoleKey, testRole, {
        baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        model: 'qwen-vl-max',
        keyPlaceholder: '视觉模型 API Key（与对话模型可不同供应商）',
      })}

      {error && <p className="text-sm text-error">{error}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 文档解析区：百度云 PaddleOCR-VL（AK/SK 走钥匙串两 account）
// ---------------------------------------------------------------------------

function ParseSection() {
  const { toast } = useToast()
  const [apiKey, setApiKey] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [akSaved, setAkSaved] = useState(false)
  const [skSaved, setSkSaved] = useState(false)
  const [showSecret, setShowSecret] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tauri = isTauri()

  useEffect(() => {
    if (tauri) {
      void Promise.all(
        (['baidu-ocr-api', 'baidu-ocr-secret'] as const).map(async (role, i) => {
          try {
            const has = await window.__TAURI_INTERNALS__?.invoke('get_api_key_has_value', { role })
            if (i === 0) setAkSaved(Boolean(has))
            else setSkSaved(Boolean(has))
          } catch {
            /* 查询失败按未配置显示 */
          }
        }),
      )
    }
  }, [tauri])

  const saveKeys = async () => {
    setError(null)
    try {
      await window.__TAURI_INTERNALS__?.invoke('set_baidu_ocr_keys', { apiKey, secretKey })
      if (apiKey) setAkSaved(true)
      if (secretKey) setSkSaved(true)
      setApiKey('')
      setSecretKey('')
      toast('文档解析凭证已保存到钥匙串，正在重启服务…', 'success')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const testConnection = async () => {
    setError(null)
    setTesting(true)
    try {
      const r = await testModelConnection('ocr')
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
        {tauri ? (
          <>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                API Key（AK）{akSaved && <span className="text-success">（已保存到钥匙串）</span>}
              </label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={akSaved ? '已配置，输入新值可更换' : '百度智能云应用的 API Key'}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Secret Key（SK）{skSaved && <span className="text-success">（已保存到钥匙串）</span>}
              </label>
              <div className="relative">
                <Input
                  type={showSecret ? 'text' : 'password'}
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  placeholder={skSaved ? '已配置，输入新值可更换' : '百度智能云应用的 Secret Key'}
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
                保存到钥匙串
              </Button>
              <Button size="sm" variant="outline" disabled={testing} onClick={testConnection}>
                {testing ? '测试中…' : '测试'}
              </Button>
            </div>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            浏览器开发模式下凭证经环境变量 BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY 配置（sidecar/.env）。
          </p>
        )}
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

// ---------------------------------------------------------------------------
// 双角色表单渲染（llm/vlm 共用；image_support 勾选仅 llm 显示）
// ---------------------------------------------------------------------------

interface RoleUiConfig {
  baseUrl: string
  model: string
  keyPlaceholder: string
}

function renderRole(
  role: ModelRole,
  title: string,
  hint: string,
  form: RoleFormState,
  setForm: Dispatch<SetStateAction<RoleFormState>>,
  onSave: (role: ModelRole) => void,
  onSaveKey: (role: ModelRole) => void,
  onTest: (role: ModelRole) => void,
  ui: RoleUiConfig,
) {
  return (
    <div className="space-y-3 rounded-lg border border-line p-3">
      <div>
        <div className="text-sm font-medium">{title}</div>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Base URL</label>
        <Input
          value={form.baseUrl}
          onChange={(e) => setForm((s) => ({ ...s, baseUrl: e.target.value }))}
          placeholder={ui.baseUrl}
        />
      </div>
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">模型</label>
        <Input value={form.model} onChange={(e) => setForm((s) => ({ ...s, model: e.target.value }))} placeholder={ui.model} />
      </div>

      {role === 'llm' && (
        <label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={form.imageSupport}
            onChange={(e) => setForm((s) => ({ ...s, imageSupport: e.target.checked }))}
            className="accent-[var(--brand)]"
          />
          <span className="font-medium">支持图片输入</span>
          <span className="text-muted-foreground">
            （勾选后不再提醒配置视觉模型；对话中能否真的读图以模型实际能力为准）
          </span>
        </label>
      )}

      {isTauri() && (
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            API Key {form.keySaved && <span className="text-success">（已保存到钥匙串）</span>}
          </label>
          <Input
            type="password"
            value={form.key}
            onChange={(e) => setForm((s) => ({ ...s, key: e.target.value }))}
            placeholder={ui.keyPlaceholder}
          />
        </div>
      )}

      <div className="flex gap-2">
        <Button size="sm" onClick={() => onSave(role)}>
          保存
        </Button>
        {isTauri() && (
          <Button size="sm" variant="outline" disabled={!form.key} onClick={() => onSaveKey(role)}>
            保存 Key
          </Button>
        )}
        <Button size="sm" variant="outline" disabled={form.testing} onClick={() => onTest(role)}>
          {form.testing ? '测试中…' : '测试'}
        </Button>
      </div>
    </div>
  )
}
