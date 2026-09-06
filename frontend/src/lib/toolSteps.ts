import type { ToolStep } from '@/api/sse'

/** 历史 trace 步骤树的防御性归一。
 *  run_traces 存的是原始 dict 序列化（Pydantic 只验证不物化默认值），且键集随版本
 *  演进（text/reasoning 08-26、startedAt/endedAt 08-28…）——旧库快照缺键是常态而非
 *  异常。渲染层按 ToolStep 直接解引用（如 step.children.length），缺键即 TypeError
 *  打到唯一根级 ErrorBoundary 变整窗错误页。在 API 出口一处收口补默认值；
 *  live 树由 runReducer 构造、恒完备，不经此路径。 */
export function normalizeToolSteps(raw: unknown): ToolStep[] {
  if (!Array.isArray(raw)) return []
  return raw.map((node, i) => {
    const s = (node ?? {}) as Partial<ToolStep> & Record<string, unknown>
    const status =
      s.status === 'running' || s.status === 'error' || s.status === 'paused' ? s.status : 'done'
    return {
      // id 是列表 key 须唯一；sidecar 侧用 tool_call_id 生成，缺省退化到下标
      id: typeof s.id === 'string' && s.id ? s.id : `step-${i}`,
      tool: typeof s.tool === 'string' ? s.tool : 'unknown',
      args: s.args && typeof s.args === 'object' ? (s.args as Record<string, unknown>) : {},
      status,
      summary: typeof s.summary === 'string' ? s.summary : '',
      error: typeof s.error === 'string' ? s.error : null,
      toolCallId: typeof s.toolCallId === 'string' ? s.toolCallId : null,
      reasoning: typeof s.reasoning === 'string' ? s.reasoning : '',
      text: typeof s.text === 'string' ? s.text : undefined,
      children: normalizeToolSteps(s.children),
      startedAt: typeof s.startedAt === 'number' ? s.startedAt : 0,
      endedAt: typeof s.endedAt === 'number' ? s.endedAt : null,
    }
  })
}
