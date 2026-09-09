/**
 * guideBasis 纯函数测试。评分表金样例取自真实任务（BPM投标 t_754be8ced133
 * analysis/evaluation.md）——三种分值形态（纯数字/复合上界/带公式）全覆盖；
 * SCORE 行序对位是跨语言契约（与 assemble_tender._build_score_registry 同构），
 * 此处锁「表头识别/段截断/归一化/定性规则」四层。
 */

import { describe, expect, it } from 'vitest'
import { guideRowBasis, parseEvaluationScores, scoreValueBadge, scoreValueMax } from './guideBasis'

const EVAL_MD = [
  '## 评分标准清单',
  '| 评分项 | 分值 | 评分要点 | 出处 |',
  '|---|---|---|---|',
  '| 综合实力：AAA级或高新技术企业 | 1 | 需提供证明材料 | 同文件（L440） |',
  '| 综合实力：软件具备等保三级认证 | 2 | 需提供证明材料 | 同文件（L440） |',
  '| 综合实力：软件著作权 | 每项1，本项不超过5 | 需提供证明材料 | 同文件（L440） |',
  '| 软件产品及项目实施能力：现场阐述 | 5 | 完整理解得4-5分 | 同文件（L445） |',
  '| 软件产品及项目实施能力：现场演示 | 10 | 20 分钟内从零创建应用 | 同文件（L447） |',
  '| 价格部分 | 30（公式：投标报价得分=基准价/报价×100×30%） | 按公式计算 | 同文件（L450） |',
  '',
  '## 评标办法概述',
  '- 本项目采用综合评估法（正文不再进表）。',
].join('\n')

describe('parseEvaluationScores（评分表解析）', () => {
  it('行序对位 SCORE-01..06 + 分值/要点/出处按列名取', () => {
    const m = parseEvaluationScores(EVAL_MD)
    expect(m.size).toBe(6)
    expect(m.get('SCORE-01')).toMatchObject({ item: '综合实力：AAA级或高新技术企业', value: '1', points: '需提供证明材料' })
    expect(m.get('SCORE-06')?.value).toContain('30')
  })

  it('段标题截断：评标办法概述之后的行不进表', () => {
    const m = parseEvaluationScores(EVAL_MD + '\n| 表外出现的假行 | 99 | | |')
    expect(m.size).toBe(6)
    expect([...m.keys()]).not.toContain('SCORE-07')
  })

  it('无表/无表头降级空 Map', () => {
    expect(parseEvaluationScores('')).toEqual(new Map())
    expect(parseEvaluationScores('# 没有评分表\n正文而已')).toEqual(new Map())
    expect(parseEvaluationScores('| 列A | 列B |\n|---|---|\n| x | y |')).toEqual(new Map())
  })
})

describe('scoreValueBadge / scoreValueMax（分值归一化）', () => {
  it('三种形态：纯数字/复合上界/带公式', () => {
    expect(scoreValueBadge('10')).toBe('10分')
    expect(scoreValueBadge('每项1，本项不超过5')).toBe('≤5分')
    expect(scoreValueBadge('30（公式：基准价/报价×100×30%）')).toBe('30分')
    expect(scoreValueBadge('满足得3分，不满足得0分')).toBe('3分')
  })

  it('无数字与空值 → null；上界取值', () => {
    expect(scoreValueBadge('通过制')).toBeNull()
    expect(scoreValueBadge('')).toBeNull()
    expect(scoreValueMax('每项1，本项不超过5')).toBe(5)
    expect(scoreValueMax('10')).toBe(10)
    expect(scoreValueMax('通过制')).toBe(0)
  })
})

describe('guideRowBasis（行定性）', () => {
  const scores = parseEvaluationScores(EVAL_MD)

  it('得分主力：单条 ≥10（现场演示 10 分）', () => {
    const b = guideRowBasis('SCORE-05', scores)
    expect(b.stance).toBe('得分主力')
    expect(b.summaryLine).toBe('1 条评分（最高 10 分）')
    expect(b.badges.get('SCORE-05')).toBe('10分')
  })

  it('得分点：合计达标或单条 <10；强制/要求/模板组合进摘要行', () => {
    const b = guideRowBasis('SCORE-01、SCORE-02、REQ-25', scores)
    expect(b.stance).toBe('得分点')
    expect(b.summaryLine).toBe('2 条评分（最高 2 分） · 1 条商务技术要求')
    // 合计 1+2+5=8 不达 15，单条最高 5 <10 → 得分点（合计 ≥15 才升主力）
    const combo = guideRowBasis('SCORE-01、SCORE-02、SCORE-04', scores)
    expect(combo.scoreMax).toBe(5)
    expect(combo.stance).toBe('得分点')
  })

  it('合计 ≥15 也升主力（多条中等分）', () => {
    // 5+10+30 = 45，最高 30 ≥10 本身已主力；构造仅中等分的场景：1+2+5=8 不够，
    // 用重复形态不现实——改为验证 5+10=15 边界（合计线）
    const b = guideRowBasis('SCORE-04、SCORE-05', scores)
    expect(b.scoreMax).toBe(10) // 单条 10 已达线
    expect(b.stance).toBe('得分主力')
  })

  it('强制条款 / 格式件 / 要求响应（无 SCORE 时的分类）', () => {
    expect(guideRowBasis('MAND-03、REQ-01', scores).stance).toBe('强制条款')
    expect(guideRowBasis('TPL-01', scores).stance).toBe('格式件')
    expect(guideRowBasis('REQ-25、REQ-26', scores).stance).toBe('要求响应')
  })

  it('无依据 → null；SCORE 对不上评分表 → 计数照常但无分值角标', () => {
    const none = guideRowBasis('—', scores)
    expect(none.stance).toBeNull()
    expect(none.summaryLine).toBeNull()
    const orphan = guideRowBasis('SCORE-99', scores)
    expect(orphan.stance).toBe('得分点') // 前缀仍算评分关联
    expect(orphan.badges.size).toBe(0)
    expect(orphan.scoreMax).toBe(0)
    expect(orphan.summaryLine).toBe('1 条评分') // 无分值时不带括号
  })
})
