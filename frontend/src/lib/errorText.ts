/** 步骤级错误的用户化首行：内部错误原文（虚拟路径/SDK/HTTP 细节）不进首屏；
 *  展开详情仍保留原始 error 供诊断。按已知错误族映射，未命中回退原文截断。 */

const RULES: [RegExp, string][] = [
  [/path_not_found/i, '找不到该文件或目录'],
  [/not_a_directory/i, '目标不是文件夹'],
  [/incomplete chunked read|peer closed|connection reset|remoteend/i, '模型连接中断（已自动重试）'],
  // 锚定错误码格式：裸 401 会误命中 fetch_url 的 HTTP 401（网站鉴权问题）
  [/code[:=] ?401|invalid[ _-]?(api[ _-]?)?key|unauthorized/i, '模型凭证无效或未配置'],
  [/code[:=] ?429|rate[ _-]?limit/i, '服务繁忙，请稍后重试'],
  [/timed?[_ -]?out|timeout/i, '请求超时，请重试'],
  [/写入被拒绝/, '该位置受产物保护，请写入工作台或草稿目录'],
]

export function humanizeError(raw: string | null | undefined, fallback = '执行未完成'): string {
  const text = (raw ?? '').trim()
  if (!text) return fallback
  for (const [pattern, label] of RULES) {
    if (pattern.test(text)) return label
  }
  return text.length > 80 ? `${text.slice(0, 80)}…` : text
}
