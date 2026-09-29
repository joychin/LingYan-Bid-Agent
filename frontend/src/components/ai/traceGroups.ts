import type { ToolStep } from '@/api/sse'
import { skillFileInfo } from '@/components/ai/toolDisplay'

/** RunTrace 步骤列表的显示层分段（数据/SSE 契约零改动，活跑与历史 trace 同构适用）：
 *  - ask_human 连续段 → 问答折叠组（AskedQuestions，行为与旧内联装配一致）；
 *  - grep 连续段 → 检索批次折叠组（GrepBatch，≥2 才成组；废标反查词表这类
 *    同动作批量调用是「一个动作」不是 N 行噪声）；
 *  - 技能文件读取连续段 → 技能加载折叠组（SkillBatch，≥2 才成组；技能正文由模型
 *    read_file 读入，事件层无专用工具名，判据见 toolDisplay.skillFileInfo）；
 *  - 旁白开组的混合工具段 → 旁白折叠组（PhaseBatch，≥2 才成组；模型一句过程旁白
 *    领起的普通工具调用收成一张卡，组头=旁白首句——「阶段」语义，非轮次）；
 *  - 其余 → task 透传 SubagentCard、普通工具透传 ToolStepRow。
 *  开组/断组规则：非空旁白（text）开旁白组并断机械组；思考（reasoning）只在机械组
 *  断组（「组数=轮次」的诚实语义保留在机械组），旁白组内思考不拆组。机械折叠
 *  （grep/技能）优先于旁白组——词表 chips 常驻是废标审计特性，带旁白的 grep 仍走
 *  grep 批。无旁白的普通工具段维持平铺（read_file 逐章推进感拍板）。 */
export type TraceSegment =
  | { kind: 'ask'; steps: ToolStep[] }
  | { kind: 'grep'; steps: ToolStep[] }
  | { kind: 'skill'; steps: ToolStep[] }
  | { kind: 'phase'; steps: ToolStep[] }
  | { kind: 'task'; step: ToolStep }
  | { kind: 'tool'; step: ToolStep }

/** 该步骤是否技能文件读取（read_file 读 `<...>/skills/<技能名>/<文件>`）。 */
export function isSkillRead(s: ToolStep): boolean {
  return s.tool === 'read_file' && skillFileInfo(s.args?.file_path) !== null
}

export function segmentToolSteps(tools: ToolStep[]): TraceSegment[] {
  const segments: TraceSegment[] = []
  let askGroup: ToolStep[] = []
  let grepGroup: ToolStep[] = []
  let skillGroup: ToolStep[] = []
  let phaseGroup: ToolStep[] = []
  const flushAsk = () => {
    if (askGroup.length === 0) return
    segments.push({ kind: 'ask', steps: askGroup })
    askGroup = []
  }
  const flushGrep = () => {
    if (grepGroup.length === 0) return
    // 单个不成组（自扩词反查等孤立调用维持普通步骤行）
    if (grepGroup.length === 1) {
      segments.push({ kind: 'tool', step: grepGroup[0] })
    } else {
      segments.push({ kind: 'grep', steps: grepGroup })
    }
    grepGroup = []
  }
  const flushSkill = () => {
    if (skillGroup.length === 0) return
    // 单个不成组（子代理开局读一份技能文档是常态，占一行更清楚）
    if (skillGroup.length === 1) {
      segments.push({ kind: 'tool', step: skillGroup[0] })
    } else {
      segments.push({ kind: 'skill', steps: skillGroup })
    }
    skillGroup = []
  }
  const flushPhase = () => {
    if (phaseGroup.length === 0) return
    // 单个不成组（一句旁白只带一个动作=普通步骤行自带旁白渲染，视觉与旧态一致）
    if (phaseGroup.length === 1) {
      segments.push({ kind: 'tool', step: phaseGroup[0] })
    } else {
      segments.push({ kind: 'phase', steps: phaseGroup })
    }
    phaseGroup = []
  }
  for (const s of tools) {
    if (s.tool === 'ask_human') {
      flushPhase()
      flushGrep()
      flushSkill()
      askGroup.push(s)
      continue
    }
    flushAsk()
    if (s.tool === 'grep') {
      flushPhase()
      flushSkill()
      if (s.text || s.reasoning) flushGrep()
      grepGroup.push(s)
      continue
    }
    if (isSkillRead(s)) {
      flushPhase()
      flushGrep()
      if (s.text || s.reasoning) flushSkill()
      skillGroup.push(s)
      continue
    }
    flushGrep()
    flushSkill()
    if (s.tool === 'task') {
      flushPhase()
      segments.push({ kind: 'task', step: s })
      continue
    }
    // 其余工具：非空旁白开旁白组（封段规则：开组步携带组头旁白，随组步 text 为空）
    if (s.text) {
      flushPhase()
      phaseGroup.push(s)
      continue
    }
    if (phaseGroup.length > 0) {
      phaseGroup.push(s)
      continue
    }
    segments.push({ kind: 'tool', step: s })
  }
  flushAsk()
  flushGrep()
  flushSkill()
  flushPhase()
  return segments
}
