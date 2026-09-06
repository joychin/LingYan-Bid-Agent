import type { ToolStep } from '@/api/sse'

/** RunTrace 步骤列表的显示层分段（数据/SSE 契约零改动，活跑与历史 trace 同构适用）：
 *  - ask_human 连续段 → 问答折叠组（AskedQuestions，行为与旧内联装配一致）；
 *  - grep 连续段 → 检索批次折叠组（GrepBatch，≥2 才成组；废标反查词表这类
 *    同动作批量调用是「一个动作」不是 N 行噪声）；
 *  - 其余 → task 透传 SubagentCard、普通工具透传 ToolStepRow。
 *  断组规则：grep 步骤带非空旁白（text）或思考（reasoning）= 新一轮模型轮次的
 *  首个调用（封段规则保证同轮只有首个携带），开新组——组数诚实对应轮次，
 *  且旁白/思考可常驻组头不被折叠吞掉。 */
export type TraceSegment =
  | { kind: 'ask'; steps: ToolStep[] }
  | { kind: 'grep'; steps: ToolStep[] }
  | { kind: 'task'; step: ToolStep }
  | { kind: 'tool'; step: ToolStep }

export function segmentToolSteps(tools: ToolStep[]): TraceSegment[] {
  const segments: TraceSegment[] = []
  let askGroup: ToolStep[] = []
  let grepGroup: ToolStep[] = []
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
  for (const s of tools) {
    if (s.tool === 'ask_human') {
      flushGrep()
      askGroup.push(s)
      continue
    }
    flushAsk()
    if (s.tool === 'grep') {
      if (s.text || s.reasoning) flushGrep()
      grepGroup.push(s)
      continue
    }
    flushGrep()
    if (s.tool === 'task') segments.push({ kind: 'task', step: s })
    else segments.push({ kind: 'tool', step: s })
  }
  flushAsk()
  flushGrep()
  return segments
}
