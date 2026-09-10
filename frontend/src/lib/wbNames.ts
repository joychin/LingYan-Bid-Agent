/**
 * 工作台文件显示名唯一真值：产物面板行、「本轮文件」chips、编辑器头部共用
 * （2026-09-10 前 chips/编辑器用裸文件名，与面板业务名对不上；解析稿物理名
 * 「源名.md」双扩展剥目录后酷似上传原件，被误读成「招标文件是本轮新建的」）。
 * path 恒为真实寻址真值（打开/下载/落盘都用它），这里只管给用户看的名字。
 */

export const WB_NAMES: Record<string, string> = {
  'analysis/structure.md': '结构事实',
  'analysis/requirements-qualification.md': '资格要求',
  'analysis/requirements-submission.md': '递交要求',
  'analysis/requirements-business.md': '商务技术要求',
  'analysis/requirements-format.md': '格式要求',
  'analysis/disqualification.md': '废标条款',
  'analysis/evaluation.md': '评分标准',
  'analysis/clarifications.md': '待澄清',
  'outline/tender-response-docs.md': '目录底稿',
  'body/写作指引.md': '写作指引',
  'body/关键事实与承诺.md': '关键事实与承诺',
}

/**
 * 工作台文件显示名（path = 相对 <task>/work/ 的 posix 路径）：
 * 固定过程文件走业务名；parse/<源文件名>/… 加「 解析稿」后缀标明产物身份；
 * 多册目录分册草稿 = 「分册 · <册名>」；其余（body 节 docx、整本-*）用 basename。
 */
export function wbDisplayName(path: string): string {
  const mapped = WB_NAMES[path]
  if (mapped) return mapped
  const parts = path.split('/')
  if (parts[0] === 'parse' && parts.length > 2) return `${parts[1]} 解析稿`
  if (parts[0] === 'outline' && parts[1] === 'fragments') {
    return `分册 · ${(parts[parts.length - 1] ?? '').replace(/\.[^.]+$/, '')}`
  }
  return parts[parts.length - 1] ?? path
}
