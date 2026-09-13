import type { ToolStep } from '@/api/sse'
import { skillFileInfo } from '@/components/ai/toolDisplay'

/** RunTrace 步骤列表的显示层分段（数据/SSE 契约零改动，活跑与历史 trace 同构适用）：
 *  - ask_human 连续段 → 问答折叠组（AskedQuestions，行为与旧内联装配一致）；
 *  - grep 连续段 → 检索批次折叠组（GrepBatch，≥2 才成组；废标反查词表这类
 *    同动作批量调用是「一个动作」不是 N 行噪声）；
 *  - 技能文件读取连续段 → 技能加载折叠组（SkillBatch，≥2 才成组；技能正文由模型
 *    read_file 读入，事件层无专用工具名，判据见 toolDisplay.skillFileInfo）；
 *  - 其余 → task 透传 SubagentCard、普通工具透传 ToolStepRow。
 *  断组规则：组内步骤带非空旁白（text）或思考（reasoning）= 新一轮模型轮次的
 *  首个调用（封段规则保证同轮只有首个携带），开新组——组数诚实对应轮次，
 *  且旁白/思考可常驻组头不被折叠吞掉。 */
export type TraceSegment =
  | { kind: 'ask'; steps: ToolStep[] }
  | { kind: 'grep'; steps: ToolStep[] }
  | { kind: 'skill'; steps: ToolStep[] }
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
  for (const s of tools) {
    if (s.tool === 'ask_human') {
      flushGrep()
      flushSkill()
      askGroup.push(s)
      continue
    }
    flushAsk()
    if (s.tool === 'grep') {
      flushSkill()
      if (s.text || s.reasoning) flushGrep()
      grepGroup.push(s)
      continue
    }
    if (isSkillRead(s)) {
      flushGrep()
      if (s.text || s.reasoning) flushSkill()
      skillGroup.push(s)
      continue
    }
    flushGrep()
    flushSkill()
    if (s.tool === 'task') segments.push({ kind: 'task', step: s })
    else segments.push({ kind: 'tool', step: s })
  }
  flushAsk()
  flushGrep()
  flushSkill()
  return segments
}
