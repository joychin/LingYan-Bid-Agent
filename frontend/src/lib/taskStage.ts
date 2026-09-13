/** 任务阶段（sidecar task_stage.py 推导）→ 界面文案。
 *
 * 真值在 sidecar（`STAGES` 顺序即流水线推进序：new→parsed→analyzed→outlined→
 * drafting→delivered），前端只做词映射，不推断、不参与判定——未知值原样回落，
 * 后端加新阶段时界面不会空白（宁可显示英文码，也不要空胶囊）。
 */
const STAGE_LABELS: Record<string, string> = {
  new: '刚开始',
  parsed: '已解析',
  analyzed: '要点已提取',
  outlined: '目录已生成',
  drafting: '正文写作中',
  delivered: '已完结',
}

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return ''
  return STAGE_LABELS[stage] ?? stage
}

/** 「已完结」类阶段：列表里做弱化显示（同侧栏「已归档」的观感分层） */
export function isFinishedStage(stage: string | null | undefined): boolean {
  return stage === 'delivered'
}
