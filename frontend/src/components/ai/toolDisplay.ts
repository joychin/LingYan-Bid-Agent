/** 工具显示名映射（§6，写死在前端；未映射工具直接显示原始名）。 */
import {
  BookMarked,
  BookOpen,
  Bot,
  Building2,
  ClipboardCheck,
  ClipboardPaste,
  Copy,
  FileBox,
  FileCheck,
  FilePlus2,
  FileScan,
  FileSearch,
  FileText,
  FolderOpen,
  Globe,
  ImagePlus,
  Layers,
  LayoutTemplate,
  ListChecks,
  ListTodo,
  ListTree,
  MessageCircle,
  MessageCircleQuestion,
  Pencil,
  PenLine,
  ScanSearch,
  Search,
  ShieldCheck,
  Upload,
  Wrench,
  type LucideIcon,
} from 'lucide-react'

export const TOOL_DISPLAY: Record<string, string> = {
  parse_document: '解析文档',
  assemble_tender: '组装投标目录',
  publish_artifact: '发布 Artifact',
  read_artifact: '读取 Artifact',
  fetch_url: '抓取网页',
  update_task_progress: '更新任务进度',
  ask_human: '向你提问',
  task: '派发子代理',
  write_file: '写入文件',
  read_file: '读取文件',
  edit_file: '编辑文件',
  ls: '列出文件',
  glob: '查找文件',
  grep: '检索文件',
  write_todos: '更新任务清单',
  check_pipeline_state: '检查任务状态',
  check_name_residue: '检查名称残留',
  list_templates: '查看版式库',
  validate_analysis: '校验分析结果',
  validate_body: '校验正文',
  search_company_assets: '检索公司资料',
  search_references: '检索写作素材',
  docx_section_create: '建立正文节',
  docx_section_read: '读取正文节',
  docx_section_revise: '修订正文节',
  docx_assemble_volume: '合并成册',
  docx_material_inject: '注入素材',
  docx_source_inject: '拷贝格式件',
  docx_image_insert: '插入图片',
  docx_comment_add: '添加批注',
}

/** 技能目录名 → 中文显示名。技能全文由模型 read_file 读入（deepagents SkillsMiddleware
 *  渐进披露：system prompt 只带技能名/描述/路径，正文按需读），事件层没有技能专用工具名，
 *  故这里按路径识别。未收录的（将来新增技能）回退目录名，不丢信息。 */
const SKILL_LABELS: Record<string, string> = {
  'document-parse': '文档解析',
  'tender-analysis': '投标分析',
  'tender-outline': '投标目录',
  'tender-body': '正文写作',
  'tender-qa': '投标问答',
  'humanizer-zh': '写作润色',
  _shared: '共享规范',
}

/** 技能读取判据：路径含 `/skills/<技能名>/` 段即算。实测有 5 种前缀拼写
 *  （`skills/`、`/skills/`、`<task>/skills/`、`/workspace/<task>/skills/`），
 *  按段匹配全部覆盖；非技能路径返回 null，调用方各自回退原有显示。 */
export function skillFileInfo(
  path: unknown,
): { skill: string; label: string; file: string } | null {
  if (typeof path !== 'string') return null
  const m = /(?:^|\/)skills\/([^/]+)\/(.+)$/.exec(path)
  if (!m) return null
  const skill = m[1]
  return { skill, label: SKILL_LABELS[skill] ?? skill, file: m[2] }
}

/** 技能读取的步骤行标题：SKILL.md（技能正文）只报技能名，附属参考文件附段名
 *  （段名有中文映射——2026-09-23 C2：中文界面不再夹杂 structure/response-guidelines
 *  这类内部文件名；未收录段名回退原名，不丢信息）。 */
const SKILL_SECTION_LABELS: Record<string, string> = {
  SKILL: '技能说明',
  structure: '结构事实',
  'requirements-qualification': '资格要求',
  'requirements-submission': '递交要求',
  'requirements-business': '商务技术要求',
  'requirements-format': '格式要求',
  disqualification: '废标条款',
  evaluation: '评分标准',
  clarifications: '待澄清',
  'response-guidelines': '回复规范',
  'evidence-rules': '证据规则',
}

export function skillStepTitle(info: { label: string; file: string }): string {
  const stem = (info.file.replace(/\.md$/, '').split('/').pop() ?? '').trim()
  if (!stem || stem.toLowerCase() === 'skill') return info.label
  const section = SKILL_SECTION_LABELS[stem] ?? stem
  return `${info.label} · ${section}`
}

/** 技能加载动作的措辞单源（步骤行标题「加载技能：投标分析」与折叠组头
 *  「加载技能 ×3」共用，防两处文案漂移）。 */
export const SKILL_LOAD_LABEL = '加载技能'

/** 内部任务 id 路径前缀（`/t_xxx/…`，12 位十六进制）：虚拟根寻址对用户无意义，
 *  显示层剥掉。位数下限 8 防误伤恰好叫 t_ab 之类的普通段名。 */
function stripTaskId(path: string): string {
  return path.replace(/^\/t_[0-9a-f]{8,}\//, '')
}

/** ls 结果（deepagents `_format_file_paths` 的 Python repr）→ 文件清单。
 *  只转完整的 `[…]` 形态——events 层 4000 字符截断会剁掉尾引号/右括号并追加
 *  「已截断」说明，残缺形态转写会静默丢截断提示与残路径，原样展示更诚实。 */
function formatLsResult(summary: string): string {
  const trimmed = summary.trim()
  if (trimmed === '[]') return '无文件'
  if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) return summary
  const paths = [...trimmed.matchAll(/'([^']+)'/g)].map((m) => m[1])
  if (paths.length === 0) return summary
  return paths.map((p) => `· ${stripTaskId(p)}`).join('\n')
}

/** write_file/edit_file 英文回执（`Updated file /t_x/…`）→ 中文 + 剥任务 id。 */
function formatUpdatedFile(summary: string): string {
  const m = /^(Updated|Created) file (\S+)$/.exec(summary.trim())
  if (!m) return summary
  return `${m[1] === 'Created' ? '已创建' : '已写入'} · ${stripTaskId(m[2])}`
}

/** check_pipeline_state 的段标 → 中文（输出格式是模型消费的稳定契约，4 个 SKILL.md
 *  逐字依赖，sidecar 不动——这里只做显示层转写；首行「[pipeline 状态]（…裁决）」
 *  是写给模型的裁读指引，不给人看，剥掉）。 */
const PIPELINE_SECTION_LABELS: Record<string, string> = {
  sources: '来源',
  candidates: '候选文件',
  untracked: '未纳入',
  parse: '解析',
  analysis: '分析',
  body: '正文',
  freshness: '新鲜度',
}

function formatPipelineResult(summary: string): string {
  const out: string[] = []
  for (const line of summary.split('\n')) {
    if (line.startsWith('[pipeline 状态]')) continue
    const m = /^\[(\w+)\]\s?(.*)$/.exec(line)
    if (m) {
      const label = PIPELINE_SECTION_LABELS[m[1]] ?? m[1]
      out.push(`【${label}】${stripTaskId(m[2])}`)
    } else if (line.trim()) {
      out.push(stripTaskId(line))
    }
  }
  return out.length > 0 ? out.join('\n') : summary
}

/** 工具步骤结果人话化（2026-09-23 B2/B3）：trace 展开区直出的工具原文按工具转写。
 *  纯展示层（不碰工具真实返回），匹配不上原样返回。 */
export function formatStepResult(tool: string, summary: string): string {
  if (!summary) return summary
  if (tool === 'ls') return formatLsResult(summary)
  if (tool === 'write_file' || tool === 'edit_file') return formatUpdatedFile(summary)
  if (tool === 'check_pipeline_state') return formatPipelineResult(summary)
  return summary
}

export function toolDisplayName(tool: string, args?: Record<string, unknown>): string {
  // 只有 read_file 走技能识别（write/edit 的 file_path 指向技能目录会被 fs_guard 拒绝）
  const skill = tool === 'read_file' ? skillFileInfo(args?.file_path) : null
  if (skill) return `${SKILL_LOAD_LABEL}：${skill.label}`
  return TOOL_DISPLAY[tool] ?? tool
}

/** 子代理卡短名：task 调用的可区分标题（并发多卡靠它分辨）。
 *  优先取 description 第一行（system prompt 纪律：模型派发时首行写 ≤16 字短名，
 *  不带「你是…」角色自述）；首行超长按句读截第一句、仍超 16 字硬截（兜底无短名
 *  约定的历史消息，句读规则同 sidecar events._friendly_description）；无 description
 *  回退 subagent_type；都缺返回空串（调用方回退 toolDisplayName('task')）。 */
export function subagentStepTitle(args?: Record<string, unknown>): string {
  const raw = typeof args?.description === 'string' ? args.description.trim() : ''
  let name = ''
  if (raw) {
    name = raw.split('\n')[0].trim()
    for (const sep of ['。', '；', ';', '.']) {
      const idx = name.indexOf(sep)
      // 句读出现在行首 2 字内（如「1.」编号）不截，避免截出「1.」这类空名
      if (idx >= 2) {
        name = name.slice(0, idx + 1)
        break
      }
    }
    name = name.trim()
    if (name.length > 16) name = `${name.slice(0, 16)}…`
  }
  if (!name && typeof args?.subagent_type === 'string') {
    name = args.subagent_type.trim()
  }
  return name
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
  search_company_assets: 'query',
  search_references: 'query',
  validate_body: 'section',
  docx_section_create: 'title',
  docx_section_read: 'path',
  docx_section_revise: 'path',
  docx_material_inject: 'block_id',
  docx_source_inject: 'source',
  docx_image_insert: 'image',
  docx_comment_add: 'text',
  ask_human: 'question',
  update_task_progress: 'progress_note',
}

export function stepArgLabel(tool: string, args?: Record<string, unknown>): string {
  // 技能读取：参数行不裸露内部路径（skills/<名>/… 对用户无意义），改报技能名+文件名
  if (tool === 'read_file') {
    const skill = skillFileInfo(args?.file_path)
    if (skill) return skillStepTitle(skill)
  }
  const key = TOOL_ARG_KEY[tool]
  if (!key || !args) return ''
  const value = args[key]
  return typeof value === 'string' && value ? value : ''
}

/** 工具标题行左侧图标（线性灰，随文字色 hover 加深）；未映射工具用扳手兜底。 */
const TOOL_ICONS: Record<string, LucideIcon> = {
  parse_document: FileScan,
  assemble_tender: ListTree,
  publish_artifact: Upload,
  read_artifact: FileBox,
  fetch_url: Globe,
  update_task_progress: ClipboardCheck,
  ask_human: MessageCircleQuestion,
  task: Bot,
  write_file: PenLine,
  read_file: FileText,
  edit_file: Pencil,
  ls: FolderOpen,
  glob: FileSearch,
  grep: Search,
  write_todos: ListTodo,
  check_pipeline_state: ListChecks,
  check_name_residue: ScanSearch,
  list_templates: LayoutTemplate,
  validate_analysis: ShieldCheck,
  validate_body: FileCheck,
  search_company_assets: Building2,
  search_references: BookMarked,
  docx_section_create: FilePlus2,
  docx_section_read: FileText,
  docx_section_revise: Pencil,
  docx_assemble_volume: Layers,
  docx_material_inject: ClipboardPaste,
  docx_source_inject: Copy,
  docx_image_insert: ImagePlus,
  docx_comment_add: MessageCircle,
}

export function toolIcon(tool: string, args?: Record<string, unknown>): LucideIcon {
  // 技能读取换书本图标：与普通文件读取在流水里一眼可分
  if (tool === 'read_file' && skillFileInfo(args?.file_path)) return BookOpen
  return TOOL_ICONS[tool] ?? Wrench
}
