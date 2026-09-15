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

import type { DirectoryData, EditDoc, EditNode } from '@/components/processors/directoryTree'

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
  // 「图示」列（2026-09-14 表格通道批）：计划产出的表格/图示清单——旧指引无此
  // 列名时按 fallbackIdx 投影不出（取空串），不破坏存量
  columns: ['节', '模式', '依据', '素材', '图示', '缺口/备注'],
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

// ---------- 缺口/备注列（读者分离：用户看缺口，AI 看执行说明） ----------

export interface GuideNoteParts {
  /** 【缺：xxx】的内容，一条一项——渲染成「需要你提供」清单 */
  gaps: string[]
  /** 【知识库】命中事实（材料名+关键数字原文），一条一项 */
  knowledge: string[]
  /** ⚠待澄清 事项（含 CLAR 编号），一条一项 */
  clarifies: string[]
  /** 其余原文（工具名、行号、人话备注）——本列里给写手的执行细节；无内容时 '' */
  rest: string
  /** 缺口项用了代词回指（「【缺：上述公司信息】」）——摘出后指代丢失，渲染层据此
   *  提示「指代见下方执行说明」并默认展开执行说明（存量指引的兜底可读性）。 */
  anaphora: boolean
}

const NOTE_ANAPHORA_RE = /【缺[：:]\s*(?:上述|以上|前述|前面)/

/** 片段终止位置：下一个句末或下一个标记（不含终止符本身）。 */
function noteStop(s: string): number {
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '；' || ch === ';' || ch === '。' || ch === '【') return i
  }
  return s.length
}

/** 剔除片段后剩下的执行说明：折叠空白、清边界与重复分隔符（避免留一串「；」）。 */
function cleanupNoteRest(s: string): string {
  return s
    .replace(/\s+/g, ' ')
    .replace(/^[\s；;，,。．、]+/, '')
    .replace(/[\s；;，。．、：:]+$/, '')
    .replace(/([；;])[\s；;]+/g, '$1')
    .replace(/([，,])[\s，,]+/g, '$1')
    .trim()
}

/**
 * 缺口/备注列 → 四类片段（2026-09-13 A 批）。
 *
 * 动因：该列被设计成「随派发整段透传给写手」的指令载体，又同时是用户唯一可见的
 * 缺料点名——工具名/行号与【缺：…】混写，整段直接渲染＝用户看不懂（实测原话）。
 * 这里按标记切分，渲染层把「需要你提供」摆在最前、执行细节折叠起来。
 *
 * 宽容解析：标记之外的原文一律落 rest，**不丢任何内容**；旧格式（裸「缺：xxx」
 * 不带括号）不强行摘，仍能在 rest 里看到。
 */
export function parseGuideNote(note: string): GuideNoteParts {
  const src = (note ?? '').trim()
  const out: GuideNoteParts = { gaps: [], knowledge: [], clarifies: [], rest: '', anaphora: false }
  if (!src || src === '—') return out

  const spans: [number, number][] = []

  // 【缺：xxx】组；紧跟其后的破折号解释一并归入该条（「【缺：X】——为什么缺」的常见写法）
  for (const m of src.matchAll(/【缺[：:]\s*([^】]*)】/g)) {
    const start = m.index ?? 0
    let end = start + m[0].length
    let text = (m[1] ?? '').trim()
    const tail = src.slice(end)
    if (/^\s*(?:——|—|－|[:：])/.test(tail)) {
      const ext = tail.slice(0, noteStop(tail))
      const body = ext.replace(/^\s*(?:——|—|－|[:：])\s*/, '').trim()
      if (body) {
        text = `${text}——${body}`
        end += ext.length
      }
    }
    if (text) out.gaps.push(text)
    spans.push([start, end])
  }

  // 【知识库】命中事实：到下一个句末/下一个标记为止（标记剥掉——命中段标题已说明来源）
  for (const m of src.matchAll(/【知识库】/g)) {
    const start = m.index ?? 0
    const after = start + m[0].length
    const len = noteStop(src.slice(after))
    const text = src.slice(after, after + len).trim()
    if (text) out.knowledge.push(text)
    spans.push([start, after + len])
  }

  // ⚠待澄清（含 CLAR 编号）：到下一个句末/下一个标记为止
  for (const m of src.matchAll(/⚠?\s*待澄清/g)) {
    const start = m.index ?? 0
    const len = noteStop(src.slice(start))
    const text = src.slice(start, start + len).replace(/^\s*⚠?\s*/, '').trim()
    if (text) out.clarifies.push(text)
    spans.push([start, start + len])
  }

  // 防御：裸【缺】（素材列的写法，本列罕见）——不静默消失，给一条泛化缺项
  for (const m of src.matchAll(/【缺】/g)) {
    const start = m.index ?? 0
    out.gaps.push('（指引未列出具体缺项）')
    spans.push([start, start + m[0].length])
  }

  spans.sort((a, b) => a[0] - b[0])
  let cursor = 0
  let rest = ''
  for (const [s, e] of spans) {
    if (s > cursor) rest += src.slice(cursor, s)
    cursor = Math.max(cursor, e)
  }
  rest += src.slice(cursor)
  out.rest = cleanupNoteRest(rest)
  out.anaphora = NOTE_ANAPHORA_RE.test(src)
  return out
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
  /** 节点概述：tender-outline 生成的一句话「这节写什么」（旧目录产物可能缺）。 */
  overview: string
  /** 归位理由：这章为什么存在（招标方要求/惯例）。 */
  reason: string
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
      if (title)
        out.push({
          vol,
          title,
          delivery: (n.交付形态 ?? '').trim(),
          overview: (n.节点概述 ?? '').trim(),
          reason: (n.归位理由 ?? '').trim(),
        })
    }
  }
  for (const d of docs ?? []) walk((d.name ?? '').trim() || '主册', d.directory)
  return out
}

/** 素材块首段预览（写作指引「素材底稿」行）：图片占位转人话、表格线替空格、
 *  剥标题#/加粗记号、折叠全部空白、超长截断。只取首个 section——预览要的是
 *  「开头写什么」，不是全量。 */
export function blockPreviewText(sections: { text: string }[] | undefined, maxChars: number): string {
  const s = (sections?.[0]?.text ?? '')
    .replace(/!\[\]\(图片\)/g, '（含图）')
    .replace(/\|/g, ' ')
    .replace(/(^|\s)#{1,6}\s*/g, '$1')
    .replace(/\*\*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return ''
  return s.length > maxChars ? `${s.slice(0, maxChars)}…` : s
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

// ---------- 指引查看态：过滤 + 一级章节分组（纯显示用途，2026-09-09 设计稿 A+D） ----------

export type GuideFilterKey = 'all' | 'missing' | 'stale' | 'offtree' | 'todo' | 'written'

/** 指引行的问题/进度标记——过滤胶囊与计数共用同一份判定，避免两处口径漂移。 */
export interface GuideRowFlags {
  /** 素材列带【缺】 */
  missing: boolean
  /** 素材列引用的块 id 已不在素材库（块失效） */
  stale: boolean
  /** 节名不在目录叶子中（目录改版后未对齐） */
  offtree: boolean
  /** 该节已有正文文件 */
  written: boolean
}

/** 行标记判定。leafKeys 传 null=无目录产物（offtree 恒 false，不判越界）。 */
export function guideRowFlags(
  sectionCell: string,
  materialCell: string,
  opts: { validBlockIds: Set<string>; leafKeys: Set<string> | null; written: boolean },
): GuideRowFlags {
  const mat = parseBlockRefs(materialCell)
  return {
    missing: mat.missing,
    stale: mat.blockIds.some((id) => !opts.validBlockIds.has(id)),
    offtree: opts.leafKeys !== null && !opts.leafKeys.has(sectionCell),
    written: opts.written,
  }
}

/** 过滤谓词：行标记是否命中某枚过滤值（单选，同设计稿 D 的胶囊交互）。 */
export function guideRowMatches(f: GuideRowFlags, key: GuideFilterKey): boolean {
  switch (key) {
    case 'all':
      return true
    case 'missing':
      return f.missing
    case 'stale':
      return f.stale
    case 'offtree':
      return f.offtree
    case 'todo':
      return !f.written
    case 'written':
      return f.written
  }
}

/** 叶子的分组归属：一级章节（最顶层祖先）+ 二级章节（顶层之下的那层容器；
 *  顶层直接挂叶子时 second=null）。 */
export interface LeafGroup {
  top: string
  second: string | null
}

/**
 * 两级章节分组：叶子键 → {top=顶层章节, second=顶层之下的容器章节}。
 * 顶层节点自身是叶子时组=自身（second=null）；叶子挂在顶层下（深度 3）second=null；
 * 更深叶子（册→顶层→二级→…→叶子）second=祖先链上第二层。多册按册分键互不串台；
 * 无树/空树返回 null（不分组）。大章内部几十行平铺时二级分组是层级可读性的主力。
 */
export function leafGroups(docs: EditDoc[] | undefined, multi: boolean): Map<string, LeafGroup> | null {
  const list = docs ?? []
  if (!list.length) return null
  const out = new Map<string, LeafGroup>()
  const walk = (vol: string, top: string, second: string | null, nodes: EditNode[] | undefined) => {
    for (const n of nodes ?? []) {
      if (n.children?.length) {
        const title = (n.目录名称 ?? '').trim()
        walk(vol, top, second ?? (title || null), n.children)
        continue
      }
      const title = (n.目录名称 ?? '').trim()
      if (title) out.set(leafKey(vol, title, multi), { top, second })
    }
  }
  for (const d of list) {
    const vol = (d.name ?? '').trim() || '主册'
    for (const top of d.directory ?? []) {
      const topTitle = (top.目录名称 ?? '').trim()
      if (topTitle) walk(vol, topTitle, null, top.children?.length ? top.children : [top])
    }
  }
  return out.size > 0 ? out : null
}

const REF_TYPE_ORDER = ['MAND', 'TPL', 'REQ', 'SCORE']

const refTypeOrder = (id: string) => {
  const i = REF_TYPE_ORDER.indexOf(id.split('-')[0]?.toUpperCase() ?? '')
  return i < 0 ? 9 : i
}

/** 依据 id 排序：MAND→TPL→REQ→SCORE 分组、组内按编号升序（选择器列表显示序）。 */
export function sortRefIds(ids: string[]): string[] {
  return ids.toSorted((a, b) => {
    const ta = refTypeOrder(a)
    const tb = refTypeOrder(b)
    if (ta !== tb) return ta - tb
    return (Number.parseInt(a.split('-')[1] ?? '0', 10) || 0) - (Number.parseInt(b.split('-')[1] ?? '0', 10) || 0)
  })
}

// ---------- 正文组面板显示序（纯显示用途） ----------

/** 文件路径 → 去扩展名的主干（整本册名/节标题对账用）。 */
const pathStem = (p: string): string => {
  const name = p.split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

export interface BodyRowOrder {
  /** 整本-<册>.docx（按 response_documents 册序；未匹配册名的尾置） */
  finals: string[]
  guide: string | null
  promise: string | null
  /** 节文件：按目录树叶子先序对账；未匹配的尾置、组内保持传入相对序（sort 稳定） */
  sections: string[]
}

/**
 * body/ 文件的面板显示序：整本 → 指引 → 承诺 → 节文件。章序真值是目录树序、
 * 不是文件名序（docx 合册 _tree_nodes 同款立场）；对账复用 writtenSections 的
 * 文件侧/行侧键规则。dir=null（无目录产物/解析失败）回退传入原序，节文件不排序
 * （字母序原样）——旧任务/无目录时保持现行为。
 */
export function orderBodyRows(paths: string[], dir: DirectoryData | null): BodyRowOrder {
  const out: BodyRowOrder = { finals: [], guide: null, promise: null, sections: [] }
  for (const p of paths) {
    if (!p.startsWith('body/')) continue
    const name = p.split('/').pop() ?? ''
    if (name.startsWith('整本-')) out.finals.push(p)
    else if (name === '写作指引.md' && !out.guide) out.guide = p
    else if (name === '关键事实与承诺.md' && !out.promise) out.promise = p
    else out.sections.push(p)
  }
  const docs = dir?.response_documents
  if (!docs?.length) return out
  // 整本按册序：整本-<sanitize(册名)>.docx ↔ response_documents 顺序（docx_ops 落名同款）
  const volOrder = new Map<string, number>()
  docs.forEach((d, i) => {
    const key = `整本-${sanitizeName((d.name ?? '').trim() || '主册')}`
    if (!volOrder.has(key)) volOrder.set(key, i)
  })
  const finalIdx = (p: string) => volOrder.get(pathStem(p)) ?? docs.length
  out.finals.sort((a, b) => finalIdx(a) - finalIdx(b))
  // 节文件按树序（先序叶子）；未匹配（已删节/孤儿稿）尾置
  const multi = multiVolume(docs)
  const leafOrder = new Map<string, number>()
  iterLeaves(docs).forEach((l, i) => {
    const k = rowSectionKey(l.vol, l.title, multi)
    if (!leafOrder.has(k)) leafOrder.set(k, i)
  })
  const leafCount = leafOrder.size
  const sectionIdx = (p: string) => {
    const parts = p.split('/')
    const vol = parts.length > 2 ? parts[parts.length - 2] : ''
    return leafOrder.get(fileSectionKey(vol, pathStem(p), multi)) ?? leafCount
  }
  out.sections.sort((a, b) => sectionIdx(a) - sectionIdx(b))
  return out
}
