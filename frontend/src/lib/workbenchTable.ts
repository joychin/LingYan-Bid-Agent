/**
 * 写作指引/承诺清单的 Markdown 表格解析与序列化（结构化表格界面数据层，纯函数）。
 *
 * 契约对齐 sidecar（金样例由 sidecar/tests/test_workbench_table_contract.py 双侧锁住）：
 * - 解析规则与 app/tools/validate_analysis.py 的 _iter_tables 同款：连续 `|` 行块、
 *   表头按列名识别（不固定列序，缺名列按下标兜底）、块内第二行当分隔行不计数据、
 *   首列（节/事项）为空的行跳过、表外内容（标题/修订注释行）原样保留；
 * - 序列化只输出标准列序的单张表——validate_body / check_pipeline / dispatch_enrich
 *   三个消费方每次现读文件即可吃下，空单元格统一写「—」；
 * - 解析宽容（吃模型写的变体），序列化唯一（只写一种格式）。
 *
 * 叶子匹配（sanitizeName/iterLeaves/sectionKey）是对 body_contract / check_pipeline
 * 的 TS 移植，**显示用途**（加行选择器、已写徽章）——对账真值仍归 sidecar 工具。
 */

import type { EditDoc, EditNode } from '@/components/processors/directoryTree'

export interface TableSpec {
  /** 表头识别：这些列名必须都出现才认这张表（宽松——列序不限） */
  required: string[]
  /** 序列化列序（canonical；dispatch_enrich 对承诺清单按位置取 cells[0]/[1]，列序不可变） */
  columns: string[]
  /** 表头缺该列名时的下标兜底（与 sidecar idx.get(name, fallback) 同款） */
  fallbackIdx?: Record<string, number>
}

export const GUIDE_TABLE: TableSpec = {
  required: ['节', '模式'],
  columns: ['节', '模式', '依据', '素材', '缺口/备注'],
  fallbackIdx: { 依据: 2, 素材: 3, '缺口/备注': 4 },
}

export const PROMISE_TABLE: TableSpec = {
  required: ['事项', '值'],
  columns: ['事项', '值', '说明'],
  fallbackIdx: { 说明: 2 },
}

export interface ParsedTableFile {
  /** 表格块之外的原文行（序列化原样保留——标题、服务端盖的「修订=用户」注释等） */
  preamble: string[]
  postamble: string[]
  /** 数据行：已按 spec.columns 列序投影（缺列取空串、多余列丢弃、首列空行剔除） */
  rows: string[][]
}

const SEPARATOR_CELL_RE = /^:?-{2,}:?$/

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|+/, '')
    .replace(/\|+$/, '')
    .split('|')
    .map((c) => c.trim())
}

/** 解析为结构化表文件；找不到**唯一**一张合法表（无表/多表/表头缺必需列）返回 null。 */
export function parseTableFile(content: string, spec: TableSpec): ParsedTableFile | null {
  const lines = content.split('\n')
  let hit: { start: number; end: number; rows: string[][] } | null = null
  let qualifying = 0
  let i = 0
  while (i < lines.length) {
    if (!lines[i].trimStart().startsWith('|')) {
      i += 1
      continue
    }
    const start = i
    while (i < lines.length && lines[i].trimStart().startsWith('|')) i += 1
    const cells = lines.slice(start, i).map(splitRow)
    const header = cells[0] ?? []
    const idx: Record<string, number> = {}
    header.forEach((c, k) => {
      if (!(c in idx)) idx[c] = k
    })
    if (!spec.required.every((r) => r in idx)) continue
    qualifying += 1
    hit = { start, end: i, rows: projectRows(cells, idx, spec) }
  }
  if (qualifying !== 1 || !hit) return null
  return {
    preamble: lines.slice(0, hit.start),
    postamble: lines.slice(hit.end),
    rows: hit.rows,
  }
}

/** 数据行投影到 canonical 列序（块内第二行=分隔行不计；中缝分隔行剔除；首列空行跳过）。 */
function projectRows(cells: string[][], idx: Record<string, number>, spec: TableSpec): string[][] {
  const first = idx[spec.columns[0]]
  const rows: string[][] = []
  for (let k = 2; k < cells.length; k++) {
    const row = cells[k]
    if (row.length && row.every((c) => SEPARATOR_CELL_RE.test(c))) continue
    const head = row[first] ?? ''
    if (!head) continue
    rows.push(spec.columns.map((c) => cellAt(row, idx, c, spec)))
  }
  return rows
}

function cellAt(row: string[], idx: Record<string, number>, name: string, spec: TableSpec): string {
  const i = idx[name] ?? spec.fallbackIdx?.[name]
  return (i !== undefined && i >= 0 && i < row.length) ? row[i] : ''
}

/** 单元格清洗：剥换行（防拆行）、`|` 替全角（防拆列）、空值统一「—」。 */
export function sanitizeCell(v: string | undefined): string {
  const s = (v ?? '')
    .replace(/\r?\n/g, ' ')
    .replace(/\|/g, '｜')
    .trim()
  return s || '—'
}

/** 序列化：preamble + 标准表 + postamble。未编辑的 canonical 输入往返字节稳定。 */
export function serializeTableFile(parsed: ParsedTableFile, spec: TableSpec): string {
  const head = `| ${spec.columns.join(' | ')} |`
  const sep = `|${spec.columns.map(() => '---').join('|')}|`
  const rows = parsed.rows.map(
    (r) => `| ${spec.columns.map((_c, k) => sanitizeCell(r[k])).join(' | ')} |`,
  )
  return [...parsed.preamble, head, sep, ...rows, ...parsed.postamble].join('\n')
}

// ---------- 单元格工具（与 sidecar 同款正则） ----------

export const GUIDE_MODES = ['素材修订', '格式跟随', '推理撰写'] as const
export type GuideMode = (typeof GUIDE_MODES)[number]

/** 模式列 → token 列表（「+」组合；「—」=非正文节点；空/未知 token 原样留给界面标警示）。 */
export function parseModeTokens(cell: string): string[] {
  return cell
    .split('+')
    .map((t) => t.trim())
    .filter(Boolean)
}

/** 依据列 → 登记表 id 列表 + 其余自由文本（切分正则与 dispatch_enrich._requirement_lines 同款）。 */
const REF_ID_RE = /^(?:MAND|TPL|REQ|SCORE)-\d+$/i
const REF_SPLIT_RE = /[、,，;；\s]+/

export function parseRefIds(cell: string): { ids: string[]; rest: string } {
  const ids: string[] = []
  const rest: string[] = []
  for (const t of cell.split(REF_SPLIT_RE)) {
    if (!t) continue
    if (REF_ID_RE.test(t)) ids.push(normRefId(t))
    else rest.push(t)
  }
  return { ids, rest: rest.join(' ') }
}

/** id 归一化（assemble_tender._norm_id 同款）：大写 + 数字补零两位（MAND-1 → MAND-01）。 */
export function normRefId(id: string): string {
  return id.toUpperCase().replace(/(\d+)$/, (m) => m.padStart(2, '0'))
}

const BLOCK_ID_RE = /blk_[0-9a-f]{12}/g

/** 素材列 → 块 id 列表（行内去重）+【缺】标记 + 其余文本（正则与 validate_body 同款）。 */
export function parseBlockRefs(cell: string): { blockIds: string[]; missing: boolean; rest: string } {
  const blockIds = [...new Set(cell.match(BLOCK_ID_RE) ?? [])]
  const missing = cell.includes('【缺】')
  const rest = cell
    .replace(BLOCK_ID_RE, ' ')
    .replace(/【缺】/g, ' ')
    .split(REF_SPLIT_RE)
    .filter(Boolean)
    .join(' ')
  return { blockIds, missing, rest }
}

// ---------- 叶子匹配（body_contract / check_pipeline 的 TS 移植，显示用途） ----------

/** 标题 → 文件名/目录名（body_contract.sanitize_name 同款：非法字符替空格、折叠空白、截 60）。 */
export function sanitizeName(title: string, limit = 60): string {
  const s = (title || '')
    .replace(/[\\/:*?"<>|\r\n\t]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return s.slice(0, limit).trim() || '未命名'
}

export interface DirLeaf {
  vol: string
  title: string
  delivery: string
}

/** 目录树叶子（无子节点、标题非空）；册名缺省「主册」（body_contract.iter_leaves 同款）。 */
export function iterLeaves(docs: EditDoc[] | undefined): DirLeaf[] {
  const out: DirLeaf[] = []
  const walk = (vol: string, list: EditNode[] | undefined) => {
    for (const n of list ?? []) {
      if (n.children?.length) {
        walk(vol, n.children)
        continue
      }
      const title = (n.目录名称 ?? '').trim()
      if (title) out.push({ vol, title, delivery: (n.交付形态 ?? '').trim() })
    }
  }
  for (const d of docs ?? []) walk((d.name ?? '').trim() || '主册', d.directory)
  return out
}

/** 多册判定：有目录树的响应文件多于一份（body_contract.multi_volume 同款）。 */
export function multiVolume(docs: EditDoc[] | undefined): boolean {
  return (docs ?? []).filter((d) => d.directory?.length).length > 1
}

/** 指引「节」列的叶子键：多册「册名/标题」复合、单册裸标题。 */
export function leafKey(vol: string, title: string, multi: boolean): string {
  return multi ? `${vol}/${title}` : title
}

/** 文件侧对账键（check_pipeline actual 同款：根级文件册键为空串）。 */
function fileSectionKey(dir: string, stem: string, multi: boolean): string {
  return `${multi ? (dir ? sanitizeName(dir) : '') : ''}\u0000${sanitizeName(stem)}`
}

/** 指引行侧对账键（check_pipeline 行拆分同款：多册无斜杠行册键=「未命名」——
 *  sanitize 空串兜底，恰好与文件侧空串册键互不匹配，裸标题行永不误标已写）。 */
function rowSectionKey(vol: string, title: string, multi: boolean): string {
  return `${multi ? sanitizeName(vol) : ''}\u0000${sanitizeName(title)}`
}

/**
 * body/ 节文件 → 已写键 → 文件路径 的映射（check_pipeline 对账规则同款）：
 * 排除 指引/承诺清单/「整本-」合册；同名 .docx/.md 并存以 docx 为准。
 */
export function writtenSections(paths: string[], multi: boolean): Map<string, string> {
  const best = new Map<string, { key: string; path: string; isDocx: boolean }>()
  for (const p of paths) {
    const parts = p.split('/')
    if (parts[0] !== 'body') continue
    const name = parts[parts.length - 1]
    if (name === '写作指引.md' || name === '关键事实与承诺.md' || name.startsWith('整本-')) continue
    const dot = name.lastIndexOf('.')
    const stem = dot > 0 ? name.slice(0, dot) : name
    const dir = parts.length > 2 ? parts[parts.length - 2] : ''
    const k = `${dir}\u0000${stem}`
    const isDocx = name.endsWith('.docx')
    const prev = best.get(k)
    if (!prev || (isDocx && !prev.isDocx)) best.set(k, { key: fileSectionKey(dir, stem, multi), path: p, isDocx })
  }
  const out = new Map<string, string>()
  for (const { key, path } of best.values()) out.set(key, path)
  return out
}

/** 指引行的已写对账：行「节」键 → 已写节映射的路径（未写返回 undefined）。 */
export function writtenPathOf(sectionCell: string, written: Map<string, string>, multi: boolean): string | undefined {
  let vol = ''
  let title = sectionCell.trim()
  if (multi && title.includes('/')) {
    const [head, ...tail] = title.split('/')
    vol = head.trim()
    title = tail.join('/').trim()
  }
  return written.get(rowSectionKey(vol, title, multi))
}
