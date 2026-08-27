import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog } from '@/components/ui/dialog'
import { getSettings, isTauri, putSettings, testModelConnection, type ModelRole } from '@/api/client'
import { useToast } from '@/context/Toast'

export interface SettingsDialogProps {
  open: boolean
  onClose: () => void
}

/** 单角色区块状态：表单三字段 + key 已存标记 + 测试/保存反馈 */
interface RoleFormState {
  baseUrl: string
  model: string
  key: string
  keySaved: boolean
  showKey: boolean
  testing: boolean
}

const emptyRole: RoleFormState = { baseUrl: '', model: '', key: '', keySaved: false, showKey: false, testing: false }

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    enabled: open,
  })
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [llm, setLlm] = useState<RoleFormState>(emptyRole)
  const [vlm, setVlm] = useState<RoleFormState>(emptyRole)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settings) {
      setLlm((s) => ({ ...s, baseUrl: settings.llm.base_url, model: settings.llm.model }))
      setVlm((s) => ({ ...s, baseUrl: settings.vlm.base_url, model: settings.vlm.model }))
    }
  }, [settings])

  useEffect(() => {
    if (open && isTauri()) {
      // Key 仅在 Tauri 环境经 command 存钥匙串，永不进入 HTTP 载荷；
      // 输入过程会瞬时存在于 JS state 与 IPC payload（PRD §6.1 现状），保存后立即清空
      void Promise.all(
        (['llm', 'vlm'] as const).map(async (role) => {
          try {
            const has = await window.__TAURI_INTERNALS__?.invoke('get_api_key_has_value', {
              role,
            })
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
      await putSettings(role, form.baseUrl, form.model)
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
      await putSettings(role, form.baseUrl, form.model)
      const r = await testModelConnection(role)
      toast(r.ok ? '连接正常' : '连接失败', r.ok ? 'success' : 'error')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTesting(false)
    }
  }

  const renderRole = (
    role: ModelRole,
    title: string,
    hint: string,
    form: RoleFormState,
    setForm: Dispatch<SetStateAction<RoleFormState>>,
    keyPlaceholder: string,
  ) => (
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
          placeholder={
            role === 'llm'
              ? 'https://api.deepseek.com/v1'
              : 'https://dashscope.aliyuncs.com/compatible-mode/v1'
          }
        />
      </div>
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">模型</label>
        <Input
          value={form.model}
          onChange={(e) => setForm((s) => ({ ...s, model: e.target.value }))}
          placeholder={role === 'llm' ? 'deepseek-v4-flash' : 'qwen-vl-max'}
        />
      </div>

      {isTauri() && (
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            API Key {form.keySaved && <span className="text-success">（已保存到钥匙串）</span>}
          </label>
          <div className="relative">
            <Input
              type={form.showKey ? 'text' : 'password'}
              value={form.key}
              onChange={(e) => setForm((s) => ({ ...s, key: e.target.value }))}
              placeholder={keyPlaceholder}
              className="pr-9"
            />
            <button
              type="button"
              onClick={() => setForm((s) => ({ ...s, showKey: !s.showKey }))}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={form.showKey ? '隐藏 Key' : '显示 Key'}
            >
              {form.showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <Button size="sm" onClick={() => saveRole(role)}>
          保存
        </Button>
        {isTauri() && (
          <Button size="sm" variant="outline" disabled={!form.key} onClick={() => saveRoleKey(role)}>
            保存 Key
          </Button>
        )}
        <Button size="sm" variant="outline" disabled={form.testing} onClick={() => testRole(role)}>
          {form.testing ? '测试中…' : '测试'}
        </Button>
      </div>
    </div>
  )

  return (
    <Dialog open={open} onClose={onClose} title="设置">
      <div className="space-y-4">
        {renderRole(
          'llm',
          '对话模型（LLM）',
          '对话与标书生成的文本模型',
          llm,
          setLlm,
          '输入后保存到钥匙串并重启 sidecar',
        )}
        {renderRole(
          'vlm',
          '视觉模型（VLM，可选）',
          '知识库图片 / 扫描件识别。不配置时仅保存原件，需手动填写信息',
          vlm,
          setVlm,
          '视觉模型 API Key（与对话模型可不同供应商）',
        )}

        {error && <p className="text-sm text-error">{error}</p>}

        <div className="flex justify-end">
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
