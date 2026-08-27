"""DeepAgents 封装：build_agent / run_stream。

build_agent 按 PRD §5.6 已验证代码构造；run_stream 在 asyncio.to_thread 中驱动
agent.stream(stream_mode=["messages","updates"])，把 iter_stream 归一化的事件发布到 bus，
并在结束/出错时把最终消息落库 app.db、更新 runs 状态。

任务层（P4）：run 启动解析会话所属任务写入 runctx；_TaskContextMiddleware 在
每次模型调用时注入任务上下文（任务名/进度便签/产物清单——现算、不落 checkpoint）。
"""

import asyncio
import dataclasses
import itertools
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.messages import SystemMessage
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import artifact_store
from . import config as cfg
from . import db
from . import events
from . import runctx
from .bus import publish
from .tools import TOOLS

logger = logging.getLogger(__name__)

# HITL：这些工具的调用先 interrupt 暂停、等用户裁决后 resume。ask_human 只允许
# respond（回答代替执行）；task = 子代理派发审批（并发子代理是重操作，派发前用户
# 确认——AI 新闻调研等技能的执行门禁，不需要时删除该行）。
INTERRUPT_ON: dict = {
    "ask_human": {"allowed_decisions": ["respond"]},
    "task": {"allowed_decisions": ["approve", "reject"]},
}

# 显式注册的子代理（deepagents 还会自动补 general-purpose）。tools 不指定 → 继承主
# agent 全部工具；interrupt_on={} 整体替换继承：子代理不直接向用户提问（问答统一由
# 主 agent 发起，需裁决项由子代理记 ⚠待澄清带回）。
SUBAGENTS: list[dict] = [
    {
        # 调研子代理：UI 卡片显示 subagent_type 标签、专属提示词含降级规则
        # （ai-news-research 技能的执行单元）。
        "name": "news-researcher",
        "description": (
            "联网调研指定 AI 厂商最新新闻，输出结构化中文摘要"
            "（ai-news-research 技能的执行单元）"
        ),
        "system_prompt": (
            "你是新闻调研子代理。用 fetch_url 抓取任务描述里给出的新闻源页面（仅 https），"
            "从页面内容提炼 3-5 条最新动态，每条包含：日期、标题、一句话摘要、来源 URL。"
            "页面内容不足时可以再抓页面里指向的子页面（最多补抓 2 个）。"
            "抓取失败或内容不可用时，基于你已有的知识输出近期动态，"
            "并明确注明「未能联网核实，基于模型知识」。"
            "只调研任务描述指定的公司，输出中文，直接给出清单，不要寒暄。"
        ),
        "interrupt_on": {},
    },
    {
        # 投标目录编写子代理：单册 R2 初稿 + 三道清理的执行单元（tender-outline 多册并发）。
        # 注意：任务目录前缀经 _TaskContextMiddleware 只注入主 agent，不会出现在子代理的
        # 模型调用里——派发 description 必须自带全部路径（SKILL.md 第 2 步有清单）。
        "name": "tender-outline-writer",
        "description": (
            "为单个响应文件生成投标目录（R2 初稿+三道清理），输出 fragment"
            "（tender-outline 技能多册并发时的执行单元）"
        ),
        "system_prompt": (
            "你是投标目录编写子代理，只负责一个响应文件的目录初稿与清理。"
            "任务描述会给出：任务目录前缀（读写路径都必须带该前缀）、响应文件名、scope、"
            "fragment 输出路径、out/analysis 各输入文件的完整路径。\n"
            "开工前先依次 read_file：skills/tender-outline/references/generate.md、"
            "annotation.md、revise-gapfill.md、revise-scoring.md、revise-walkthrough.md，"
            "严格按其规则执行：R2 补全三段（## 目录 / ## 来源标注 / ## 目录说明）"
            "→ 三道清理（输入缺失的道跳过并在摘要里声明）。回招标原文核实时同样遵守"
            "导航纪律：读 out/parse/<文件名>/<文件名>.outline.json 按行号取区段，禁止整读全文。\n"
            "产物写到指定的 fragment 路径：单个 `# 响应文件：<名>` 标题 + scope 段 + 三段，"
            "遵守树格式红线（- 开头 / 无编号 / 每级 2 空格缩进 / 独立附件平级 / 不用代码块），"
            "全文严禁用代码块包裹。\n"
            "禁止调用 ask_human（无人应答）：需要用户裁决的记「⚠待澄清：…」进目录说明。\n"
            "完成后返回简短中文摘要：目录节点数、来源标注数、跳过的清理道及原因、待澄清项。"
        ),
        "interrupt_on": {},
    },
]

_agent = None
_agent_lock = asyncio.Lock()
_saver_conn = None  # 持久 sqlite 连接（进程存活期只开一条、永不关闭）
_saver = None
_saver_init_lock = threading.Lock()  # API 线程 delete_thread 与 build_agent 并发首建 saver 的护栏


def _get_saver():
    global _saver_conn, _saver
    if _saver is None:
        with _saver_init_lock:
            if _saver is None:
                _saver_conn = sqlite3.connect(str(cfg.agent_db_path()), check_same_thread=False)
                # langgraph-checkpoint-sqlite 3.x：from_conn_string 是上下文管理器（会随 with 关闭连接）。
                # sidecar 常驻进程需要连接全程存活，故自持连接、直接构造 SqliteSaver（内部自带线程锁）。
                _saver = SqliteSaver(_saver_conn)
    return _saver


class _SubagentTagMiddleware(AgentMiddleware):
    """task 工具插桩：tools 任务 ns → tool_call_id 登记到 events 的子代理注册表。

    执行 task 工具时正处于父图 tools 任务内，runtime.config 的
    configurable["checkpoint_ns"]（"tools:<tid>"）恰为该子代理所有内部事件的
    ns 第 0 段；登记先于子代理启动，消费端（iter_stream）据此精确归属并发子代理。
    """

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        if call.get("name") != "task":
            return handler(request)
        cfg = getattr(request.runtime, "config", None) or {}
        ns = (cfg.get("configurable") or {}).get("checkpoint_ns") or ""
        call_id = call.get("id") or ""
        if ns and call_id:
            # rid 经 runctx 取（contextvars 已随 ToolNode 线程传播）：登记进本 run 的桶
            ctx = runctx.current_run()
            if ctx is not None:
                events.register_subagent(ctx.run_id, ns, call_id)
        return handler(request)


def _artifact_listing(rows: list[dict]) -> list[str]:
    return [
        f"- {r['display_name']}（{r['kind']}/{r['schema_id']}@{r['schema_version']}，{r['artifact_id']}）"
        for r in rows
        if artifact_store.package_ready(r["artifact_id"], r)
    ]


def _task_context_block(task_id: str, conversation_id: str) -> str:
    """拼装任务上下文注入块：任务名 + 进度便签 + 两层产物清单（仅名称与 id）。

    共享的是文件夹和结论，不是聊天记录（设计文档 §8.2）：模型要具体内容时
    经 read_artifact 按需读取。每次模型调用现算——run 中途发布/转正的成果
    下一次调用即可见。
    """
    task = db.get_task(task_id)
    if not task:
        return ""
    lines = [
        f"## 当前任务：{task['title']}（本会话属于该任务，产物分两层）",
        # §16 任务分组目录：模型引用文件/产物的路径前缀（files/ 上传区、out/ 工作台、drafts/ 草稿区）
        f"任务工作目录：`{task_id}/`（用户上传的文件在其 files/ 下，解析与分析产物在 out/ 下，"
        "发布草稿写 drafts/；引用这些路径时带上该前缀）",
        # 模型不知道当前时间，写产物头部等时间戳时会编造（如零点占位）——每次调用现给
        f"当前时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
        "（写时间戳时用它，不要自己估）",
    ]
    note = (task.get("progress_note") or "").strip()
    if note:
        lines.append(f"### 任务进度便签\n{note}")
    formal = _artifact_listing(db.list_artifact_index(task_id=task_id))
    if formal:
        lines.append("### 任务正式稿（用户确认过的权威成果）\n" + "\n".join(formal))
    drafts = _artifact_listing(db.list_artifact_index(conversation_id=conversation_id))
    if drafts:
        lines.append("### 本会话过程稿（草稿层）\n" + "\n".join(drafts))
    return "\n".join(lines)


class _TaskContextMiddleware(AgentMiddleware):
    """每次模型调用前把任务上下文块追加到 system message（不落 checkpoint）。

    与工具同处 worker 线程的同一份 context 拷贝，经 runctx 按当前 run 解析任务；
    不在任务会话中（无 task_id）时不注入。
    """

    def wrap_model_call(self, request, handler):
        ctx = runctx.current_run()
        if ctx is None or not ctx.task_id:
            return handler(request)
        block = _task_context_block(ctx.task_id, ctx.conversation_id)
        if not block:
            return handler(request)
        base = request.system_message.content if request.system_message is not None else ""
        request = dataclasses.replace(
            request, system_message=SystemMessage(content=f"{base}\n\n{block}" if base else block)
        )
        return handler(request)


def build_agent():
    """构造（或重建）DeepAgents 实例。settings 变更后调用 rebuild_agent()。"""
    api_key = cfg.llm_api_key()
    if not api_key:
        raise RuntimeError("LLM_API_KEY 未设置（sidecar 只能通过环境变量拿到 key）")

    # ChatDeepSeek 会提取 DeepSeek 的 reasoning_content 到 additional_kwargs，
    # events._chunk_reasoning 据此发 agent.reasoning（非推理模型下与 ChatOpenAI 行为一致）。
    model = ChatDeepSeek(
        api_key=api_key,
        base_url=cfg.llm_base_url(),
        model=cfg.llm_model(),
        timeout=180,
    )

    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(cfg.workspace_dir())),
        tools=TOOLS,
        subagents=SUBAGENTS,
        skills=["skills/"],  # 未加载时在 main 启动日志提示换写法（见 README）
        # 子代理归属插桩；todos 工具；任务上下文按 run 注入
        middleware=[_SubagentTagMiddleware(), TodoListMiddleware(), _TaskContextMiddleware()],
        system_prompt=(
            "你是标书助理，在一个投标任务下的会话里工作。任务产物分两层："
            "任务「正式稿」（用户确认过的权威成果）与本会话「过程稿」（草稿层）。"
            "你的发布一律进入本会话过程稿；希望成果进入正式稿时置 propose_promotion"
            "（建议转正），用户确认后才生效——不要假装已写入正式稿。"
            "方法论在 skills 目录中，按各技能的 SKILL.md 执行："
            "解析招标文件（文件→Markdown、确认来源集合）用 document-parse 技能"
            "（确认主文件与补充角色→parse_document→解析概况经用户确认）；"
            "分析招标文件、提取要点用 tender-analysis 技能（前提是 document-parse 已完成，"
            "读 outline 按行号取区段，禁止整读全文）；"
            "要点齐后生成投标目录用 tender-outline 技能（R1 确认点→初稿→三道清理→"
            "assemble_tender 组装发布并提醒转正；多响应文件时并发派发"
            " tender-outline-writer 子代理每册一个，主线程只派发与汇总）；"
            "调研 AI 厂商新闻用 ai-news-research 技能（并发派 3 个 news-researcher 子代理后汇总）。"
            "用户上传的文件在当前任务工作目录的 files/ 下（任务目录前缀见任务上下文，"
            "如 <任务目录>/files/招标文件.docx）。"
            "引用结构化成果（如投标目录）时用 read_artifact 按契约读取当前内容（正式稿优先），"
                "不要猜文件路径；中途想保存的未登记内容以 doc.note 笔记保存。"
                "完成阶段性工作后用 update_task_progress 更新任务进度便签（保持简短）。"
                "输出纪律：调用工具的那一轮，正文只写一句以内的当前动作说明"
                "（如「读取评分办法」），面向用户说清要做什么，不复述工具用法、"
                "输出格式等内部规则，也不展开计划、不罗列备选方案；"
                "完整的进展与结论只在最终回复（不再调用工具的那一轮）给出。"
                "缺少关键信息（如资质材料、报价策略）或遇到需要用户拍板的取舍时，"
                "用 ask_human 向用户提问，不要自行猜测；可以明确推断的小事不要问。"
                "需要用户在候选项里挑选时，把选项放进 options（「；」分隔）并按是否"
                "允许多选设置 multiple，用户点选与补充文字会一并作为回答回传。"
        ),
        checkpointer=_get_saver(),
        interrupt_on=INTERRUPT_ON,
    )
    return agent


async def get_agent():
    global _agent
    if _agent is None:
        async with _agent_lock:
            if _agent is None:
                _agent = await asyncio.to_thread(build_agent)
    return _agent


async def rebuild_agent():
    """PUT /api/settings 后重建 agent 实例（base_url/model 立即生效）。"""
    global _agent
    async with _agent_lock:
        _agent = await asyncio.to_thread(build_agent)


def delete_thread_memory(cid: str) -> None:
    """删会话时连带清理 agent.db 里该 thread 的 checkpoint（409 已保证此刻无并发 run）。

    不清理会让已删会话在 agent.db 里留幽灵记忆（隐私/空间泄漏）。清理失败不阻断
    删除：app.db 行已删，残留只是回到旧行为，且下次对账不会再重建（messages 没了）。
    """
    try:
        _get_saver().delete_thread(cid)
    except Exception:
        logger.exception("清理 thread checkpoint 失败：%s", cid)


async def recover_agent_memory() -> int:
    """启动对账：app.db 有消息但 agent.db 该 thread 无 checkpoint 的会话，用 messages
    历史重建记忆（agent.db 丢失/损坏/被删时兜底，checkpoint 仍是记忆真值）。

    重建的是纯文本对（无工具调用细节），好于整段失忆；重建后此会话后续 run 正常续接。
    未配置 LLM_API_KEY 时跳过（sidecar 允许无 key 启动）。返回重建的会话数。
    """
    try:
        agent = await get_agent()
    except RuntimeError as e:
        logger.warning("agent 记忆对账跳过（%s）", e)
        return 0
    rebuilt = 0
    for conv in db.list_conversations():
        history = db.load_recent_history(conv["id"], limit=1000)
        if not history:
            continue
        cfg = {"configurable": {"thread_id": conv["id"]}}
        try:
            msgs = (agent.get_state(cfg).values or {}).get("messages") or []
            if msgs:
                continue  # checkpoint 健在，不动
            agent.update_state(cfg, {"messages": [(m["role"], m["content"]) for m in history]})
        except sqlite3.DatabaseError:
            # agent.db 文件损坏（本函数的兜底使命恰恰包含它）：不能让异常打崩 lifespan
            # 导致 sidecar 起不来。记日志跳过——checkpoint 仍坏，首次对话会报错，
            # 用户删掉 agent.db 重启后可由本函数用 messages 重建。
            logger.exception("agent.db 读取失败（疑似损坏），记忆对账中止；删除 agent.db 后重启可重建")
            return rebuilt
        rebuilt += 1
    if rebuilt:
        logger.warning("记忆对账：%d 个会话的 checkpoint 缺失，已用 messages 历史重建", rebuilt)
    return rebuilt


def _new_trace_step(payload: dict) -> dict:
    # id 用 tool_call_id（唯一）；缺省退化到工具名+毫秒时间戳，保证前端列表 key 稳定
    tcid = payload.get("tool_call_id")
    return {
        "id": tcid or f"{payload.get('tool') or 'step'}@{int(time.time() * 1000)}",
        "tool": payload.get("tool") or "unknown",
        "args": payload.get("args") or {},
        "status": "running",
        "summary": "",
        "error": None,
        "tool_call_id": payload.get("tool_call_id"),
        "reasoning": "",
        # 本步骤开始前模型输出的旁白段（narration）：主 agent 调用才有，见 _run_agent_stream 封段
        "text": "",
        "children": [],
        # 计时（ms epoch，键名与前端 ToolStep 一致）
        "startedAt": int(time.time() * 1000),
        "endedAt": None,
    }


def _find_task_step(steps: list[dict], agent_id: str) -> dict | None:
    """按 agent_id（= task 的 tool_call_id）找所属子代理步骤。"""
    for s in steps:
        if s["tool"] == "task" and s.get("tool_call_id") == agent_id:
            return s
    return None


def _attach_step(top_steps: list[dict], step: dict, agent_id: str | None) -> None:
    """子代理的工具步骤挂到对应 task 的 children，主图挂顶层。"""
    if agent_id:
        parent = _find_task_step(top_steps, agent_id)
        if parent is not None:
            parent["children"].append(step)
            return
    top_steps.append(step)


def _find_pending(steps: list[dict], payload: dict) -> dict | None:
    """在步骤树里按 tool_call_id（缺省退化按工具名）找 running 的待回填步骤。"""
    for s in reversed(steps):
        if s["status"] == "running":
            tcid = payload.get("tool_call_id")
            if tcid and s.get("tool_call_id") == tcid:
                return s
            if not tcid and s["tool"] == payload["tool"]:
                return s
        hit = _find_pending(s["children"], payload)
        if hit is not None:
            return hit
    return None


def _run_agent_stream(
    agent, cid: str, rid: str, task_id: str | None, _publish, user_text: str | None, resume_decisions: list | None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, str | None, dict, dict | None]:
    """worker 线程里跑完整流，逐块实时回调 _publish(event, data)。

    首段（user_text）与续段（resume_decisions，Command(resume=...) 从 checkpoint
    的 interrupt 处续跑）共用本函数。返回 (assistant_text, error, trace, interrupt)：
    assistant_text 是**最终回复**（最后一段未被 tool.called 跟随的正文）；此前各轮的
    正文旁白在 tool_called 到达时封段挂到对应 trace 步骤的 text 字段（过程/结果分通道，
    前端 useRun 用同一条封段规则，SSE 契约零改动）。
    interrupt 非空 = HITL 暂停（events 归一化的 {"requests": [...]}），本段流到此
    结束、run 转入 waiting_input，等用户裁决后由 run_stream 再开一段续流。
    trace 是本次 run 的执行过程快照：顶层工具步骤树（task 步骤含子代理 children
    与 reasoning）+ 最新 todos + 主 agent 思考流整段（reasoning 键，随 run_traces
    落库供历史「深度思考」渲染），run 结束时由 run_stream 落库 run_traces。

    cancel_event 非空且被置位 = 用户请求停止：在每个流事件边界协作式退出
    （LLM 流式调用期间 token 事件持续到达，停止会在下一个事件处生效；
    长工具执行中则等待工具返回），退出走 error 路径（半截回复落库 + run 标 error）。
    """
    # run 上下文随 context 拷贝进入本线程：工具据此记录产物来源与作用域，
    # _TaskContextMiddleware 据此注入任务上下文（同线程同一份 context）
    runctx.set_run(cid, rid, task_id)
    if resume_decisions is not None:
        stream_input: object = Command(resume={"decisions": resume_decisions})
    else:
        stream_input = {"messages": [("user", user_text or "")]}
    stream = agent.stream(
        stream_input,
        config={"configurable": {"thread_id": cid}},
        stream_mode=["messages", "updates"],
        subgraphs=True,  # 子代理内部事件浮现父流；events.iter_stream 按 ns 归属
    )
    # 正文按轮次分段：cur_text_parts 是当前未封口段；主 agent 的 tool_called 到达即
    # 封口为旁白（挂该步骤 text），run 结束时最后未封口段 = 最终回复。
    cur_text_parts: list[str] = []
    # 主 agent 思考流整段累积（DeepSeek reasoning_content）：不按步封段（跨多轮、
    # 与工具步骤归属不清晰），run 结束随 trace 落 run_traces.reasoning——历史会话
    # 的「深度思考」折叠区数据源。子代理 reasoning 另走 task_step["reasoning"]。
    cur_reasoning: list[str] = []
    error = None
    top_steps: list[dict] = []
    last_todos: list = []
    interrupt: dict | None = None
    try:
        for kind, payload in events.iter_stream(stream, rid):
            if cancel_event is not None and cancel_event.is_set():
                error = events.CANCELLED_MESSAGE
                break
            if kind == "reasoning":
                # DeepSeek 推理模型的 chain-of-thought 增量；agent_id 非空时归属子代理
                _publish(
                    events.EVENT_REASONING,
                    {
                        "run_id": rid,
                        "conversation_id": cid,
                        "text": payload["text"],
                        "agent_id": payload.get("agent_id"),
                    },
                )
                if payload.get("agent_id"):
                    task_step = _find_task_step(top_steps, payload["agent_id"])
                    if task_step is not None:
                        task_step["reasoning"] += payload["text"]
                else:
                    cur_reasoning.append(payload["text"])
            elif kind == "token":
                cur_text_parts.append(payload)  # type: ignore[arg-type]
                _publish(
                    events.EVENT_TOKEN,
                    {"run_id": rid, "conversation_id": cid, "text": payload},
                )
            elif kind == "tool_called":
                _publish(
                    events.EVENT_TOOL_CALLED,
                    {
                        "run_id": rid,
                        "conversation_id": cid,
                        "tool": payload["tool"],
                        "args": payload["args"],
                        "tool_call_id": payload.get("tool_call_id"),
                        # agent_id 非空 = 子代理内部工具调用（归属对应 task）
                        "agent_id": payload.get("agent_id"),
                    },
                )
                step = _new_trace_step(payload)
                if not payload.get("agent_id"):
                    # 主 agent 调用：把之前流出的正文封为旁白挂到本步骤（同轮连发的
                    # 后续调用 text 为空串）；子代理调用不封段（其正文 token 不透传）
                    step["text"] = "".join(cur_text_parts)
                    cur_text_parts.clear()
                _attach_step(top_steps, step, payload.get("agent_id"))
            elif kind == "tool_result":
                _publish(
                    events.EVENT_TOOL_RESULT,
                    {
                        "run_id": rid,
                        "conversation_id": cid,
                        "tool": payload["tool"],
                        "summary": payload["summary"],
                        # 失败工具必须透传 error（前端据 data.error 渲染失败卡），成功时为 null
                        "error": payload.get("error"),
                        "tool_call_id": payload.get("tool_call_id"),
                        "agent_id": payload.get("agent_id"),
                    },
                )
                step = _find_pending(top_steps, payload)
                if step is not None:
                    step["status"] = "error" if payload.get("error") else "done"
                    step["summary"] = payload["summary"]
                    step["error"] = payload.get("error")
                    step["endedAt"] = int(time.time() * 1000)
            elif kind == "todo_updated":
                todos = payload  # type: ignore[arg-type]
                last_todos = todos  # type: ignore[assignment]
                done = sum(1 for t in todos if t.get("status") == "completed")
                _publish(
                    events.EVENT_TODO_UPDATED,
                    {
                        "run_id": rid,
                        "conversation_id": cid,
                        "done": done,
                        "total": len(todos),
                        "items": [
                            {"content": t.get("content", ""), "status": t.get("status", "pending")}
                            for t in todos
                        ],
                    },
                )
            elif kind == "interrupt":
                # HITL 暂停：流到此为止，run_stream 落半截消息并转 waiting_input
                interrupt = payload
                break
    except Exception as e:  # 网络/API 错误等
        logger.exception("agent stream failed")
        error = str(e)
    finally:
        runctx.clear_run()
        events.clear_subagent_registry(rid)
    # 最终回复 = 最后未封口段（未被 tool.called 跟随）；旁白已挂在 trace 步骤 text 上
    return (
        "".join(cur_text_parts),
        error,
        {"tools": top_steps, "todos": last_todos, "reasoning": "".join(cur_reasoning)},
        interrupt,
    )


def _last_narration(tools: list[dict]) -> str:
    """倒序找最后一个非空旁白段：interrupt/error 半截落库在最终回复为空时的兜底文案
    （被门禁拦下/中断的那轮若只有旁白没有正文，至少让用户看到 AI 说到哪了）。"""
    for step in reversed(tools):
        if step.get("text"):
            return step["text"]
    return ""


def _freeze_paused_steps(steps: list[dict]) -> list[dict]:
    """中断边界落 trace 前把 running 步骤改标 paused（含子代理 children）。

    被审批门禁拦下的调用此刻并未执行（真正执行发生在续跑段，步骤树另起一份），
    历史快照里的「执行中」会永远转圈、与续跑段的同名步骤形成"冻结+活跑"双卡，
    观感像开了新一轮——改为「已暂停」终态，如实反映该段落在等待确认时被快照。
    """
    now = int(time.time() * 1000)

    def walk(step: dict) -> dict:
        children = [walk(c) for c in step.get("children", [])]
        if children != step.get("children"):
            step = {**step, "children": children}
        if step["status"] == "running":
            step = {**step, "status": "paused", "endedAt": step.get("endedAt") or now}
        return step

    return [walk(s) for s in steps]


# 活跃 run 的协作式取消事件（rid → Event）：POST /runs/{rid}/cancel 置位，
# worker 线程在下一个流事件边界退出（见 _run_agent_stream）
CANCEL_EVENTS: dict[str, threading.Event] = {}


def request_cancel(rid: str) -> bool:
    """置位取消事件。返回 False = 该 run 不在本进程活跃执行（已结束/不存在）。"""
    event = CANCEL_EVENTS.get(rid)
    if event is None:
        return False
    event.set()
    return True


def is_cancel_pending(rid: str) -> bool:
    """run 是否已请求停止但尚未收尾（协作式取消的事件边界等待中）。"""
    event = CANCEL_EVENTS.get(rid)
    return event is not None and event.is_set()


async def run_stream(
    cid: str,
    rid: str,
    user_text: str | None = None,
    resume_decisions: list | None = None,
    start_seq: int = 0,
) -> None:
    """后台任务：驱动一段 agent 流式执行并实时发布 §5.5 事件。

    首段传 user_text；HITL 续段传 resume_decisions（同一 run 从 interrupt 处续跑，
    start_seq 接上一段的事件序号——前端按 run_id 去重，重置会吞掉续段事件）。
    """
    # 用户请求停止（POST /runs/{rid}/cancel）：注册协作式取消事件，run 结束时摘除
    cancel_event = threading.Event()
    CANCEL_EVENTS[rid] = cancel_event
    try:
        # per-run 事件序列号（契约 additive 扩展）：所有流事件 data 带 seq（1 起单调递增），
        # 客户端据此去重（双连接重影防线）与检测缺口。ping/run.state（对账）不带。
        # started → worker（串行逐事件）→ completed 的时序保证计数无并发，锁是保险。
        seq_counter = itertools.count(start_seq + 1)
        seq_lock = threading.Lock()

        def next_seq() -> int:
            with seq_lock:
                return next(seq_counter)

        await publish(
            cid,
            {"event": events.EVENT_STARTED, "data": {"run_id": rid, "conversation_id": cid, "seq": next_seq()}},
        )
        agent = await get_agent()
        loop = asyncio.get_running_loop()

        # worker 线程里逐块发布：把协程调度回事件循环（queue.put_nowait 即时返回）
        def _publish(event: str, data: dict) -> None:
            payload = {**data, "seq": next_seq()}
            fut = asyncio.run_coroutine_threadsafe(publish(cid, {"event": event, "data": payload}), loop)
            fut.result()

        t0 = time.monotonic()
        task_id = (db.get_conversation(cid) or {}).get("task_id")
        text, error, trace, interrupt = await asyncio.to_thread(
            _run_agent_stream, agent, cid, rid, task_id, _publish, user_text, resume_decisions, cancel_event
        )
        duration_ms = int((time.monotonic() - t0) * 1000)

        # 本段结束（completed/error/waiting_input 都执行）：发布本次 run 登记的类型化
        # Artifact 事件，先于终态事件发出（时序沿用 §4.2）。发布本身在工具内即时落盘，
        # 这里只负责把 emitted=0 的记录推给前端。
        for row in db.pending_emit(rid):
            await publish(
                cid,
                {
                    "event": events.EVENT_ARTIFACT_CREATED,
                    "data": events.artifact_created_payload(row, rid, cid, next_seq()),
                },
            )
            db.mark_emitted(row["artifact_id"])

        if error:
            # 最终回复为空时用最后一段旁白兜底（半截消息至少能看到 AI 说到哪了）
            snapshot_text = text if text.strip() else _last_narration(trace["tools"])
            if snapshot_text.strip():
                # 中断 run 的半截回复落库：checkpoint 里模型"说过"这些话（或 dangling 修复后
                # 仍残留半截上下文），messages 表同步记一份（带中断标记），UI 与模型记忆对齐
                db.append_assistant_message(cid, snapshot_text.rstrip() + "\n\n（任务中断）")
            else:
                # 续跑段终止且无任何新产出：改写暂停消息的「等待你的输入…」标记，
                # 否则对话最后一句永远宣称在等输入、与已终止的 run 矛盾
                db.retire_pause_marker((db.get_run(rid) or {}).get("pause_msg_id"))
            # 中断 run 的执行过程也落 trace（message_id 空）便于复盘
            db.save_run_trace(rid, cid, None, trace["tools"], trace["todos"], duration_ms, trace.get("reasoning", ""))
            # code（契约 additive）：cancelled=用户主动停止，前端据此中性呈现（非红色错误卡）
            await publish(
                cid,
                {
                    "event": events.EVENT_ERROR,
                    "data": {
                        "run_id": rid,
                        "conversation_id": cid,
                        "error": error,
                        "code": "cancelled" if error == events.CANCELLED_MESSAGE else None,
                        "seq": next_seq(),
                    },
                },
            )
            db.finish_run(rid, "error", error)
            return

        if interrupt:
            # HITL 暂停：半截回复落库（沿用「任务中断」先例）+ trace，run 转 waiting_input，
            # 快照与 last_seq 存进 runs 行——重启后 run.state/前端恢复审批卡、seq 续接都靠它。
            msg_id = None
            # 同 error 分支：最终回复为空时用最后一段旁白兜底（被门禁拦下的轮次常无正文）
            snapshot_text = text if text.strip() else _last_narration(trace["tools"])
            if snapshot_text.strip():
                msg_id = db.append_assistant_message(cid, snapshot_text.rstrip() + "\n\n（等待你的输入…）")["id"]
            db.save_run_trace(rid, cid, msg_id, _freeze_paused_steps(trace["tools"]), trace["todos"], duration_ms, trace.get("reasoning", ""))
            seq = next_seq()
            await publish(
                cid,
                {
                    "event": events.EVENT_RUN_INTERRUPT,
                    "data": {
                        "run_id": rid,
                        "conversation_id": cid,
                        "requests": interrupt["requests"],
                        "seq": seq,
                    },
                },
            )
            db.interrupt_run(rid, interrupt["requests"], seq, pause_msg_id=msg_id)
            return

        if not text.strip():
            text = "（空回复）"
        msg = db.append_assistant_message(cid, text)
        # 执行过程快照与 assistant 消息关联落库（历史会话/刷新后执行过程仍可见）
        db.save_run_trace(rid, cid, msg["id"], trace["tools"], trace["todos"], duration_ms, trace.get("reasoning", ""))
        db.finish_run(rid, "completed")
        await publish(
            cid,
            {"event": events.EVENT_COMPLETED, "data": {"run_id": rid, "conversation_id": cid, "message_id": msg["id"], "seq": next_seq()}},
        )
    except Exception as e:
        logger.exception("run_stream failed")
        db.finish_run(rid, "error", str(e))
        await publish(cid, {"event": events.EVENT_ERROR, "data": {"run_id": rid, "conversation_id": cid, "error": str(e), "seq": next_seq()}})
    finally:
        CANCEL_EVENTS.pop(rid, None)
