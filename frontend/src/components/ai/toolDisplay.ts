/** 工具显示名映射（§6，写死在前端；未映射工具直接显示原始名）。 */
export const TOOL_DISPLAY: Record<string, string> = {
  parse_document: '解析文档',
  assemble_tender: '组装投标目录',
  publish_artifact: '发布 Artifact',
  read_artifact: '读取 Artifact',
  fetch_url: '抓取网页',
  write_file: '写入文件',
  read_file: '读取文件',
  edit_file: '编辑文件',
  ls: '列出文件',
  grep: '检索文件',
  write_todos: '更新任务清单',
}

export function toolDisplayName(tool: string): string {
  return TOOL_DISPLAY[tool] ?? tool
}

/** 工具步骤行的关键参数（一眼看出在操作哪个路径/对象）；未映射或参数缺失返回空串。 */
const TOOL_ARG_KEY: Record<string, string> = {
  ls: 'path',
  read_file: 'file_path',
  write_file: 'file_path',
  edit_file: 'file_path',
  grep: 'pattern',
  glob: 'pattern',
  parse_document: 'path',
  fetch_url: 'url',
  read_artifact: 'artifact_id',
  publish_artifact: 'title',
}

export function stepArgLabel(tool: string, args?: Record<string, unknown>): string {
  const key = TOOL_ARG_KEY[tool]
  if (!key || !args) return ''
  const value = args[key]
  return typeof value === 'string' && value ? value : ''
}
