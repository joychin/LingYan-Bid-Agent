"""LangGraph 流 → SSE 事件的唯一映射层。

DeepAgents 处于 beta，库内部格式变化只改这个文件，事件契约（agent.started / agent.token /
tool.called / tool.result / agent.completed / agent.error / ping /
todo.updated / artifact.created / run.state）不可变。
additive 扩展：agent.reasoning（推理模型）；tool_call_id / agent_id（子代理过程透传——
agent.stream 开 subgraphs=True 后，子代理内部 tool 调用与 reasoning 以
agent_id=所属 task 的 tool_call_id 归属下发；子代理正文 token 不透传，与 task 结果重复）；
conversation.renamed（自动命名推送，无 seq）。
"""

import html
import json
import logging
import re
from typing import Iterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

logger = logging.getLogger(__name__)

EVENT_STARTED = "agent.started"
EVENT_TOKEN = "agent.token"
EVENT_TOOL_CALLED = "tool.called"
EVENT_TOOL_RESULT = "tool.result"
EVENT_COMPLETED = "agent.completed"
EVENT_ERROR = "agent.error"
EVENT_TODO_UPDATED = "todo.updated"
EVENT_ARTIFACT_CREATED = "artifact.created"
# 推理模型（DeepSeek reasoner）的 chain-of-thought 增量文本；非推理模型不产生该事件
EVENT_REASONING = "agent.reasoning"
# LLM 瞬时错误自动重试的等待期通知（契约 additive 2026-09-08）：前端在输出区显示
# 「正在自动重试」shimmer 并清空未封口正文（与 sidecar cur_text_parts.clear() 对齐）
EVENT_AGENT_RETRY = "agent.retry"
# HITL：agent 调用 interrupt_on 登记的工具时暂停，等待用户裁决（approve/reject/respond/edit）
# 后经 Command(resume={"decisions":[...]}) 续跑（契约 additive 扩展）
EVENT_RUN_INTERRUPT = "run.interrupt"
# 自动命名完成推送（契约 additive 扩展）：titler 生成标题并写入后发布。
# 连接级事件不带 seq（同 ping/run.state，不属于任何 run 的事件流）
EVENT_CONVERSATION_RENAMED = "conversation.renamed"
# SSE 连接建立时由端点直接下发的对账事件（非 iter_stream 产出）：
# 携带该会话最新 run 的真实状态，客户端据此恢复 running 或收敛
EVENT_RUN_STATE = "run.state"

# 用户主动停止（协作式取消）时 run 的 error 文案。agent.error/run.state 据此带
# code="cancelled"（契约 additive 扩展，2026-08-27）：前端对主动停止做中性呈现，
# 不与真实错误共用红色错误卡。定义在 events.py 供 agent / api 共用。
CANCELLED_MESSAGE = "任务已停止"


def artifact_created_payload(row: dict, rid: str | None, cid: str, seq: int) -> dict:
    """artifact.created 的 data 载荷（run 边界产物事件；不在 run 内无 seq 宿主）。

    2026-08-31 重构 reshape（非 additive）：scope/promotion_proposed 两键一次性
    替换为 state（draft/confirmed）；2026-09-04 两态整体移除、state 键删除
    （产物=单一当前版本），前端 events.gen.ts 同批再生。task_id 恒为所属任务；
    conversation_id 即事件宿主会话（run 边界产物必属该会话）。
    """
    task_id = row.get("task_id")
    return {
        "run_id": rid,
        "conversation_id": cid,
        "artifact_id": row["artifact_id"],
        "display_name": row["display_name"],
        "kind": row["kind"],
        "schema_id": row["schema_id"],
        "schema_version": row["schema_version"],
        "task_id": task_id,
        "seq": seq,
    }

# ---- run 边界事件 payload 构造 ----
# 与 artifact_created_payload 同款先例：构造集中在本文件，契约形状的单一事实源在
# app/contracts/events.py（pydantic 模型），test_contract.py 两者互证。


def started_payload(rid: str, cid: str, seq: int) -> dict:
    return {"run_id": rid, "conversation_id": cid, "seq": seq}


def completed_payload(rid: str, cid: str, message_id: str, seq: int) -> dict:
    return {"run_id": rid, "conversation_id": cid, "message_id": message_id, "seq": seq}


def error_payload(rid: str, cid: str, error: str, code: str | None, seq: int) -> dict:
    """agent.error：code 恒有键（2026-08-27 additive）。取值域（2026-09-08 扩展）：
    cancelled=用户主动停止；llm_unavailable=模型服务方过载/超时/断流（重试耗尽）；
    llm_auth=模型未配置/Key 失效；internal=程序自身错误；None=未分类（旧 sidecar）。
    error 文案首行人话、次行起为服务方/异常原文（前端按 \\n 拆行渲染）。"""
    return {"run_id": rid, "conversation_id": cid, "error": error, "code": code, "seq": seq}


def retry_payload(rid: str, cid: str, attempt: int, total: int, wait_seconds: float) -> dict:
    """agent.retry：自动重试等待期通知（seq 由 _publish 闭包统一补，同 tool 事件）。"""
    return {
        "run_id": rid,
        "conversation_id": cid,
        "attempt": attempt,
        "total": total,
        "wait_seconds": wait_seconds,
    }


def interrupt_payload(rid: str, cid: str, requests: list, seq: int) -> dict:
    return {"run_id": rid, "conversation_id": cid, "requests": requests, "seq": seq}


# updates 流里「真实执行节点」白名单：只有这两个节点的 messages 代表本轮新工作
# （model=模型新产出的 AIMessage（tool_calls→tool.called）、tools=工具执行结果
# （ToolMessage→tool.result））。其余节点的 messages 是状态重写不是新工作——尤其
# deepagents PatchToolCallsMiddleware 的 before_agent 钩子：新 run 开头发现悬空
# tool_calls（上一 run 中断/停止遗留）时，会把整段历史消息原对象 + 补插的取消
# ToolMessage 一并写进 updates，照译会把上一轮全部工具步骤重放进本轮的 SSE 与
# trace（2026-09-08 实证：中断 run 的下一轮 trace 混入 12~64 个外来 tool_call_id，
# 前端活卡显示上一轮的工具卡）。子代理子图同名节点照常翻译（ns 归属不受影响）。
_TOOL_EVENT_NODES = frozenset({"model", "tools"})

# ---- 子代理归属注册表 ----
# task 工具执行时（agent._SubagentTagMiddleware.wrap_tool_call）登记：tools 任务的
# checkpoint_ns（形如 "tools:<tid>"，恰为子代理事件 ns 元组的第 0 段）→ task 的 tool_call_id。
# 注册发生在子代理启动之前、事件消费之前，因此并发子代理也能精确归属（无时序歧义）。
# ns 与 tool_call_id 在 langgraph 层无稳定等式（tid 是执行哈希），只能靠插桩建立。
# 按 rid 分桶（同 CANCEL_EVENTS 键控姿势）：run 随便并发，一个 run 结束只回收自己的桶，
# 不清掉正在并发执行的其他 run 的映射。
_SUBAGENT_REGISTRY: dict[str, dict[str, str]] = {}


def register_subagent(rid: str, ns: str, tool_call_id: str) -> None:
    _SUBAGENT_REGISTRY.setdefault(rid, {})[ns] = tool_call_id


def clear_subagent_registry(rid: str) -> None:
    """该 run 结束时回收自己的桶（tid 虽唯一，干净回收防累积；并发 run 互不影响）。"""
    _SUBAGENT_REGISTRY.pop(rid, None)


def _chunk_text(msg: AIMessageChunk) -> str:
    """从 AIMessageChunk 提取增量文本（content 可能是 str 或内容块列表）。"""
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c
    parts: list[str] = []
    for b in c:
        if isinstance(b, str):
            parts.append(b)
        elif isinstance(b, dict):
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", "") or "")
    return "".join(parts)


def _chunk_reasoning(msg: AIMessageChunk) -> str:
    """从 AIMessageChunk 提取增量推理文本（DeepSeek 的 reasoning_content）。

    ChatDeepSeek 把推理增量放 additional_kwargs["reasoning_content"]（str 或内容块列表）。
    """
    raw = (getattr(msg, "additional_kwargs", None) or {}).get("reasoning_content")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    if isinstance(raw, list):
        for b in raw:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") in ("text", "reasoning_text"):
                parts.append(b.get("text", "") or "")
    return "".join(parts)


def _deep_unescape(value):
    """递归反转义 HTML 实体与字面转义序列（仅展示层）。

    个别模型会把参数里的换行写错编码：早期是 `&#10;` 实体；实测还有字面
    `\\n`（工具调用 JSON 里过度转义 `\\\\n` 的解码产物，落到字符串是反斜杠
    +n 两个字符）——问答卡原样上屏、首行/副标题分段失效。html.unescape 单遍
    解码（`&amp;#10;` 只解到 `&#10;`、不会二次展开），字面 `\\n` 再折叠为
    真实换行；其余转义序列（\\t 等）罕见、不折叠，避免误伤合法反斜杠文本。
    这里只作用于下发 UI 的 args 副本，工具实际执行与模型记忆（checkpoint）
    仍用模型原始输出。
    """
    if isinstance(value, str):
        return html.unescape(value).replace("\\n", "\n")
    if isinstance(value, dict):
        return {k: _deep_unescape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_unescape(v) for v in value]
    return value


def _tool_args(args) -> dict:
    if isinstance(args, dict):
        return _deep_unescape(args)
    if isinstance(args, str):
        try:
            return _deep_unescape(json.loads(args))
        except Exception:
            return {"raw": _deep_unescape(args)}
    return {"raw": _deep_unescape(str(args))}


# ask_human 参数泄漏行（2026-09-10 两轮实测）：deepseek-v4-flash 偶发把可选参数写成
# `options="A；B"` / `guide_path="body/写作指引.md"` 赋值行塞进 question 正文、参数
# 本身留空——前端候选项/「打开」按钮只读 args 字段，空则按钮整体不渲染、伪代码行
# 原样上屏。白名单只收已观测的两个参数；multiple（布尔、短值）未观测不收。
_SALVAGE_LINE = re.compile(r"^\s*(options|guide_path)\s*[=:：]\s*(.+?)\s*$")
_SALVAGE_QUOTES = "\"'“”‘’「」"


def _salvage_ask_human_args(args: dict) -> dict:
    """ask_human 参数泄漏自愈：question 里的赋值行摘回对应参数（仅展示层副本）。

    与 _deep_unescape 同边界：只改下发 UI 的 args 副本，工具实际执行与模型记忆
    （checkpoint）仍用模型原始输出。参数已有值时不碰（两处信息冲突无从裁决，
    保留原文诚实呈现）；命中的行从 question 删除。options 按候选项规则（；/;
    分隔、逐项剥引号）重组，guide_path 只剥外层引号。
    """
    question = args.get("question")
    if not isinstance(question, str) or not question:
        return args
    out = dict(args)
    kept: list[str] = []
    salvaged: list[str] = []
    for line in question.split("\n"):
        m = _SALVAGE_LINE.match(line)
        key = m.group(1) if m else None
        if key and not str(out.get(key) or "").strip():
            value = m.group(2).strip().strip(_SALVAGE_QUOTES)
            if key == "options":
                items = [s.strip(_SALVAGE_QUOTES) for s in re.split(r"[；;]", value) if s.strip()]
                value = "；".join(items)
            if value:
                out[key] = value
                salvaged.append(key)
                continue
        kept.append(line)
    if not salvaged:
        return args
    out["question"] = "\n".join(kept).rstrip()
    logger.warning("ask_human 参数泄漏自愈：question 内 %s 赋值行已摘回参数", "/".join(salvaged))
    return out


def normalize_hitl_requests(requests) -> list:
    """读侧兜底：落库的 interrupt requests 逐条过 ask_human 参数自愈。

    修复上线前已等待中的 run，其 runs.interrupt 快照仍是泄漏形态；run.state
    对账与 runs/latest 读出时过同一遍纠正，客户端重连/刷新后提问卡自愈
    （写侧 _hitl_requests 只保住此后新中断的 run）。
    """
    if not isinstance(requests, list):
        return requests
    for req in requests:
        if (
            isinstance(req, dict)
            and req.get("tool") == "ask_human"
            and isinstance(req.get("args"), dict)
        ):
            req["args"] = _salvage_ask_human_args(req["args"])
    return requests


def _summary(content, limit: int = 4000) -> str:
    """tool 结果摘要：展开详情要能读到完整输出，上限放宽到 4000 字符；
    超限时明示截断与完整长度（静默「…」会让用户以为内容残缺）。"""
    s = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n……（已截断，完整输出共 {len(s)} 字符）"


_HITL_TEMPLATE_PREFIX = "Tool execution requires approval"


def _friendly_description(name: str, args: dict) -> str:
    """审批卡 description 人话化。

    langchain HITL 中间件的默认 description 是英文模板 + 完整 args repr
    （"Tool execution requires approval\\nTool: …\\nArgs: {…}"），整段铺在卡片里
    普通用户无法据此判断在批什么；重写为一句话摘要，完整参数仍随 args 下发
    （前端「查看参数」折叠可见，信息零丢失）。
    """
    if name == "task":
        label = "派出子代理"
        subagent_type = args.get("subagent_type")
        if subagent_type:
            label += f"（{subagent_type}）"
        raw = args.get("description")
        first = ""
        if isinstance(raw, str) and raw.strip():
            sentence = raw.strip().splitlines()[0]
            for sep in ("。", "；", ";", "."):
                idx = sentence.find(sep)
                if idx != -1:
                    sentence = sentence[: idx + 1]
                    break
            first = sentence.strip()
            if len(first) > 80:
                first = first[:80] + "…"
        return f"{label}：{first}" if first else f"{label}，需要你的批准"
    return f"执行工具 {name}，需要你的批准"


def _hitl_requests(interrupts) -> dict:
    """把 langgraph Interrupt 元组归一化 {requests: [{tool, args, description, allowed, interrupt_id}]}。

    遍历**全部** Interrupt（同一轮多个 ask_human 会各产生一个，只取第一个会让
    第二个悬空——resume 时 langgraph 报「must specify the interrupt id」把 run
    打死，2026-09-06 实测）；单个 Interrupt 的 batch 模式下多个 tool call 仍合并在
    同一 value.action_requests。每条 request 附 interrupt_id（resume 按 id 分组映射
    恢复；旧快照无此字段）。allowed 取 review_configs 的 allowed_decisions，前端
    据此分支渲染审批卡/问答卡。
    """
    items = interrupts if isinstance(interrupts, (tuple, list)) else (interrupts,)
    requests = []
    for it in items:
        value = getattr(it, "value", None) or {}
        iid = getattr(it, "id", "") or ""
        allowed_by_tool: dict[str, list[str]] = {}
        for rc in value.get("review_configs", []):
            if isinstance(rc, dict) and rc.get("action_name"):
                allowed_by_tool[rc["action_name"]] = list(rc.get("allowed_decisions") or [])
        for ar in value.get("action_requests", []):
            if not isinstance(ar, dict):
                continue
            name = ar.get("name") or "unknown"
            args = _tool_args(ar.get("args"))
            if name == "ask_human":
                args = _salvage_ask_human_args(args)
            desc = ar.get("description") or ""
            if desc.startswith(_HITL_TEMPLATE_PREFIX):
                desc = _friendly_description(name, args)
            requests.append(
                {
                    "tool": name,
                    "args": args,
                    "description": desc,
                    "allowed": allowed_by_tool.get(name) or ["approve", "reject"],
                    "interrupt_id": iid,
                }
            )
    return {"requests": requests}


def iter_stream(stream: Iterator, rid: str | None = None) -> Iterator[tuple[str, object]]:
    """把 agent.stream(stream_mode=["messages","updates"], subgraphs=True) 的产出映射为归一化事件。

    subgraphs=True 时每项为 (ns, mode, payload) 三元组：主图 ns=()，子代理内部
    ns=("tools:<tid>",)（孙代理长度 2，数据结构天然兼容）。兼容未开 subgraphs 的
    (mode, payload) 二元组（此时没有子代理事件）。rid 用于子代理归属注册表按 run 查桶。

    yield: ("token", text) | ("reasoning", {"text", "agent_id"}) | ("tool_called", {...})
           | ("tool_result", {...}) | ("todo_updated", todos) | ("interrupt", {"requests": [...]})
    """
    last_todos_key: str | None = None
    for item in stream:
        if isinstance(item, tuple) and len(item) == 3 and isinstance(item[0], tuple):
            ns, mode, chunk = item
        elif isinstance(item, tuple) and len(item) == 2:
            ns, mode, chunk = (), item[0], item[1]
        else:
            continue
        sub_ns = ns[0] if ns else None
        # 子代理内部事件归属：ns 第 0 段查本 run 的注册桶得所属 task 的 tool_call_id
        agent_id = _SUBAGENT_REGISTRY.get(rid or "", {}).get(sub_ns) if sub_ns else None

        if mode == "messages":
            msg, _meta = chunk if isinstance(chunk, tuple) else (chunk, None)
            if isinstance(msg, AIMessageChunk):
                reason = _chunk_reasoning(msg)
                if reason:
                    yield ("reasoning", {"text": reason, "agent_id": agent_id})
                if not sub_ns:
                    # 子代理正文 token 不透传：与 task 的 tool.result（最终报告）重复
                    text = _chunk_text(msg)
                    if text:
                        yield ("token", text)
        elif mode == "updates":
            if not isinstance(chunk, dict):
                continue
            # HITL 中断：langgraph 在 updates 模式以 {"__interrupt__": (Interrupt,...)} 下发
            # （值是元组，不是节点 update；不专门处理会被静默丢弃）。value 即
            # HumanInTheLoopMiddleware 的 HITLRequest；归一化为前端契约的 requests 形状。
            pending = chunk.get("__interrupt__")
            if pending:
                yield ("interrupt", _hitl_requests(pending))
                continue
            for _node, update in chunk.items():
                if isinstance(update, dict):
                    # todos 由 TodoListMiddleware 的 write_todos 写入主图 state；
                    # 子代理 state 排除 todos 键，限定主图处理是双保险。
                    # 每次调用整体替换列表，去重后只在内容变化时发事件
                    todos = update.get("todos")
                    if todos is not None and not sub_ns:
                        key = json.dumps(todos, sort_keys=True, ensure_ascii=False)
                        if key != last_todos_key:
                            last_todos_key = key
                            yield ("todo_updated", todos)
                    # 消息→工具事件的翻译只认真实执行节点（见 _TOOL_EVENT_NODES 注释）；
                    # 中间件伪节点的 messages 是历史重写，跳过
                    if _node not in _TOOL_EVENT_NODES:
                        continue
                    messages = update.get("messages", [])
                    for m in messages:
                        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                            for tc in m.tool_calls:
                                yield (
                                    "tool_called",
                                    {
                                        "tool": tc.get("name", "unknown"),
                                        "args": _tool_args(tc.get("args")),
                                        "tool_call_id": tc.get("id"),
                                        "agent_id": agent_id,
                                    },
                                )
                        elif isinstance(m, ToolMessage):
                            content = getattr(m, "content", "")
                            status = getattr(m, "status", None)
                            error = None
                            if status == "error":
                                # task 抛出异常时 ToolMessage.content 是错误文本；作为 tool_result 的
                                # error 字段下发，让前端渲染「✗ 失败工具卡」并可展开查看详情
                                error = _summary(content, limit=800)
                            yield (
                                "tool_result",
                                {
                                    "tool": getattr(m, "name", None) or "unknown",
                                    "summary": _summary(content),
                                    "error": error,
                                    "tool_call_id": getattr(m, "tool_call_id", None),
                                    "agent_id": agent_id,
                                },
                            )
