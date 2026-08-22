import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog } from '@/components/ui/dialog'
import { getSettings, isTauri, putSettings } from '@/api/client'

export interface SettingsDialogProps {
  open: boolean
  onClose: () => void
}

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    enabled: open,
  })
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // API Key 仅在 Tauri 环境显示，经 command 存钥匙串，永不进入 HTTP 载荷；
  // 输入过程会瞬时存在于 JS state 与 IPC payload（PRD §6.1 现状），保存后立即清空
  const [key, setKey] = useState('')
  const [keySaved, setKeySaved] = useState(false)

  useEffect(() => {
    if (settings) {
      setBaseUrl(settings.base_url)
      setModel(settings.model)
    }
  }, [settings])

  useEffect(() => {
    if (open && isTauri()) {
      window.__TAURI_INTERNALS__
        ?.invoke('get_api_key_has_value')
        .then((v) => setKeySaved(Boolean(v)))
        .catch(() => setKeySaved(false))
    }
  }, [open])

  const handleSave = async () => {
    setError(null)
    try {
      await putSettings(baseUrl, model)
      setSaved(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleSaveKey = async () => {
    setError(null)
    try {
      await window.__TAURI_INTERNALS__?.invoke('set_llm_settings', {
        baseUrl,
        model,
        apiKey: key,
      })
      setKey('')
      setKeySaved(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="设置">
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Base URL</label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">模型</label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="deepseek-v4-flash" />
        </div>

        {isTauri() && (
          <div className="space-y-1.5 rounded-md border p-3">
            <label className="text-sm font-medium">
              API Key {keySaved && <span className="text-xs text-green-600">（已保存到钥匙串）</span>}
            </label>
            <Input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="输入后保存到钥匙串并重启 sidecar"
            />
            <Button size="sm" onClick={handleSaveKey} disabled={!key}>
              保存 Key
            </Button>
          </div>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
        {saved && !error && <p className="text-sm text-green-600">已保存（base_url/model 立即生效）</p>}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
          <Button onClick={handleSave}>保存</Button>
        </div>
      </div>
    </Dialog>
  )
}
