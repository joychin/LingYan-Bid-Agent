/** 模型设置的纯逻辑（可测；弹窗里的 UI 只做接线）。
 *  抽出来的动因：前端无组件测试环境（无 jsdom/testing-library），可验证的部分
 *  一律做成纯函数，符合仓库「测试全是纯函数」的现状。 */

/** 归一化 base_url 便于同厂商比较（去首尾空白与尾斜杠；与后端 _norm_base_url 同语义）。 */
function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

/** 两个接口地址是否同一（归一化后比较）。后端 key_ref 借用绑定用同一语义，
 *  前端「已保存 Key 是否适用于当前地址」的判断必须与之一致。 */
export function sameBaseUrl(a: string, b: string): boolean {
  return normalizeBaseUrl(a) === normalizeBaseUrl(b)
}

/** 找同厂商（同 base_url）且已配 Key 的兄弟 profile。
 *  用途：添加弹窗检测到时可提示「留空复用其 Key」；测试正文取 key_ref。
 *  excludeId 排除自身；多条命中取第一个（调用方决定提示哪一个）。 */
export function findKeySource<T extends { id: string; baseUrl: string; keySaved: boolean }>(
  models: T[],
  baseUrl: string,
  excludeId?: string,
): T | null {
  if (!baseUrl.trim()) return null
  return (
    models.find((m) => m.id !== excludeId && m.keySaved && sameBaseUrl(m.baseUrl, baseUrl)) ?? null
  )
}

export interface ModelOptionGroup {
  /** 分组标题（如「服务商提供」「常用」） */
  label: string
  models: { name: string; imageSupport?: boolean }[]
}

/** 合并「服务商实际提供」与「内置常用预设」两组模型名，去重后分组。
 *  fetched 里的名字只带 name（/models 不返回能力元数据）；preset 命中时补齐
 *  imageSupport（图片输入权标靠静态预设兜底）。fetched 为空 → 只出常用组。 */
export function mergeModelOptions(
  fetched: string[],
  preset: { name: string; imageSupport?: boolean }[],
): ModelOptionGroup[] {
  const seen = new Set<string>()
  const fetchedNames: string[] = []
  for (const raw of fetched) {
    const n = raw.trim()
    if (!n || seen.has(n)) continue
    seen.add(n)
    fetchedNames.push(n)
  }
  const presetMeta = new Map(preset.map((m) => [m.name, m.imageSupport]))
  const fetchedModels = fetchedNames.map((name) => ({
    name,
    imageSupport: presetMeta.get(name),
  }))
  const presetOnly = preset.filter((m) => !seen.has(m.name))

  const groups: ModelOptionGroup[] = []
  if (fetchedModels.length > 0) groups.push({ label: '服务商提供', models: fetchedModels })
  if (presetOnly.length > 0) groups.push({ label: '常用', models: presetOnly })
  return groups
}
