import type { Message } from '@/api/client'

/** sidecar 落库时拼在半截回复末尾的状态标记（agent.py interrupt/error 分支）。
 *  渲染层剥掉换成状态徽章，正文文字归过程卡（HITL 痕迹不占正文区）。 */
export const PAUSE_MARKER = '\n\n（等待你的输入…）'
export const INTERRUPTED_MARKER = '\n\n（任务中断）'

export type PauseMarker = 'pause' | 'interrupted' | null

/** 裸标记消息（无正文、仅标记——提问前模型零旁白时暂停消息的形态） */
const BARE_MARKERS: [string, Exclude<PauseMarker, null>][] = [
  ['（等待你的输入…）', 'pause'],
  ['（任务中断）', 'interrupted'],
]

export function splitMarker(content: string): { body: string; marker: PauseMarker } {
  for (const [bare, marker] of BARE_MARKERS) {
    if (content === bare) return { body: '', marker }
  }
  if (content.endsWith(PAUSE_MARKER)) {
    return { body: content.slice(0, -PAUSE_MARKER.length), marker: 'pause' }
  }
  if (content.endsWith(INTERRUPTED_MARKER)) {
    return { body: content.slice(0, -INTERRUPTED_MARKER.length), marker: 'interrupted' }
  }
  return { body: content, marker: null }
}

export function isPauseMarked(content: string): boolean {
  return splitMarker(content).marker !== null
}

/** 暂停/中断标记的状态徽章文案（渲染层用；正文不再保留尾巴文本）。 */
export const MARKER_CHIP: Record<'pause' | 'interrupted', string> = {
  pause: '⏣ 曾在此等待你的输入',
  interrupted: '已中断',
}

/**
 * 是否为 HITL respond 回答的落库消息（不渲染为对话气泡，答案由过程卡的
 * 问答组展示）：判定 = 前一条 assistant 消息带暂停/中断标记（同回合位置判定，
 * 覆盖纯文字回答），辅以历史信号「已选：」前缀（点选项拼装的既定格式）。
 *
 * run_id 硬校验（新落库消息均带 run_id）：回答与被拦截的 assistant 同属一个
 * run；不一致（如 error/停止收尾后用户发的新指令，run_id 是新 run 的）一律不
 * 算回答——只靠前缀/位置启发式会把「停止任务 → 输入新指令」的指令从转录里
 * 吞掉，并让「重新执行」重发更早的旧指令。任一侧缺 run_id（迁移前历史数据）
 * 回退纯启发式。
 */
export function isRespondAnswer(messages: Message[], i: number): boolean {
  const m = messages[i]
  if (!m || m.role !== 'user' || i === 0) return false
  const prev = messages[i - 1]
  const prevMarked = prev.role === 'assistant' && isPauseMarked(prev.content)
  const prefixSignal = m.content.startsWith('已选：')
  if (!prefixSignal && !prevMarked) return false
  if (m.run_id && prev.run_id) return m.run_id === prev.run_id
  return true
}

/** 取转录里最后一条真实指令（「重新执行」重发用）：跳过 HITL 回答消息。 */
export function lastInstructionText(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role !== 'user') continue
    if (isRespondAnswer(messages, i)) continue
    return m.content
  }
  return ''
}
