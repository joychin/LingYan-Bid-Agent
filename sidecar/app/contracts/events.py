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
    # 微合批（2026-09-08 additive）：SSE 发送层把窗口内连续增量合并成一帧时
    # seq=合并的最大序号、seq_from=首序号——前端缺口检查用 seq_from（连续=非缺口）。
    seq_from: int | None = None


class AgentReasoning(BaseModel):
    """推理模型的 chain-of-thought 增量（agent_id 非空 = 子代理内部推理）。"""

    run_id: str
    conversation_id: str
    text: str
    agent_id: str | None = None
    seq: int
    seq_from: int | None = None


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
    """run 边界产物事件（events.artifact_created_payload；run_id 恒非空——
    不在 run 内无 seq 宿主）。2026-08-31 scope/promotion_proposed → state；
    2026-09-04 两态移除、state 键删除（均 reshape 非 additive，前端 events.gen.ts
    同批再生）。"""

    run_id: str | None = None
    conversation_id: str
    artifact_id: str
    display_name: str
    kind: str
    schema_id: str
    schema_version: int
    task_id: str | None = None
    seq: int


class DeliverableCreated(BaseModel):
    """交付物呈现信号（契约 additive 2026-09-13；二批改定呈现时机）：产出侧声明
    「这是值得展示给用户的交付物」，前端收到即自动打开产物面板。声明在工具成功
    点入队，事件在 **run 正常完成时**取最后一个声明、在终态事件前发出（error/
    取消/等待输入段不呈现）。瞬时信号：不落库、不重放、错过不补。
    kind=artifact 开产物视图（artifact_id），kind=file 开工作台文件
    （path 相对 <task>/work/，与「本轮文件」chips 同格式）。"""

    run_id: str
    conversation_id: str
    kind: Literal["artifact", "file"]
    artifact_id: str | None = None
    path: str | None = None
    display_name: str | None = None
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
    # 错误定性（键恒存在，2026-08-27 additive；取值域 2026-09-08 扩展）：
    # cancelled=用户主动停止（中性呈现）；llm_unavailable=模型服务方过载/超时/断流
    # （自动重试耗尽）；llm_auth=模型未配置/Key 失效（前端给「去设置」入口）；
    # internal=程序自身错误；None=未分类（旧 sidecar）。error 文案首行人话、
    # 次行起为服务方/异常原文（前端按 \n 拆行渲染）
    code: str | None = None
    seq: int


class AgentRetry(BaseModel):
    """LLM 瞬时错误自动重试的等待期通知（additive 2026-09-08）：前端在输出区显示
    「正在自动重试」shimmer 并清空未封口正文。attempt 从 1 起。"""

    run_id: str
    conversation_id: str
    attempt: int
    total: int
    wait_seconds: float
    seq: int


class InterruptRequestPayload(BaseModel):
    """HITL 待裁决动作（run.interrupt / run.state(waiting_input) 附带）。"""

    tool: str
    args: dict
    description: str = ""
    allowed: list[str] = ["approve", "reject"]
    # 归属的 langgraph Interrupt id（additive，2026-09-06 多中断恢复：resume 按 id
    # 分组映射；旧快照/前端不消费为可缺省）
    interrupt_id: str = ""


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
    # 错误定性（取值域同 AgentError.code：error 终态时下发，含 interrupted=
    # sidecar 重启中断——仅经本事件恢复的历史 run 会见到）
    code: str | None = None
    requests: list[InterruptRequestPayload] | None = None
    # run 开始时间（epoch ms，来源 runs.created_at）：客户端刷新/重连恢复 running 态时
    # 活卡计时按真实起点续算（此前拿不到起点、从恢复时刻重算是可见失真）
    started_at: int | None = None


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
    "deliverable.created": DeliverableCreated,
    "agent.completed": AgentCompleted,
    "agent.error": AgentError,
    "agent.retry": AgentRetry,
    "run.interrupt": RunInterrupt,
    "run.state": RunState,
    "conversation.renamed": ConversationRenamed,
}
