/** 工具显示名映射（§6，写死在前端；未映射工具直接显示原始名）。 */
import {
  BookOpen,
  Bot,
  ClipboardCheck,
  FileBox,
  FileScan,
  FileSearch,
  FileText,
  FolderOpen,
  Globe,
  ListTodo,
  ListTree,
  MessageCircleQuestion,
  Pencil,
  PenLine,
  Search,
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
  search_knowledge: '检索知识库',
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
}

export function toolDisplayName(tool: string): string {
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
  search_knowledge: 'query',
  ask_human: 'question',
  update_task_progress: 'progress_note',
}

export function stepArgLabel(tool: string, args?: Record<string, unknown>): string {
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
  search_knowledge: BookOpen,
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
}

export function toolIcon(tool: string): LucideIcon {
  return TOOL_ICONS[tool] ?? Wrench
}
