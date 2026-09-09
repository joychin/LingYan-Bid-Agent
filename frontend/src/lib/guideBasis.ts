/**
 * 写作指引「依据」定性数据层（2026-09-09 设计稿 F+H，纯函数）：
 * 「为什么要写这一章、有多重要」三层信息的前两层——定性（stance）与分值。
 *
 * 数据源=analysis/evaluation.md 评分表。registry 不存分值（assemble_tender
 * `_build_score_registry` 只取评分项/出处两列），但 SCORE 编号=表体行序（两位
 * 零填充，同构机械对位，BPM 任务 13/13 实测验证）——前端按行序解析即得
 * SCORE-xx → 分值/评分要点，零后端改动。
 *
 * 解析宽容（表头按名识别、段截断、无表降级空 Map），定性规则纯机械
 * （分值阈值/前缀计数），不引入 LLM——「LLM 语义、程序机械」铁则。
 */

import { parseRefIds } from './workbenchTable'

/** 评分表一行（item/value/source 为原文列，points=评分要点）。 */
export interface ScoreRow {
  item: string
  value: string
  points?: string
  source?: string
}

const SEP_CELL_RE = /^:?-{2,}:?$/

const splitRow = (line: string): string[] =>
  line
    .trim()
    .replace(/^\|+/, '')
    .replace(/\|+$/, '')
    .split('|')
    .map((c) => c.trim())

/**
 * 解析 evaluation.md 的评分标准清单：表头含「评分项」与「分值」的表格，
 * 数据行第 n 行 → SCORE-{nn}（两位补零，与 assemble_tender 行序赋号同构）；
 * 表块随任意非 `|` 行结束（含 `##` 段标题——评标办法概述/待澄清登记等不进表）。
 * 无表/无数据行返回空 Map（调用方降级：不显示分值，定性计数照常）。
 */
export function parseEvaluationScores(md: string): Map<string, ScoreRow> {
  const lines = md.split('\n')
  let i = 0
  // 定位表头行：| 开头、含「评分项」与「分值」两列
  while (i < lines.length) {
    const l = lines[i]
    if (l.trimStart().startsWith('|')) {
      const cells = splitRow(l)
      if (cells.includes('评分项') && cells.includes('分值')) break
    }
    i += 1
  }
  if (i >= lines.length) return new Map()
  // 表头列下标（评分项/分值/评分要点/出处按名取，缺列容错）
  const header = splitRow(lines[i])
  const idxOf = (name: string) => header.indexOf(name)
  const iItem = idxOf('评分项')
  const iValue = idxOf('分值')
  const iPoints = idxOf('评分要点')
  const iSource = idxOf('出处')
  i += 1
  const out = new Map<string, ScoreRow>()
  while (i < lines.length) {
    const l = lines[i]
    if (!l.trimStart().startsWith('|')) break // 表块结束（空行/段标题均截断）
    const cells = splitRow(l)
    if (!(cells.length >= 2 && cells.every((c) => SEP_CELL_RE.test(c)))) {
      const item = iItem >= 0 ? (cells[iItem] ?? '') : ''
      if (item && item !== '评分项' && item !== '评分标准') {
        const id = `SCORE-${String(out.size + 1).padStart(2, '0')}`
        out.set(id, {
          item,
          value: iValue >= 0 ? (cells[iValue] ?? '') : '',
          points: iPoints >= 0 ? (cells[iPoints] ?? '') : undefined,
          source: iSource >= 0 ? (cells[iSource] ?? '') : undefined,
        })
      }
    }
    i += 1
  }
  return out
}

/** 分值角标归一化：'10'→'10分'；'每项1，本项不超过5'→'≤5分'（优先「不超过N」）；'30（公式…）'→'30分'；无数字→null。 */
export function scoreValueBadge(value: string): string | null {
  const v = value.trim()
  if (!v) return null
  const cap = v.match(/不超过\s*(\d+(?:\.\d+)?)/)
  if (cap) return `≤${cap[1]}分`
  const first = v.match(/(\d+(?:\.\d+)?)/)
  return first ? `${first[1]}分` : null
}

/** 定性阈值用的上界分值（复合形态取「不超过N」，否则首个数字；无数字 0）。 */
export function scoreValueMax(value: string): number {
  const cap = value.match(/不超过\s*(\d+(?:\.\d+)?)/)
  const m = cap ?? value.match(/(\d+(?:\.\d+)?)/)
  return m ? Number.parseFloat(m[1]) : 0
}

/** 行定性结论（guideRowBasis 产物）。 */
export interface RowBasis {
  /** 本章定位（机械规则）：得分主力/得分点/强制条款/格式件/要求响应；无依据 null */
  stance: string | null
  /** 摘要行文案（如「得分点 · 2 条评分（最高 10 分） · 3 条强制要求」）；无依据 null */
  summaryLine: string | null
  /** 依据 id 的分值角标（仅 SCORE 且 evaluation 表中能对上的） */
  badges: Map<string, string>
  /** 评分类依据的最高分值（无评分/对不上为 0） */
  scoreMax: number
}

/**
 * 指引行「依据」列的定性：按 id 前缀分类计数 + SCORE 关联分值。
 * stance 规则（纯机械，先命中先得）：任一评分上界 ≥10 或合计 ≥15 → 得分主力；
 * 有 SCORE → 得分点；有 MAND → 强制条款；仅 TPL → 格式件；有 REQ → 要求响应。
 */
export function guideRowBasis(refCell: string, scores: Map<string, ScoreRow>): RowBasis {
  const ids = parseRefIds(refCell).ids
  const badges = new Map<string, string>()
  let scoreCount = 0
  let mandCount = 0
  let tplCount = 0
  let reqCount = 0
  let scoreTotal = 0
  let scoreMax = 0
  for (const id of ids) {
    if (id.startsWith('SCORE')) {
      scoreCount += 1
      const score = scores.get(id)
      if (score) {
        const badge = scoreValueBadge(score.value)
        if (badge) badges.set(id, badge)
        const max = scoreValueMax(score.value)
        scoreTotal += max
        scoreMax = Math.max(scoreMax, max)
      }
    } else if (id.startsWith('MAND')) mandCount += 1
    else if (id.startsWith('TPL')) tplCount += 1
    else if (id.startsWith('REQ')) reqCount += 1
  }
  if (ids.length === 0) return { stance: null, summaryLine: null, badges, scoreMax: 0 }

  const parts: string[] = []
  if (scoreCount > 0) parts.push(`${scoreCount} 条评分${scoreMax > 0 ? `（最高 ${scoreMax} 分）` : ''}`)
  if (mandCount > 0) parts.push(`${mandCount} 条强制要求`)
  if (reqCount > 0) parts.push(`${reqCount} 条商务技术要求`)
  if (tplCount > 0) parts.push(`${tplCount} 份格式件`)

  let stance: string
  if (scoreCount > 0 && (scoreMax >= 10 || scoreTotal >= 15)) stance = '得分主力'
  else if (scoreCount > 0) stance = '得分点'
  else if (mandCount > 0) stance = '强制条款'
  else if (tplCount > 0 && reqCount === 0) stance = '格式件'
  else stance = '要求响应'
  return { stance, summaryLine: parts.join(' · '), badges, scoreMax }
}
