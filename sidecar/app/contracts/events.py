"""SSE 事件 payload 契约模型（§5.5 事件的单一事实源）。

- 事件名常量与 LangGraph 流 → 事件的映射仍在 app/events.py（唯一适配层）；本文件只
  描述各事件 payload 的形状，供 test_contract.py 校验真实发布数据、scripts/gen_ts_types.py
  生成前端类型（frontend/src/api/events.gen.ts）——前后端字段对齐从「注释纪律」变成
  「模型断言 + 生成」，additive 扩展在此登记后重新生成即可。
- 纯 pydantic、零 langchain 依赖（保证生成器干净）。
- 字段与 events.py / agent.py / api/sse.py 的构造逐字一致；改字段 = 改这里 + 重新生成。
"""

from typing import Literal

from pydantic import BaseModel

TodoStatus = Literal["pending", "in_progress", "completed"]
RunStatus = Literal["running", "completed", "error", "waiting_input"]


class TodoItemPayload(BaseModel):
    content: str
    status: TodoStatus


class AgentStarted(BaseModel):
    run_id: str
    conversation_id: str
    seq: int


class AgentToken(BaseModel):
    run_id: str
    conversation_id: str
    text: str
    seq: int


class AgentReasoning(BaseModel):
    """推理模型的 chain-of-thought 增量（agent_id 非空 = 子代理内部推理）。"""

    run_id: str
    conversation_id: str
    text: str
    agent_id: str | None = None
    seq: int


class ToolCalled(BaseModel):
    run_id: str
    conversation_id: str
    tool: str
    args: dict
    tool_call_id: str | None = None
    agent_id: str | None = None
    seq: int


class ToolResult(BaseModel):
    run_id: str
    conversation_id: str
    tool: str
    summary: str
    error: str | None = None
    tool_call_id: str | None = None
    agent_id: str | None = None
    seq: int


class TodoUpdated(BaseModel):
    run_id: str
    conversation_id: str
    done: int
    total: int
    items: list[TodoItemPayload]
    seq: int


class ArtifactCreated(BaseModel):
    """run 边界产物事件（events.artifact_created_payload；run_id 恒非空——确认端点
    不发 SSE，不在 run 内无 seq 宿主）。2026-08-31 重构时 scope/promotion_proposed
    两键一次性替换为 state（reshape 非 additive，前端 events.gen.ts 同批再生）。"""

    run_id: str | None = None
    conversation_id: str
    artifact_id: str
    display_name: str
    kind: str
    schema_id: str
    schema_version: int
    state: Literal["draft", "confirmed"]
    task_id: str | None = None
    seq: int


class AgentCompleted(BaseModel):
    run_id: str
    conversation_id: str
    message_id: str
    seq: int


class AgentError(BaseModel):
    run_id: str
    conversation_id: str
    error: str
    # cancelled=用户主动停止（前端中性呈现）；非取消恒为 None（键恒存在，2026-08-27 additive）
    code: str | None = None
    seq: int


class InterruptRequestPayload(BaseModel):
    """HITL 待裁决动作（run.interrupt / run.state(waiting_input) 附带）。"""

    tool: str
    args: dict
    description: str = ""
    allowed: list[str] = ["approve", "reject"]


class RunInterrupt(BaseModel):
    run_id: str
    conversation_id: str
    requests: list[InterruptRequestPayload]
    seq: int


class RunState(BaseModel):
    """SSE 连接建立时下发的对账事件（连接级，无 seq——同 ping）。"""

    run_id: str
    conversation_id: str
    status: RunStatus
    error: str | None = None
    code: str | None = None
    requests: list[InterruptRequestPayload] | None = None


class ConversationRenamed(BaseModel):
    """自动命名完成推送（连接级，无 run_id/seq）。"""

    conversation_id: str
    title: str


# 事件名 → payload 模型。事件名常量真值在 app/events.py（适配层）；两边靠
# test_contract.py 的键集断言对齐（改一边不改另一边测试即红）。
EVENT_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "agent.started": AgentStarted,
    "agent.token": AgentToken,
    "agent.reasoning": AgentReasoning,
    "tool.called": ToolCalled,
    "tool.result": ToolResult,
    "todo.updated": TodoUpdated,
    "artifact.created": ArtifactCreated,
    "agent.completed": AgentCompleted,
    "agent.error": AgentError,
    "run.interrupt": RunInterrupt,
    "run.state": RunState,
    "conversation.renamed": ConversationRenamed,
}
