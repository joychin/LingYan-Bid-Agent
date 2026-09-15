/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

export interface AgentCompleted {
  run_id: string;
  conversation_id: string;
  message_id: string;
  seq: number;
}
export interface AgentError {
  run_id: string;
  conversation_id: string;
  error: string;
  code?: string | null;
  seq: number;
}
/**
 * 推理模型的 chain-of-thought 增量（agent_id 非空 = 子代理内部推理）。
 */
export interface AgentReasoning {
  run_id: string;
  conversation_id: string;
  text: string;
  agent_id?: string | null;
  seq: number;
  seq_from?: number | null;
}
/**
 * LLM 瞬时错误自动重试的等待期通知（additive 2026-09-08）：前端在输出区显示
 * 「正在自动重试」shimmer 并清空未封口正文。attempt 从 1 起。
 *
 * scope（additive 2026-09-15）：失败源归属——main=主线程模型调用 / sub=子代理
 * 模型调用（异常抛出点经 runctx.agent_scope 挂到异常对象、worker 沿 __cause__
 * 链读回）。重试本身恒为整流级（从 checkpoint 断点重放，波次中失败=整波重放），
 * scope 只标注断在哪一侧；缺省 main 兼容旧载荷。
 */
export interface AgentRetry {
  run_id: string;
  conversation_id: string;
  attempt: number;
  total: number;
  wait_seconds: number;
  scope?: "main" | "sub";
  seq: number;
}
export interface AgentStarted {
  run_id: string;
  conversation_id: string;
  seq: number;
}
export interface AgentToken {
  run_id: string;
  conversation_id: string;
  text: string;
  seq: number;
  seq_from?: number | null;
}
/**
 * run 边界产物事件（events.artifact_created_payload；run_id 恒非空——
 * 不在 run 内无 seq 宿主）。2026-08-31 scope/promotion_proposed → state；
 * 2026-09-04 两态移除、state 键删除（均 reshape 非 additive，前端 events.gen.ts
 * 同批再生）。
 */
export interface ArtifactCreated {
  run_id?: string | null;
  conversation_id: string;
  artifact_id: string;
  display_name: string;
  kind: string;
  schema_id: string;
  schema_version: number;
  task_id?: string | null;
  seq: number;
}
/**
 * 自动命名完成推送（连接级，无 run_id/seq）。
 */
export interface ConversationRenamed {
  conversation_id: string;
  title: string;
}
/**
 * 交付物呈现信号（契约 additive 2026-09-13；二批改定呈现时机）：产出侧声明
 * 「这是值得展示给用户的交付物」，前端收到即自动打开产物面板。声明在工具成功
 * 点入队，事件在 **run 正常完成时**取最后一个声明、在终态事件前发出（error/
 * 取消/等待输入段不呈现）。瞬时信号：不落库、不重放、错过不补。
 * kind=artifact 开产物视图（artifact_id），kind=file 开工作台文件
 * （path 相对 <task>/work/，与「本轮文件」chips 同格式）。
 */
export interface DeliverableCreated {
  run_id: string;
  conversation_id: string;
  kind: "artifact" | "file";
  artifact_id?: string | null;
  path?: string | null;
  display_name?: string | null;
  seq: number;
}
/**
 * HITL 待裁决动作（run.interrupt / run.state(waiting_input) 附带）。
 */
export interface InterruptRequestPayload {
  tool: string;
  args: {
    [k: string]: unknown;
  };
  description?: string;
  allowed?: string[];
  interrupt_id?: string;
}
export interface RunInterrupt {
  run_id: string;
  conversation_id: string;
  requests: InterruptRequestPayload[];
  seq: number;
}
/**
 * SSE 连接建立时下发的对账事件（连接级，无 seq——同 ping）。
 */
export interface RunState {
  run_id: string;
  conversation_id: string;
  status: "running" | "completed" | "error" | "waiting_input";
  error?: string | null;
  code?: string | null;
  requests?: InterruptRequestPayload[] | null;
  started_at?: number | null;
}
export interface TodoItemPayload {
  content: string;
  status: "pending" | "in_progress" | "completed";
}
export interface TodoUpdated {
  run_id: string;
  conversation_id: string;
  done: number;
  total: number;
  items: TodoItemPayload[];
  seq: number;
}
export interface ToolCalled {
  run_id: string;
  conversation_id: string;
  tool: string;
  args: {
    [k: string]: unknown;
  };
  tool_call_id?: string | null;
  agent_id?: string | null;
  seq: number;
}
export interface ToolResult {
  run_id: string;
  conversation_id: string;
  tool: string;
  summary: string;
  error?: string | null;
  tool_call_id?: string | null;
  agent_id?: string | null;
  seq: number;
}
