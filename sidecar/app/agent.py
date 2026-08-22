"""DeepAgents 封装：build_agent / run_stream。

build_agent 按 PRD §5.6 已验证代码构造；run_stream 在 asyncio.to_thread 中驱动
agent.stream(stream_mode=["messages","updates"])，把 iter_stream 归一化的事件发布到 bus，
并在结束/出错时把最终消息落库 app.db、更新 runs 状态。
"""

import asyncio
import logging
import sqlite3

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver

from . import config as cfg
from . import db
from . import events
from .bus import publish
from .tools.tender_toc import TOOLS

logger = logging.getLogger(__name__)

_agent = None
_agent_lock = asyncio.Lock()
_saver_conn = None  # 持久 sqlite 连接（进程存活期只开一条、永不关闭）
_saver = None


def _get_saver():
    global _saver_conn, _saver
    if _saver is None:
        _saver_conn = sqlite3.connect(str(cfg.agent_db_path()), check_same_thread=False)
        # langgraph-checkpoint-sqlite 3.x：from_conn_string 是上下文管理器（会随 with 关闭连接）。
        # sidecar 常驻进程需要连接全程存活，故自持连接、直接构造 SqliteSaver（内部自带线程锁）。
        _saver = SqliteSaver(_saver_conn)
    return _saver


def build_agent():
    """构造（或重建）DeepAgents 实例。settings 变更后调用 rebuild_agent()。"""
    api_key = cfg.llm_api_key()
    if not api_key:
        raise RuntimeError("LLM_API_KEY 未设置（sidecar 只能通过环境变量拿到 key）")

    model = ChatOpenAI(
        api_key=api_key,
        base_url=cfg.llm_base_url(),
        model=cfg.llm_model(),
        timeout=180,
    )

    agent = create_deep_agent(
        model=model,
        backend=FilesystemBackend(root_dir=str(cfg.workspace_dir())),
        tools=TOOLS,
        skills=["skills/"],  # 未加载时在 main 启动日志提示换写法（见 README）
        system_prompt=(
            "你是标书助理。方法论在 skills 目录中："
            "标书分析用 tender-analysis 技能；"
            "解析招标文件生成投标目录用 tender-toc 技能"
            "（按其 SKILL.md 与 references/prompts.md 执行，脚本步骤用提供的工具，不要自己编命令）。"
        ),
        checkpointer=_get_saver(),
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


def _run_agent_stream(agent, user_text: str, cid: str, rid: str, _publish) -> tuple[str, str | None]:
    """worker 线程里跑完整流，逐块实时回调 _publish(event, data)。返回 (assistant_text, error)。"""
    stream = agent.stream(
        {"messages": [("user", user_text)]},
        config={"configurable": {"thread_id": cid}},
        stream_mode=["messages", "updates"],
    )
    text_parts: list[str] = []
    error = None
    try:
        for kind, payload in events.iter_stream(stream):
            if kind == "token":
                text_parts.append(payload)  # type: ignore[arg-type]
                _publish(
                    events.EVENT_TOKEN,
                    {"run_id": rid, "conversation_id": cid, "text": payload},
                )
            elif kind == "tool_called":
                _publish(
                    events.EVENT_TOOL_CALLED,
                    {"run_id": rid, "conversation_id": cid, "tool": payload["tool"], "args": payload["args"]},
                )
            elif kind == "tool_result":
                _publish(
                    events.EVENT_TOOL_RESULT,
                    {"run_id": rid, "conversation_id": cid, "tool": payload["tool"], "summary": payload["summary"]},
                )
    except Exception as e:  # 网络/API 错误等
        logger.exception("agent stream failed")
        error = str(e)
    return "".join(text_parts), error


async def run_stream(cid: str, rid: str, user_text: str) -> None:
    """后台任务：驱动一次 agent 流式执行并实时发布 §5.5 事件。"""
    try:
        await publish(cid, {"event": events.EVENT_STARTED, "data": {"run_id": rid, "conversation_id": cid}})
        agent = await get_agent()
        loop = asyncio.get_running_loop()

        # worker 线程里逐块发布：把协程调度回事件循环（queue.put_nowait 即时返回）
        def _publish(event: str, data: dict) -> None:
            fut = asyncio.run_coroutine_threadsafe(publish(cid, {"event": event, "data": data}), loop)
            fut.result()

        text, error = await asyncio.to_thread(_run_agent_stream, agent, user_text, cid, rid, _publish)

        if error:
            await publish(cid, {"event": events.EVENT_ERROR, "data": {"run_id": rid, "conversation_id": cid, "error": error}})
            db.finish_run(rid, "error", error)
            return

        if not text.strip():
            text = "（空回复）"
        msg = db.append_assistant_message(cid, text)
        db.finish_run(rid, "completed")
        await publish(
            cid,
            {"event": events.EVENT_COMPLETED, "data": {"run_id": rid, "conversation_id": cid, "message_id": msg["id"]}},
        )
    except Exception as e:
        logger.exception("run_stream failed")
        db.finish_run(rid, "error", str(e))
        await publish(cid, {"event": events.EVENT_ERROR, "data": {"run_id": rid, "conversation_id": cid, "error": str(e)}})
