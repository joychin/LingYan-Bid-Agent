"""DeepAgents 封装：build_agent / run_stream。

build_agent 按 PRD §5.6 已验证代码构造；run_stream 在 asyncio.to_thread 中驱动
agent.stream(stream_mode=["messages","updates"])，把 iter_stream 归一化的事件发布到 bus，
并在结束/出错时把最终消息落库 app.db、更新 runs 状态。

任务层（P4）：run 启动解析会话所属任务写入 runctx；_TaskContextMiddleware 在
每次模型调用时注入任务上下文（任务名/进度便签/产物清单——现算、不落 checkpoint）。
"""

import asyncio
import contextvars
import copy
import dataclasses
import itertools
import json
import logging
import random
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from deepagents import create_deep_agent
from deepagents.middleware.summarization import SummarizationMiddleware, compute_summarization_defaults
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware, ToolErrorMiddleware
from langchain_core.exceptions import ContextOverflowError, ModelConnectionError, ModelRateLimitError, ModelTimeoutError
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from openai import APIError, APIStatusError, APITimeoutError, BadRequestError, InternalServerError, RateLimitError

from . import (
    artifact_store,
    db,
    deliverables,
    dispatch_enrich,
    events,
    llm_throttle,
    model_registry,
    path_resolve,
    run_files,
    runctx,
    token_usage,
)
from . import config as cfg
from .bus import publish
from .fs_guard import GuardedBackend
from .tools import TOOLS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langchain.agents.middleware import ToolCallRequest

# HITL：这些工具的调用先 interrupt 暂停、等用户裁决后 resume。ask_human 只允许
# respond（回答代替执行）。task 派发审批门禁已于 2026-09-06 删除（用户拍板：
# 每次派发子代理都弹审批卡太吵，直接执行）；要恢复门禁加回
# "task": {"allowed_decisions": ["approve", "reject"]} 即可。
INTERRUPT_ON: dict = {
    "ask_human": {"allowed_decisions": ["respond"]},
}

# 图执行的并发步数上限：langgraph RunnableConfig 顶层键（_run_agent_stream 的
# stream config 设置），封顶同一 superstep 的并行任务——含同一消息并发派发的多个
# task 子代理，并经 ensure_config 的 ContextVar 拷贝自动传入子代理图（各图自建
# executor/semaphore，无共享无死锁）。行业标配（Claude Code 20 / OpenAI SDK
# max_function_tool_concurrency / LangGraph 原生）；8 = 自建网关实测稳定并发，
# tender-body 派发纪律的「每消息 ≤8 个任务」与此对齐（2026-09-15 起分组由模型
# 自主规划，波容量不再是程序侧概念）。
_MAX_CONCURRENT_STEPS = 8

# LLM 流式调用的瞬时错误（连接断开/超时/限流）：可从 checkpoint 断点自动重试——
# 失败节点的写入未提交 checkpoint，以 input=None 重拉 graph 只重跑该节点，代价 ≈ 一次
# 模型调用（见 _run_agent_stream）。认证/参数类永久错误不走重试，直接失败。
_LLM_RETRYABLE_ERRORS = (ModelConnectionError, ModelRateLimitError, ModelTimeoutError)
_LLM_RETRY_BACKOFFS = (3.0, 10.0, 30.0)  # 三次重试的等待秒数（等待期间尊重停止请求）


def _jittered_backoff(base: float) -> float:
    """退避加随机抖动（±50%）：整波并发同时被拒后不再同秒齐重试（重试风暴）。

    OpenAI Cookbook 明确建议的防同步重试标配；「任意用户网关」前提下整波齐拒
    是真实现场景（AIMD 收闸前的那一波）。agent.retry 载荷带抖动后的真值。"""
    return base * random.uniform(0.5, 1.5)
# SSE 流迭代期断连（"peer closed connection ... incomplete chunked read"）以裸
# httpx.RemoteProtocolError 逸出：openai SDK 只在建连阶段包装 httpx 异常，流路径不包；
# langchain_openai 也只在 openai.APIError 路径包装成 ModelConnectionError。类型匹配
# 之外再按消息关键词兜底，覆盖库版本更替下同类瞬断换了包装的情况。
_LLM_TRANSIENT_MARKERS = (
    "peer closed connection",
    "incomplete chunked read",
    "connection reset by peer",
    # 网关过载（2026-09-07 实测自建网关流内 "Our servers are currently overloaded"）；
    # 不收 "try again later"——配额类永久错误常带此措辞
    "overloaded",
)


def _is_llm_transient(exc: BaseException) -> bool:
    """异常是否为可断点重试的瞬时 LLM/网络错误（否则按永久错误直接失败）。"""
    if isinstance(exc, _LLM_RETRYABLE_ERRORS):
        return True
    if isinstance(exc, httpx.RemoteProtocolError):
        return True
    # 网关流内错误事件：openai _streaming.py 对数据流中途的 {"error":...} 无论错误体
    # 带不带 code/status 一律构造裸基类 APIError（类型化子类只存在于建连前非 2xx
    # 响应路径），langchain_openai 对裸基类也原样 re-raise。精确类型匹配（type is，
    # 非 isinstance）恰好只命中这一形态——401/400/404 全是子类，不会误伤。
    if type(exc) is APIError:
        return True
    # 请求级 5xx（langchain 包装后的混合类仍继承 openai.InternalServerError）：
    # SDK 自身重试已耗尽，图级断点再给一次机会，错杀代价 = 重跑一个节点
    if isinstance(exc, InternalServerError):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _LLM_TRANSIENT_MARKERS)


class AgentConfigError(RuntimeError):
    """模型配置缺失/失效（未配置模型、未配置 Key）：归类 llm_auth，
    前端给「去设置」入口而非让用户干等重试。"""


def _classify_error(exc: BaseException) -> tuple[str, str]:
    """错误定性 → (code, 人话文案)。code 取值域（agent.error/run.state 契约 additive
    2026-09-08）：llm_auth=模型未配置/Key 失效/账户欠费；llm_unavailable=服务方过载/超时/断流；
    internal=程序自身错误（兜底）。文案首行给人话、次行起原样保留服务方/异常原文
    （前端按 \\n 拆行渲染：首行主文案、其余小字），原文截 300 字符防超长。"""
    if isinstance(exc, AgentConfigError):
        return "llm_auth", str(exc)
    # 建连阶段非 2xx 的 401/403/402 是类型化子类（流内错误是裸基类 APIError，见
    # _is_llm_transient 注释）——Key 无效/权限被封 401/403、账户欠费 402 都在这里暴露；
    # 三者重试都救不了，统一归 llm_auth 让前端给「去设置」入口
    if isinstance(exc, APIStatusError) and exc.status_code in (401, 403, 402):
        if exc.status_code == 402:
            human = "模型账户额度不足（欠费）——请前往服务商平台充值，或切换到其他模型。"
        else:
            human = "模型 API Key 无效或已失效，请在 设置 → 模型 中检查。"
        return "llm_auth", f"{human}\n服务方返回：{str(exc)[:300]}"
    if _is_llm_transient(exc):
        # 正常不该到这（内层重试循环已消化瞬时错误），留作外层兜底路径的保险
        return (
            "llm_unavailable",
            f"模型服务暂时不可用。\n服务方返回：{str(exc)[:300]}",
        )
    return "internal", f"程序内部错误，请重试；反复出现可导出诊断反馈。\n错误详情：{str(exc)[:300]}"


def _task_failure_content(exc: Exception, request: "ToolCallRequest") -> str | None:
    """task（子代理派发）工具的异常收敛（ToolErrorMiddleware.on_error）。

    瞬时错误返回 None 上抛：异常经工具节点穿出主图，由 _run_agent_stream 的断点
    重试循环接手（_retire_broken_steps 负责 UI 收尾）——全自动重试语义不变。
    其余异常转错误字符串回给模型：langgraph 工具节点默认对非参数校验异常一律
    re-raise，deepagents 的 task 工具无 try/except，子代理内一个永久错误原本会
    打死整个主 run（2026-09-07 实测）。错误字符串带重派指引，模型据此自裁决。
    """
    if _is_llm_transient(exc):
        return None
    logger.exception(
        "task 子代理执行失败（tool_call_id=%s）", request.tool_call.get("id")
    )
    msg = str(exc) or exc.__class__.__name__
    return (
        f"[子代理执行失败] {exc.__class__.__name__}: {msg[:500]}\n"
        "可重派一次（必要时缩小范围或先核对输入）；"
        "仍失败则在最终回复向用户说明该部分未完成。"
    )


# ---------------------------------------------------------------------------
# 子代理路径罗盘 + 文件工具路径自愈（2026-09-08）
#
# 动因（run_traces 全库 24 次 path_not_found 类红错，全部发生在子代理开局探测）：
# 任务上下文只注入主 agent，子代理对虚拟文件系统布局全靠猜，而技能参考文档里的
# 路径示例全部按主 agent 视角书写（不带任务前缀），照抄即错。两层各治一半：
# ①罗盘（治"不知道"）——给子代理每次模型调用注入三行工作区布局事实；
# ②自愈（治"知道仍写错"）——文件工具事前发现目标不存在时按固定规则换算重写。
# general-purpose 子代理（deepagents 自动补）两件都挂不上（spec 不归我们传），
# 历史上它只贡献 1 次错误，接受；主代理不吃罗盘（任务上下文块已含工作目录行）。
# ---------------------------------------------------------------------------


def _path_compass_block(task_id: str) -> str:
    """子代理路径罗盘（run 内字节稳定：只依赖 task_id，前缀缓存铁律）。"""
    return (
        "【路径罗盘】文件系统的根就是工作区本身：没有 /workspace 这一层，"
        "也不要拼接本机绝对路径。\n"
        f"当前任务目录前缀：{task_id}/——work/、sources/ 下的一切读写路径都必须带"
        f"此前缀（例：{task_id}/work/body/…）。\n"
        "全局共享目录不带任务前缀：skills/、materials/、knowledge/。"
    )


class _SubagentCompassMiddleware(AgentMiddleware):
    """把路径罗盘追加到子代理每次模型调用的 system message（不落 checkpoint）。

    task_id 经 runctx（contextvars）在子代理工作线程里可取——与
    _RunAwareChatDeepSeek 的思考档位同一条传播链。无任务上下文时不注入。
    """

    def wrap_model_call(self, request, handler):
        ctx = runctx.current_run()
        if ctx is None or not ctx.task_id:
            return handler(request)
        compass = _path_compass_block(ctx.task_id)
        base = request.system_message.content if request.system_message is not None else ""
        request = dataclasses.replace(
            request,
            system_message=SystemMessage(content=f"{base}\n\n{compass}" if base else compass),
        )
        return handler(request)


class _SubagentScopeMiddleware(AgentMiddleware):
    """子代理用量打标：模型调用语境置 sub，per-turn 用量明细按 main/sub 归因。

    wrap_model_call 包住调用执行，记账点（模型壳 create 返回处 →
    token_usage.record_usage）在同一线程同一份 context 里，读到的 scope 即 sub；
    finally 复位防泄漏。嵌套子代理同标 sub（二元归因够用）。deepagents 自动补的
    general-purpose 子代理 spec 不归我们传、挂不上（记 main，历史频率极低，接受）。
    """

    def wrap_model_call(self, request, handler):
        token = runctx.set_agent_scope("sub")
        try:
            return handler(request)
        finally:
            runctx.reset_agent_scope(token)


# 参与自愈的文件工具（deepagents FilesystemMiddleware 内置）→ 路径参数名。
# delete 不参与：改写删除目标不可逆；execute 与 docx_ops 等自有工具各有自己的
# 路径解析约定，不碰。
_FS_PATH_TOOLS: dict[str, str] = {
    "ls": "path",
    "glob": "path",
    "grep": "path",
    "read_file": "file_path",
    "write_file": "file_path",
    "edit_file": "file_path",
}
# 换算候选序已收拢进 path_resolve（2026-09-15 路径可靠性批单点化）；别名保留
# 供既有调用方与测试引用
_norm_vpath = path_resolve.norm_vpath
_path_rescue_candidates = path_resolve.norm_candidates


def _is_path_miss_error(tool: str, content: str) -> bool:
    """工具错误文案是否为「路径不存在」类（用于终态错误富化；grep 的
    "No matches found" 是空命中不是坏路径，明确不匹配）。"""
    if tool == "ls":
        return ": path_not_found" in content
    if tool in ("read_file", "edit_file"):
        return "File '" in content and "not found" in content
    return False


class _PathRescueMiddleware(AgentMiddleware):
    """文件工具路径自愈：调工具前发现目标不存在时，按固定规则换算到存在的候选。

    事前换算而非事后看错误重试——glob/grep 对坏路径静默返回空结果、write_file
    自动建父目录（写错不报错直接散落），事后检测接不住这两类。只做字符串换算
    后交给原工具执行，containment 语义不变（候选仍在工作区虚拟根内）。
    """

    def _plan_rewrite(self, tool: str, args: dict, task_id: str) -> tuple[str, str] | None:
        """目标不存在且存在可用候选时返回 (arg_key, 新路径)，否则 None。"""
        arg_key = _FS_PATH_TOOLS.get(tool)
        raw = args.get(arg_key) if arg_key else None
        if not isinstance(raw, str) or not raw.strip():
            return None
        norm = _norm_vpath(raw)
        if norm is None:
            return None
        root = cfg.workspace_dir()
        target = root / norm.lstrip("/")
        candidates = _path_rescue_candidates(norm, task_id, str(root))
        if tool == "write_file":
            # 原父目录存在 = 真要写新文件，不动；仅当原父目录缺失而候选父目录
            # 存在才换算（模型本来就想写进那棵树）。两边都缺 = 真新区域，维持
            # 现状自动建目录。
            if target.parent.is_dir():
                return None
            for cand in candidates:
                if (root / cand.lstrip("/")).parent.is_dir():
                    return arg_key, cand
            return None
        want_dir = tool in ("ls", "glob", "grep")
        pred = (lambda t: t.is_dir()) if want_dir else (lambda t: t.is_file())
        if pred(target):
            return None
        for cand in candidates:
            if pred(root / cand.lstrip("/")):
                return arg_key, cand
        return None

    def _annotate(self, result, note: str):
        if isinstance(result, ToolMessage) and isinstance(result.content, str):
            return result.model_copy(update={"content": f"{result.content}\n{note}"})
        return result

    def wrap_tool_call(self, request: "ToolCallRequest", handler):
        call = request.tool_call
        tool = call.get("name")
        if tool not in _FS_PATH_TOOLS:
            return handler(request)
        ctx = runctx.current_run()
        if ctx is None or not ctx.task_id:
            return handler(request)
        args = call.get("args") or {}
        plan = self._plan_rewrite(tool, args, ctx.task_id)
        if plan is not None:
            arg_key, new_path = plan
            old_path = args.get(arg_key)
            request = request.override(
                tool_call={**call, "args": {**args, arg_key: new_path}}
            )
            result = handler(request)
            return self._annotate(
                result, f"（路径已按任务上下文解析为 {new_path}；原请求路径 {old_path} 不存在）"
            )
        result = handler(request)
        if (
            isinstance(result, ToolMessage)
            and result.status == "error"
            and isinstance(result.content, str)
            and _is_path_miss_error(tool, result.content)
        ):
            # 终态错误富化：错误文案自带罗盘，模型一步纠正而非盲猜 2–3 轮
            return self._annotate(result, _path_compass_block(ctx.task_id))
        return result


# tender-body 正文写手子代理名：派发拼装中间件的过滤目标（SUBAGENTS spec 与
# 中间件引用同一常量，改名单点生效）
_BODY_WRITER_NAME = "tender-body-writer"

# 写手最小工具集（2026-09-10）：spec 不写 tools 字段时 deepagents 继承全量
# TOOLS——22 个工具 schema 每轮模型调用都随身携带，实测 894 轮只用下列 13 个。
# 剔除的 9 个均为「prompt 明令禁止 / 职责归主线程 / 零调用」：ask_human、
# check_pipeline_state、docx_assemble_volume、read_artifact、assemble_tender、
# publish_artifact、update_task_progress、validate_analysis、list_templates。
# 文件七件套（ls/read_file/write_file/edit_file/glob/grep/delete）由
# FilesystemMiddleware 提供、不受 spec.tools 控制，自动随行。守卫测试防拼错
# 与「顺手加回」（test_agent）。
_BODY_WRITER_TOOLS = frozenset({
    "docx_section_create",
    "docx_section_read",
    "docx_section_revise",
    "docx_diagram_insert",
    "docx_html_figure",
    "docx_source_inject",
    "docx_material_inject",
    "docx_image_insert",
    "docx_comment_add",
    "validate_body",
    "check_name_residue",
    "search_references",
    "search_company_assets",
    "parse_document",
    "fetch_url",  # 用户明令保留（2026-09-10）：联网需求留通道
})


class _DispatchEnrichMiddleware(AgentMiddleware):
    """tender-body-writer 派发说明程序拼装（机制与动因见 dispatch_enrich 模块头）。

    三层过滤（工具名=task / subagent_type=正文写手 / runctx 有任务）外全部放行；
    拼装函数自身的任何异常也放行原文——增强逻辑绝不打断 run。改写发生在工具
    执行前（request.override），tool.called 事件仍带模型原始 args——UI 卡标题
    =模型短名不受影响；完整拼装块由任务文件确定性推导（无需事件侧同步）。
    """

    def wrap_tool_call(self, request: "ToolCallRequest", handler):
        call = request.tool_call
        if call.get("name") != "task":
            return handler(request)
        args = call.get("args") or {}
        if args.get("subagent_type") != _BODY_WRITER_NAME:
            return handler(request)
        ctx = runctx.current_run()
        if ctx is None or not ctx.task_id:
            return handler(request)
        enriched = dispatch_enrich.build_enriched_description(args.get("description"), ctx.task_id)
        if enriched is None:
            return handler(request)
        request = request.override(
            tool_call={**call, "args": {**args, "description": enriched}}
        )
        return handler(request)


# ── 重派守卫（2026-09-15 路径可靠性批）─────────────────────────────────────
# 动因：r_eedd621716b5 整本 run 两次 402 中断后 checkpoint 整波重放——中断落在
# 波中间（ToolNode 未落 superstep 存档）时续跑把整轮重派，59 节书派发 86 次、
# 13 节被完整重写一两遍。模型续跑后凭记忆重派不对账已写节，纪律管不住（SKILL
# 的「续跑后先对账」是软防线），故升机制：机械识别「本 run 内已写出的节被无
# 重写意图地再次派发」并拒绝执行——与清单同步守卫同款「拒绝+意图词泄压+次数
# 保险丝」模式。run 起点沿用 runs.created_at 原值（continue 不改写），续跑段
# 写出的文件同样算「本轮」，正是要拦的重放对象。
_REPLAY_GUARD_MARK = "〔重派守卫〕"
_REPLAY_INTENT_RE = re.compile(r"重写|覆盖|更新|修订|重派")
_REPLAY_GUARD_VALVE = 3  # 同 run 拒绝上限：防「拒绝→原样重发」死循环烧轮次
# runs.created_at 秒级精度 + 文件系统时钟差余量：mtime 早于起点-2s 才算历史产物
_REPLAY_MTIME_SLACK = 2.0
# rid -> {"hits": 拒绝次数, "start": run 起点 epoch 秒（懒加载，None=未初始化）}
_REPLAY_GUARD_STATE: dict[str, dict] = {}


class _ReplayGuardMiddleware(AgentMiddleware):
    """重派守卫：本 run 内已写出的节、无重写意图的再次派发 → 拒绝执行。

    与 _DispatchEnrichMiddleware 同款三层过滤（task/写手/任务上下文）；节名对账
    复用 dispatch_enrich.resolve_section（「节名→输出路径」单点推导；2026-09-15
    模型自主拆分批起派发可一任务多节——逐节名检查，任一节本轮已写即拒，把模型
    推回「只补派缺失的节」）。拒绝=不调
    handler 直接回 error ToolMessage（_ToolTimeoutMiddleware 同款，批内其他派发
    照常执行）。放行面有意宽：节名对不上/文件不存在/历史 run 写的旧节/描述含
    意图词/保险丝打满——守卫只治整波重放这一种确定性浪费，不当重写裁判。
    任何内部异常放行（增强逻辑绝不打断 run）。
    """

    def wrap_tool_call(self, request: "ToolCallRequest", handler):
        call = request.tool_call
        if call.get("name") != "task":
            return handler(request)
        args = call.get("args") or {}
        if args.get("subagent_type") != _BODY_WRITER_NAME:
            return handler(request)
        ctx = runctx.current_run()
        if ctx is None or not ctx.task_id or not ctx.run_id:
            return handler(request)
        desc = args.get("description")
        if not isinstance(desc, str) or _REPLAY_INTENT_RE.search(desc):
            return handler(request)
        try:
            state = _REPLAY_GUARD_STATE.setdefault(ctx.run_id, {"hits": 0, "start": None})
            if state["hits"] >= _REPLAY_GUARD_VALVE:
                return handler(request)
            if state["start"] is None:
                row = db.get_run(ctx.run_id)
                # 行缺失（理论不可达）=起点不可判：置 inf 恒放行，宁漏拦不误拦
                state["start"] = (
                    datetime.fromisoformat(row["created_at"]).timestamp() if row else float("inf")
                )
            for needle in dispatch_enrich.first_line_needles(desc):
                target = dispatch_enrich.resolve_section(needle, ctx.task_id)
                if target is None:
                    continue
                path = artifact_store.work_dir(ctx.task_id) / target.rel
                if not path.is_file() or path.stat().st_mtime <= state["start"] - _REPLAY_MTIME_SLACK:
                    continue
                state["hits"] += 1
                return ToolMessage(
                    content=(
                        f"{_REPLAY_GUARD_MARK}节「{target.title}」本轮已写出"
                        f"（{target.rel}），这多半是断点续跑/中断重放的重复派发。先调"
                        " check_pipeline_state 对账已写节、只补派缺失的节；确要重写"
                        "本节，请在派发描述里写明「重写」等意图词。"
                    ),
                    status="error",
                    tool_call_id=call.get("id") or "",
                    name="task",
                )
            return handler(request)
        except Exception:
            logger.debug("重派守卫检查失败，放行（rid=%s）", ctx.run_id, exc_info=True)
            return handler(request)


# 工具超时档位（秒）。重工具 600（磁盘+CPU 密集、无自身超时，对齐 Claude Code
# bash「默认 2min/硬上限 10min」的机制纪律）；其余全部工具默认 120——2026-09-12
# 从清单制改为兜底制：搜索/校验/发布/文件七件套 hang 时此前无上界，取消的事件
# 边界永不到达，会话被 409 钉死到重启。task（子代理）不设硬上限：其内部每步自带
# LLM 180s/工具超时、总量由主 worker 断流重试兜底，只参与取消感知。
# ask_human 不包（瞬时中断型，真正的等待在 HITL 暂停语义里）。
_TOOL_TIMEOUT_HEAVY = 600
_TOOL_TIMEOUT_DEFAULT = 120
_TOOL_TIMEOUTS: dict[str, int | None] = {
    **{
        name: _TOOL_TIMEOUT_HEAVY
        for name in (
            "parse_document",
            "assemble_tender",
            "docx_section_create",
            "docx_section_read",
            "docx_section_revise",
            "docx_material_inject",
            "docx_source_inject",
            "docx_image_insert",
            "docx_assemble_volume",
        )
    },
    "task": None,
}
_TOOL_TIMEOUT_SKIP = frozenset({"ask_human"})
# 取消感知的等待粒度（秒）：停止请求在任意工具执行期内 ≤ 此值即被察觉
_TOOL_CANCEL_POLL = 0.5


class _ToolCancelledError(RuntimeError):
    """用户请求停止时从工具等待中抛出：节点失败、superstep 不落 checkpoint，悬空
    tool_calls 由下一 run/续跑开头 PatchToolCalls 补插取消 ToolMessage 自愈——与
    既有「取消不清 checkpoint」同口径。"""


class _ToolTimeoutMiddleware(AgentMiddleware):
    """全工具超时封顶 + 取消感知（2026-09-12 从清单制扩展为兜底制）。

    超时：重工具 600 / 其余 120 / task 无硬上限。超时返回错误 ToolMessage 走既有
    tool error 通道，模型可自行缩小范围重试或绕行，run 正常收尾清理。
    取消感知：等待循环按 _TOOL_CANCEL_POLL 粒度查 CANCEL_EVENTS——置位即抛
    _ToolCancelledError 中止节点（worker 按 cancelled 收尾）。此前取消只能等工具
    自然返回（LLM 死等最坏 180s、清单外工具无上界），停止形同虚设。
    机制边界（明示）：Python 杀不掉线程——超时/中止后底层工具线程（daemon）滞留至
    自然结束，滞留计数有界；task 中止后子代理在后台跑到下一边界（token 消耗有界）；
    wrap_tool_call 是同步链，故真 handler 在复制了 contextvars 的新线程里执行
    （工具读任务上下文不受影响），本线程限时等待。
    """

    def wrap_tool_call(self, request: "ToolCallRequest", handler):
        call = request.tool_call
        name = call.get("name") or ""
        if name in _TOOL_TIMEOUT_SKIP:
            return handler(request)
        run_ctx = runctx.current_run()
        rid = run_ctx.run_id if run_ctx is not None else None
        timeout = _TOOL_TIMEOUTS.get(name, _TOOL_TIMEOUT_DEFAULT)
        cancel_event = CANCEL_EVENTS.get(rid) if rid is not None else None
        if cancel_event is None and timeout is None:
            return handler(request)  # 无取消语境且无硬上限（task+独立实例）：包了只剩开销
        # 取消预检：langgraph 若因本节点失败重试，重进即抛（快速耗尽重试策略）
        if cancel_event is not None and cancel_event.is_set():
            raise _ToolCancelledError(name)
        ectx = contextvars.copy_context()
        box: list = []
        done = threading.Event()

        def _run():
            try:
                box.append(handler(request))
            except BaseException as exc:  # 原样回传给上层链处理
                box.append(exc)
            finally:
                done.set()

        threading.Thread(
            target=ectx.run, args=(_run,), daemon=True, name="tool-timeout"
        ).start()
        deadline = None if timeout is None else time.monotonic() + timeout
        while not done.is_set():
            now = time.monotonic()
            if deadline is not None:
                remaining = deadline - now
                if remaining <= 0:
                    return ToolMessage(
                        content=(
                            f"[工具超时：{name} 已运行 {int(timeout) // 60} 分钟未完成——多半是文件过大或底层卡死。"
                            "注意：原调用可能仍在后台执行并最终写盘，请勿立即重写同一文件"
                            "（后写者会整体覆盖先写者）；请缩小范围（分节/分文件/限行号区间）"
                            "或换一条路径完成目标]"
                        ),
                        status="error",
                        tool_call_id=call.get("id") or "",
                        name=name,
                    )
                wait_for = min(_TOOL_CANCEL_POLL, remaining)
            else:
                wait_for = _TOOL_CANCEL_POLL
            if done.wait(wait_for):
                break
            if cancel_event is not None and cancel_event.is_set():
                raise _ToolCancelledError(name)
        result = box[0]
        if isinstance(result, BaseException):
            raise result
        return result


_SUBAGENT_COMPASS_MW = _SubagentCompassMiddleware()
_SUBAGENT_SCOPE_MW = _SubagentScopeMiddleware()
_PATH_RESCUE_MW = _PathRescueMiddleware()
_DISPATCH_ENRICH_MW = _DispatchEnrichMiddleware()
_REPLAY_GUARD_MW = _ReplayGuardMiddleware()
_TOOL_TIMEOUT_MW = _ToolTimeoutMiddleware()

# 显式注册的子代理（deepagents 还会自动补 general-purpose）。tools 不指定 → 继承主
# agent 全部工具；interrupt_on={} 整体替换继承：子代理不直接向用户提问（问答统一由
# 主 agent 发起，需裁决项由子代理记 ⚠待澄清带回）。
SUBAGENTS: list[dict] = [
    {
        # 投标目录编写子代理：单册 R2 初稿 + 三道清理的执行单元（tender-outline 多册并发）。
        # 任务目录前缀不随任务上下文注入子代理——派发 description 自带全部路径
        # （SKILL.md 第 2 步有清单），罗盘中间件兜底注入三行布局事实。
        "name": "tender-outline-writer",
        "description": (
            "为单个响应文件生成投标目录（R2 初稿+三道清理），输出 fragment"
            "（tender-outline 技能多册并发时的执行单元）"
        ),
        "system_prompt": (
            "你是投标目录编写子代理，只负责一个响应文件的目录初稿与清理。"
            "任务描述会给出：任务目录前缀（读写路径都必须带该前缀）、响应文件名、scope、"
            "fragment 输出路径、work/analysis 各输入文件的完整路径、来源文件名清单"
            "（主文件+补充文件名——回原文核实时据此构造 work/parse/<文件名>/ 路径）。\n"
            "开工前先依次 read_file：skills/tender-outline/references/generate.md、"
            "annotation.md、revise-gapfill.md、revise-scoring.md、revise-walkthrough.md，"
            "严格按其规则执行：R2 补全三段（## 目录 / ## 来源标注 / ## 目录说明）"
            "→ 三道清理（输入缺失的道跳过并在摘要里声明）。回招标原文核实时同样遵守"
            "导航纪律：读 work/parse/<文件名>/<文件名>.outline.json 按行号取区段，禁止整读全文。\n"
            "产物写到指定的 fragment 路径：单个 `# 响应文件：<名>` 标题 + scope 段 + 三段，"
            "遵守树格式红线（- 开头 / 无编号 / 每级 2 空格缩进 / 独立附件平级 / 不用代码块），"
            "全文严禁用代码块包裹。\n"
            "禁止调用 ask_human（无人应答）：需要用户裁决的记「⚠待澄清：…」进目录说明。\n"
            "完成后返回简短中文摘要：目录节点数、来源标注数、跳过的清理道及原因、待澄清项。"
        ),
        "interrupt_on": {},
        "middleware": [_SUBAGENT_COMPASS_MW, _SUBAGENT_SCOPE_MW, _PATH_RESCUE_MW, _TOOL_TIMEOUT_MW],
    },
    {
        # 正文编写子代理：一任务一节或多节的执行单元（tender-body 并发派发）。同
        # outline-writer：任务目录前缀不注入子代理。派发说明由 _DispatchEnrichMiddleware
        # 程序拼装（模型只写节名清单+意图，共享上下文机械补全——2026-09-08 实测模型
        # 派发塌成五字节名、32 个子代理开局自救烧掉整本六成输入 token，纪律清单管
        # 不住故升机制；2026-09-15 模型自主拆分批起支持一任务多节：主代理自行决定
        # 捆组粒度，首行列多个节名，拼装层共享块一份+逐节块每节一份）；
        # 要求以「内容+出处」形式传达，REQ 等内部编号不进派发（子代理会把「覆盖REQ-xx」
        # 镜像进正文首句），罗盘中间件兜底注入三行布局事实。
        "name": _BODY_WRITER_NAME,
        "description": (
            "按写作指引写一个或多个目录节的响应文件正文（tender-body 技能并发派发时的执行单元）"
        ),
        # 最小工具集（机制化收窄，见 _BODY_WRITER_TOOLS 注释）——不写则继承全量
        "tools": [t for t in TOOLS if t.name in _BODY_WRITER_TOOLS],
        "system_prompt": (
            "你是响应文件正文编写子代理，只负责任务描述点名的目录节的正文（2026-09-15 起"
            "一个任务可能带多个节）。任务描述=首行节名清单（一节或多节，多节以顿号分隔）"
            "与主代理意图，其后系统自动附上本任务派发上下文：任务目录前缀（读写路径都必须"
            "带该前缀）、各节文件输出路径（.docx，多节任务逐节给出【第 N 节：…】块）、"
            "今天日期（封面/函件落款用这行，"
            "不要自编日期）、各节写作模式、要求清单（每条=要求内容+"
            "出处，随时可按出处读招标原文核对）、可用素材块 id（格式跟随/格式件节另带"
            "拷原件指引）、公司材料与缺口（指引缺口列原文——【知识库】=知识库命中的"
            "公司事实，证书数字照抄不改写；【缺】=库里没有，批注待办）、承诺清单的全部"
            "值、兄弟节开头摘要——已含你所需的全部共享信息。\n"
            "多节任务执行纪律：**逐节完成、全部节完成才收尾**——每节独立走一遍"
            " 建节→注入/拷件→改写→validate_body 自查 再进下一节（不把多节内容混进"
            "同一个文件、不漏节；每节文件互不依赖，顺序按【第 N 节】块给定的次序）。\n"
            "开局纪律：写作方法论（section-writing.md 全文）已随任务描述给出，"
            "**不要 read_file 它**；若还需其它参考文件，在同一条消息里一次读齐"
            "（禁止逐个串行）；禁止调用"
            " check_pipeline_state（流水线状态归主线程）；禁止读 写作指引.md 与 "
            "关键事实与承诺.md 全文（你的指引行与全部承诺值已在任务描述）；"
            "docx_section_create 后 docx_section_read 通读一次，此后修订按段落/表格"
            "标签定位，不再整读全文——docx_section_revise 的返回自带改动后现文，"
            "改完即续下一步、**不回读视图确认**；开局禁止 ls/glob 探测目录（目录"
            "前缀与输出路径已在任务描述首部）；禁止 grep/检索 REQ/MAND/SCORE/TPL"
            " 内部编号——要求原文与出处已按内容解析给出，编号不在你的语境（更不要"
            "写进正文）。\n"
            "建节用 body 块序列（段落+表格混排）——人员配置/里程碑/进度/对比类内容"
            "用表格不用流水句（写法示例在方法论里）；派发上下文「本节图示清单」的"
            "计划项逐个产出：普通数据表=body 的 table 块、分层/组织架构/甘特/中心"
            "辐射=docx_diagram_insert（程序生成，只给语义拓扑），界面原型=docx_html_figure"
            "（只写全部样式内联的 HTML，禁外链禁脚本，渲染失败改文字描述+批注），"
            "计划外不配图。"
            "严格按素材先行五步执行（docx 直出，模型不直接写 docx 二进制）：选块"
            "（任务描述已给素材块清单时**直接采用**——清单带每块标题/字数/含图/"
            "来源文件，够做规划，**不再调用 search_references**；清单缺失、指引标"
            "【缺】或块标已失效才自行检索）→ 列使用计划 → docx_section_create 建节 + "
            "docx_material_inject 素材块保真贴底稿（非 docx 素材才自行撰写）→ "
            "docx_section_read 拿段号 + docx_section_revise 改写适配本项目 → "
            "validate_body(section=<节路径>, block_ids=<使用计划的块>) 自查。\n"
            "格式跟随/格式件节：出处原件是 docx 时用 docx_source_inject（source=任务"
            "描述给的来源文件名，lines=行号区间；独立格式附件整文件拷）把招标格式原样"
            "拷进节文件，再 revise 填空——表格空格子 fill、旧值 replace（表格按 "
            "table/row/col 格坐标寻址）；pdf 原件无可拷元素，按解析文本自行成形。"
            "填我方公司事实（资质证书/体系认证/注册信息/注册资本等）优先用任务描述"
            "「公司材料与缺口」段的【知识库】命中事实（注册号/有效期照抄原文），"
            "段里没有的现查 search_company_assets，查不到才批注待办——禁止凭印象编。\n"
            "任务描述意图句给了临时参考件（sources/ 的类似案例，带路径+行号区间）时："
            "按区段 read_file 参考**写法**——章节组织/论证顺序/表格设计/语言风格可"
            "借鉴，案例里的项目名/客户名/数字/公司信息一律不进正文，与要求清单冲突"
            "以要求清单为准；案例内容进正文一律改写、不整段拷贝；完成摘要里说明"
            "用了案例哪些写法。未给参考件则忽略本条，不要主动去 sources/ 翻文件。\n"
            "硬纪律：承诺类数字只能使用任务描述给出的承诺清单值，清单没有的用 "
            "docx_comment_add 加批注带回待澄清，不得编造；缺料/待核验同样 "
            "docx_comment_add 加批注（锚定相关段落）继续写不阻塞——**正文里禁止写"
            "【待补】【待澄清】占位文字**（会随交付稿打印出去，validate_body 判不过）；"
            "docx 素材块必须先"
            " docx_material_inject 注入贴底稿再 revise 适配，禁止跳过注入直接自写——"
            "素材块内的图片只有注入能带进正文（自写=图全丢）；认为指引指派的素材块"
            "与本节要求明显不符时（如历史标书讲的行业/产品与本节主题无关、块内容与"
            "本节依据的要求对不上），**仍须照常注入并改写**，不得自行跳过该块或改换"
            "其他块——另用 docx_comment_add 留一条以「素材异议」开头的批注（锚定相关"
            "段落）：写清哪一块 blk_…、为什么不符、本节如何处理（已淡化/未采用其某"
            "部分）；证书复印件等独立图片"
            "用 docx_image_insert 插入（图源路径用 search_company_assets 命中行的"
            "「含图 N 张」提示，PDF 原件传路径+页号）；物理附件/复印件节任务描述标了"
            "【知识库】命中（含图）的，建节后按其图源路径逐张贴图产出节文件，库里"
            "没有的建壳节——标题+一行贴入位「（此处贴入：XXX 复印件，加盖公章）」"
            "+批注点名待线下补；正文是干净文本，"
            "不带任何头部/元信息，且 REQ/MAND/SCORE/TPL-xx 内部对账编号（无论从任务"
            "描述还是指引等文件里看到）一个都不写进正文——呼应招标要求用要求内容或"
            "招标文件真实印着的章节/条款号（如「按第三章 2.3 条」，评标人可对照原文，"
            "内部编号他们对不上）；兄弟节已覆盖的要点参考摘要避免重复展开；只写任务"
            "描述点名的节文件（已存在的节重建传 replace=true），不动任何其他文件。\n"
            "禁止调用 ask_human（无人应答）：需要用户裁决的用 docx_comment_add 加批注带回。\n"
            "禁止改写写作指引与关键事实与承诺清单（共享文件只归主线程维护）。\n"
            "完成后返回简短中文摘要：**逐节**列 节名、字数、使用素材块与重叠率、自查"
            "结果、素材异议（无则写「无」；有则逐条列块 id 与理由）、待办批注清单——"
            "多节任务一节一段、一节不漏。"
        ),
        "interrupt_on": {},
        "middleware": [_SUBAGENT_COMPASS_MW, _SUBAGENT_SCOPE_MW, _PATH_RESCUE_MW, _TOOL_TIMEOUT_MW],
    },
]

_agents: dict[str, object] = {}  # profile_id -> agent（跨供应商多模型：每 profile 一份）
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


def checkpoint_exists(cid: str) -> bool:
    """该会话在 agent.db 里是否有 checkpoint（continue 端点前置校验，2026-09-12）：
    断点续跑的前提是 thread 存在——agent.db 损坏/被删后记忆重建只产出纯文本对，
    thread 缺失时续跑会在首个模型调用处异常落 internal 终态；提前挡掉给用户
    「请重新执行」的明确出路。读失败按不存在处理（不放大成 500）。"""
    try:
        return _get_saver().get_tuple({"configurable": {"thread_id": cid}}) is not None
    except Exception:
        logger.exception("checkpoint 预检失败（cid=%s）", cid)
        return False


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
    """拼装任务上下文注入块：任务名 + 进度便签 + 单一产物清单（名称）。

    共享的是文件夹和结论，不是聊天记录（设计文档 §8.2）：模型要具体内容时
    经 read_artifact 按需读取。**必须经 _task_context_block_frozen 使用**——直接
    每次调用现算会让秒级时间/便签/产物清单逐次变化，打断模型供应商的前缀缓存
    （DeepSeek 自动前缀缓存按字节前缀匹配，断点后全部按未命中全价计费；
    2026-09-06 实测一个正文 run 烧掉千万级 token 的主因）。
    """
    task = db.get_task(task_id)
    if not task:
        return ""
    lines = [
        f"## 当前任务：{task['title']}（本会话属于该任务，产物归任务、单一当前版本）",
        # §16 任务分组目录：模型引用文件/产物的路径前缀（sources/ 来源、work/ 工作树）
        f"任务工作目录：`{task_id}/`（用户上传的文件在其 sources/ 下，解析与分析过程文件在 "
        "work/ 下，发布暂存写 _meta/staging/；引用这些路径时带上该前缀）",
        # 天级日期（Claude Code 同款精度）：秒级时间戳每次调用都变会打断前缀缓存，
        # 一天只断一次可接受；模型写时间戳的场景已删（分析产物头部 2026-09-04 裁决），
        # 日期足够定位"今天"。需要精确时刻的少数场景按业务就近说明。
        f"今天日期：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}（UTC；涉及时效判断时用它，不要自己估）",
    ]
    note = (task.get("progress_note") or "").strip()
    if note:
        lines.append(f"### 任务进度便签\n{note}")
    kb_line = _kb_summary_line()
    if kb_line:
        lines.append(kb_line)
    artifacts = _artifact_listing(db.list_artifact_index(task_id=task_id))
    if artifacts:
        lines.append("### 任务产物\n" + "\n".join(artifacts))
    return "\n".join(lines)


# 任务上下文块的 run 内冻结缓存：run_id -> 块文本。前缀缓存铁律——system 在整个
# run 内必须字节稳定（见 _task_context_block docstring），便签/产物清单随块在 run
# 起点定格：run 中途的更新不再自动可见，模型要新鲜状态自己 read_artifact/查目录
# （工具就是它的眼睛）。HITL 续跑同 run_id 沿用冻结块（续段缓存还能接上）。
# 容量守卫（2026-09-10 review 收口）：只逐条淘汰最旧一条、绝不全表 clear——全清
# 会把仍在跑的长 run 已冻结的块一并抹掉，该 run 下次调用现算新块=system 中途变化，
# 正是本机制要防的缓存全废事故。常态下 run 终态即清理（_frozen_ctx_cleanup），
# 守卫只是长驻进程的兜底，基本不触达。条目只是短文本。
_FROZEN_CTX: dict[str, str] = {}


def _frozen_ctx_cleanup(run_id: str | None) -> None:
    """run 终态（completed/error）清掉自己的冻结块——waiting_input 暂停不清
    （续跑同 run_id 沿用冻结块的语义）。幂等，缺省静默。"""
    if run_id:
        _FROZEN_CTX.pop(run_id, None)


def _task_context_block_frozen(task_id: str, conversation_id: str, run_id: str | None) -> str:
    """run 内冻结版任务上下文块：每个 run 计算一次、字节不变；非 run 态现算。"""
    if not run_id:
        return _task_context_block(task_id, conversation_id)
    block = _FROZEN_CTX.get(run_id)
    if block is None:
        if len(_FROZEN_CTX) >= 64:
            # 逐条淘汰最旧若干、插入后总量封顶 64（insertion order；当前 rid
            # 尚未插入必是最新，被淘汰的只会是早已结束的 run 的残留条目）
            while len(_FROZEN_CTX) >= 64:
                _FROZEN_CTX.pop(next(iter(_FROZEN_CTX)))
        block = _task_context_block(task_id, conversation_id)
        _FROZEN_CTX[run_id] = block
    return block


def _kb_summary_line() -> str:
    """知识库+素材库摘要（事实层=我们有什么/做过什么；素材层=用户手工挑选的写法章节）。
    无内容时返回空不占上下文。"""
    from .knowledge.types import ROLE_LABELS, TYPES, role_of

    items = db.kb_list_items()
    mt_files = db.mt_list_files()
    if not items and not mt_files:
        return ""
    lines = []
    for role in ("fact", "writing"):
        role_items = [it for it in items if role_of(it.get("doc_type")) == role]
        if not role_items:
            continue
        counts: dict[str, int] = {}
        for it in role_items:
            code = it.get("doc_type") or "other"
            counts[code] = counts.get(code, 0) + 1
        parts = [f"{TYPES[c].name} {n} 份" for c, n in sorted(counts.items()) if c in TYPES]
        pending = sum(1 for it in role_items if it["review_status"] == "pending_review")
        tail = f"，其中 {pending} 份信息待用户确认" if pending else ""
        label = ROLE_LABELS[role] + "（事实检索用）" if role == "writing" else ROLE_LABELS[role]
        lines.append(f"{label} {len(role_items)} 份：{'、'.join(parts) or '未分类'}{tail}")
    if mt_files:
        n_blocks = db.mt_count_blocks()
        lines.append(
            f"写作素材库 {len(mt_files)} 份文件 {n_blocks} 个素材块（用户手工挑选的章节+备注，写法最可靠）"
        )
    return (
        "### 公司知识库与写作素材\n" + "\n".join(lines) + "\n"
        "写标书陈述公司资质/案例/业绩等事实时先用 search_company_assets 检索（历史标书"
        "里的业绩描述可引用但须与合同核对，拟投入承诺不是现状事实）；参考同类内容怎么写、"
        "需要整章拷贝修订、或想知道某类产品/服务该写哪些能力模块时用 search_references"
        "（查用户手工挑选的素材块及其备注；素材≠公司事实，数字与承诺须按本次招标重新核对；"
        "拷贝素材后必须 check_name_residue 扫旧名残留）。检索后按行号区间用 read_file 精读原文。"
    )


class _TaskContextMiddleware(AgentMiddleware):
    """每次模型调用前把任务上下文块追加到 system message（不落 checkpoint）。

    与工具同处 worker 线程的同一份 context 拷贝，经 runctx 按当前 run 解析任务；
    不在任务会话中（无 task_id）时不注入。
    """

    def wrap_model_call(self, request, handler):
        ctx = runctx.current_run()
        if ctx is None or not ctx.task_id:
            return handler(request)
        # run 内冻结（前缀缓存铁律）：同 run 每次调用字节相同，见 _FROZEN_CTX 注释
        block = _task_context_block_frozen(ctx.task_id, ctx.conversation_id, ctx.run_id)
        if not block:
            return handler(request)
        base = request.system_message.content if request.system_message is not None else ""
        request = dataclasses.replace(
            request, system_message=SystemMessage(content=f"{base}\n\n{block}" if base else block)
        )
        return handler(request)


# 任务清单陈旧阈值：距上一次 write_todos 的消息条数超过它才提醒。整本逐节生成的
# 主代理每波派发/返回约产生 8~20 条消息，10 ≈ 滞后一到两拍——不在模型正常工作
# 节奏里制造噪音，也不让清单停在上一阶段数小时（2026-09-13 实测：确认门之后
# 40+ 次子代理派发零 write_todos，面板停在 4/8 而实际已跑到第 4 波）。
_TODO_STALE_THRESHOLD = 10
# 清单同步守卫（二批，2026-09-13）：滞后超过它时拒绝 task 派发，逼模型先回写
# 清单。6 ≈ 一整波（8 路）的 ToolMessage 数——波内不拦（清单标 in_progress 本就
# 正确），跨波未回写必拦。
_TODO_GATE_THRESHOLD = 6
# 泄压阀：同一段内守卫已拒绝这么多次仍不回写 → 放行派发（防病态循环卡死 run；
# 对齐 opencode-auto-resume 插件 maxRetries=3 的有界拒绝实践）。
_TODO_GATE_VALVE = 3
# 守卫拒绝文案标记：泄压阀从消息序列无状态计数的锚点（勿改文案前缀）。
_TODO_GATE_MARK = "〔清单同步守卫〕"


def _todo_baseline(msgs: list) -> tuple[bool, int, bool, int]:
    """清单基线推导（消息序列纯函数，提醒与守卫共用）。

    返回 (写过清单, 距基线的消息条数, 裁决后未回写, 基线位置)。基线取「最后一条
    write_todos 结果」；若其后存在 ask_human 的代答 ToolMessage（HITL resume 合成
    的用户回答/respond，tool_call_id 沿用原调用），基线抬到代答处并置
    resume_pending——「刚回答完用户、清单还没刷新」是消息序列可机械识别的边界
    （2026-09-13 实测事故：续跑后 4 分钟面板仍停在上一阶段，提醒层对该首拍盲区）。
    """
    write_ids: set[str] = set()
    ask_ids: set[str] = set()
    for m in msgs:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                if not tc.get("id"):
                    continue
                if tc.get("name") == "write_todos":
                    write_ids.add(tc["id"])
                elif tc.get("name") == "ask_human":
                    ask_ids.add(tc["id"])
    if not write_ids:
        return False, 0, False, -1
    last_write = last_answer = None
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if not isinstance(m, ToolMessage):
            continue
        if last_write is None and m.tool_call_id in write_ids:
            last_write = i
        if last_answer is None and m.tool_call_id in ask_ids:
            last_answer = i
        if last_write is not None and last_answer is not None:
            break
    if last_write is None:
        return False, 0, False, -1
    base, resume_pending = last_write, False
    if last_answer is not None and last_answer > last_write:
        base, resume_pending = last_answer, True
    return True, len(msgs) - 1 - base, resume_pending, base


class _TodoFreshnessMiddleware(AgentMiddleware):
    """任务清单陈旧提醒 + 同步守卫（只挂主 agent——子代理没有 todos）。

    提醒（2026-09-13 一批）：距上次 write_todos 太久时，在最新工具结果尾部追加
    一句系统提醒，模型回写清单后自动消失。动因：langchain TodoListMiddleware 的
    工具描述原文已要求「实时更新、完成立刻标、不要攒批」，但整本逐节生成的波次
    循环里模型就是不调，任务清单数小时停在确认门之前的旧阶段。纪律在场的失灵
    先例：派发说明塌方→dispatch_enrich 程序拼装、ask_human 参数泄漏→机械归一化。

    守卫（2026-09-13 二批，治本）：提醒固有 latency=一整波（8 路 ToolMessage 才
    攒够阈值 10），且续跑后首拍完全盲区（实测复现：回答完 4 分钟面板不动）。
    after_model 在派发落地前整批拒绝滞后的 task 调用——子代理派发不可能带着滞后
    清单执行，这才是保证。实现手法对齐框架内先例 TodoListMiddleware.after_model
    的并行 write_todos 拒绝（error ToolMessage 应答 tool_call → 路由层判「无
    pending 调用」跳回模型节点，factory.py 既有路径，HITL 同款）；行业佐证：
    OpenCode #28961（同病、纪律路线证伪、官方关闭不做）+ opencode-auto-resume
    插件（todo 真值 + 工具边界有界拒绝）。机械层不做语义改写（哪项清单对应哪段
    执行归模型判断），只强制回写时机。

    两层状态全从 messages 现推导（无跨调用状态）；本会话从未写清单不提醒不拦
    （不逼聊天类 run 建清单）。拒绝消息对 SSE 不可见（events 翻译只认真实执行
    节点，伪节点注入的 ToolMessage 被跳过——不产生幻影失败卡，前端零改动）。
    """

    def wrap_model_call(self, request, handler):
        msgs = request.messages
        wrote, count, _resume_pending, _base = _todo_baseline(msgs)
        if not wrote or count < _TODO_STALE_THRESHOLD:
            return handler(request)
        tail = msgs[-1]
        if not (isinstance(tail, ToolMessage) and isinstance(tail.content, str)):
            return handler(request)
        note = (
            f"〔系统提醒〕任务清单已 {count} 条消息未更新，与当前实际进度可能脱节；"
            "继续之前先调用 write_todos 把清单回写为真实进度"
            "（已完成标 completed、正在做标 in_progress），再继续当前工作。"
        )
        patched = tail.model_copy(update={"content": f"{tail.content}\n\n{note}"})
        request = dataclasses.replace(request, messages=[*msgs[:-1], patched])
        return handler(request)

    def after_model(self, state, runtime) -> dict | None:
        """清单同步守卫：滞后（或裁决后未回写）的 task 派发整批拒绝。

        放行条件按序短路：state 异常 / 无清单 / 尾部 AIMessage 无 task 调用 /
        同批已带 write_todos（「回写+派发」同轮的常态路径，免重试往返）/ 新鲜 /
        泄压阀已计满。命中才全批拒绝——漏放行半个批=带着旧清单继续执行，守卫
        失效；故必须逐个 task 调用应答，路由层随即跳回模型节点。
        """
        try:
            msgs = state["messages"]
            todos = state.get("todos")
        except Exception:
            return None
        if not isinstance(msgs, list) or not msgs or not todos:
            return None
        try:
            ai = next(m for m in reversed(msgs) if isinstance(m, AIMessage))
            calls = getattr(ai, "tool_calls", None) or []
        except StopIteration:
            return None
        task_calls = [tc for tc in calls if tc.get("name") == "task"]
        if not task_calls or any(tc.get("name") == "write_todos" for tc in calls):
            return None
        wrote, count, resume_pending, base = _todo_baseline(msgs)
        if not wrote:
            return None
        if not resume_pending and count < _TODO_GATE_THRESHOLD:
            return None
        rejects = sum(
            1
            for m in msgs[base + 1:]
            if isinstance(m, ToolMessage)
            and isinstance(m.content, str)
            and _TODO_GATE_MARK in m.content
        )
        if rejects >= _TODO_GATE_VALVE:
            return None
        reason = "你刚收到用户的回答" if resume_pending else f"距上次回写 {count} 条消息"
        text = (
            f"{_TODO_GATE_MARK}任务清单已滞后实际进度（{reason}）。"
            "请先调用 write_todos 把清单回写为真实进度"
            "（已完成标 completed、正在做标 in_progress），再重新派发子代理；"
            "write_todos 可以与派发放在同一轮。"
        )
        return {
            "messages": [
                ToolMessage(
                    content=text,
                    status="error",
                    tool_call_id=tc.get("id") or "",
                    name="task",
                )
                for tc in task_calls
            ]
        }

    async def aafter_model(self, state, runtime) -> dict | None:
        # 基类默认空实现不委托同步版（框架按执行模式择一调用），显式转发
        return self.after_model(state, runtime)


# 思考档位 -> OpenAI 风格 reasoning_effort（标准 API 参数）。模型本身默认开思考，
# 档位只是强度提示，网关/模型按自身能力解释（不依赖网关认真分档）。
THINKING_PAYLOADS: dict[str, dict] = {
    "low": {"reasoning_effort": "low"},
    "medium": {"reasoning_effort": "medium"},
    "high": {"reasoning_effort": "high"},
}


class _RunAwareChatDeepSeek(ChatDeepSeek):
    """按当前 run 的思考档位注入 reasoning_effort 的模型壳。

    档位经 runctx（contextvars）随 run 传播：主 agent 与子代理共用同一实例，
    每次 API 请求构建 payload 时现读档位（并发 run 各在 to_thread 工作线程的
    context 拷贝里互不串扰；实例共享且无状态，线程安全）。titler 是独立实例，
    不经此类，保持模型默认行为。
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        extra = THINKING_PAYLOADS.get(runctx.current_thinking())
        if extra:
            payload.update(extra)
        return payload


# 撞线学习：超限文案里解析服务商披露的真实窗口（纯函数，供测试直击）。
# 只认两种最主流措辞（OpenAI 兼容生态 fact standard，DeepSeek/各网关实测同款），
# 数字限 4-9 位（16K~2M 量级），再按 sanity 区间过滤——宁缺勿错：学到偏大值的
# 最坏情形=间隔很长的重复撞线自愈（非死循环），学到偏小=提前压缩（安全方向）。
_CONTEXT_LIMIT_PATTERNS = (
    "maximum context length is {}",
    "context window is {}",
)
_LEARNED_WINDOW_SANITY = (16384, 2_000_000)


def _parse_context_limit(msg_lower: str) -> int | None:
    import re

    for pattern in _CONTEXT_LIMIT_PATTERNS:
        m = re.search(pattern.format(r"(\d{4,9})"), msg_lower)
        if m:
            value = int(m.group(1))
            if _LEARNED_WINDOW_SANITY[0] <= value <= _LEARNED_WINDOW_SANITY[1]:
                return value
    return None


class _NoThinkingRetryCompletions:
    """网关「思考回传」400 兜底 + 超限 400 归一化 + 撞线学习真实窗口。

    自建网关 2026-08-29 起对思考模式 + 历史含 tool_calls 的冷回放
    （HITL resume 重放 checkpoint 是唯一命中场景；热会话有服务端状态不校验）
    强制要求把历史轮思考内容按 reasoning_text 回传，而其代理层只认
    reasoning/reasoning_content 且实测回传任何字段都无法满足该校验（2026-08-30
    全格式探针证实），唯一穿路是 reasoning_effort="none" 关思考重放。

    挂在 openai SDK 的 chat.completions 资源实例上：langchain _stream/_generate
    都经 client.create(**payload)，撞上该 400 时对当次请求关思考重试一次——只降
    这一跳的思考，下个请求恢复原档位；其余 400 原样上抛。同步路径专用（agent
    全链路 sync stream，async client 未用）。

    超限归一化：各供应商「输入超出上下文窗口」的 400 措辞不一（langchain_openai
    只翻译 context_length_exceeded 等少数几种，其他厂商/网关措辞未必命中），这里
    统一 re-raise 成 langchain_core 的 ContextOverflowError——deepagents 的
    SummarizationMiddleware 捕获它后当场压缩历史并重试，会话不会因超限永久报废。
    未命中标记词的其余 400 记 warning 日志（截断消息），供将来发现新措辞扩表。

    并发闸收口（2026-09-15）：create 的进出点同时是自适应并发闸的 acquire/release
    （429/超时按背压收缩，见 llm_throttle 模块头）——主 agent 与全部子代理共享本
    实例，流式/非流式调用都过这里，是唯一能看见「调用何时开始与结束」的层。
    """

    # 小写化后子串匹配；覆盖 openai 官方（新旧两种报错措辞）/Anthropic/常见网关
    _OVERFLOW_MARKERS = (
        "context_length_exceeded",
        "maximum context length",
        "prompt is too long",
        "input tokens exceed",
        "contextwindowexceedederror",
        "input length and `max_tokens`",
    )

    def __init__(self, inner, on_overflow_window=None, limiter=None):
        self._inner = inner
        # 撞线学习回调（build_agent 注入：写回共享模型实例的 profile）——比例档
        # 压缩中间件每轮活读 model.profile，下一轮即按真实窗口触发/保留
        self._on_overflow_window = on_overflow_window
        # 自适应并发闸（build_agent 注入 per-profile 实例；缺省透传——测试直构
        # 不配速），见 llm_throttle 模块头
        self._limiter = limiter or llm_throttle.NoopLimiter()

    def create(self, **kwargs):
        # 并发闸：进门取许可，出口一次恰好一次归还（one-shot 抢锁——归路有三条：
        # 流耗尽的生成器 finally、with 块 __exit__、显式/GC close，生成器进循环
        # 引用时 GC 关闭可能落在别的线程，与消费线程并发到达；非阻塞抢锁原子，
        # 恰一人成功，Event 先查后设有竞态窗口）。429/超时按背压调闸（hard/
        # soft）、其余异常只归还（neutral）、成功 ok；流式许可持有到流耗尽/
        # 提前关闭——流式 create 立即返回，此刻归还是把闸门架空。
        self._limiter.acquire()
        once = threading.Lock()

        def _release(outcome: str) -> None:
            if once.acquire(blocking=False):  # 首抢者归还，锁不再释放=一次性
                self._limiter.release(outcome)

        try:
            try:
                resp = self._inner.create(**kwargs)
            except BadRequestError as e:
                msg = str(e)
                msg_lower = msg.lower()
                if any(m in msg_lower for m in self._OVERFLOW_MARKERS):
                    logger.warning("上下文超限 400（%.200s），归一化为 ContextOverflowError 走压缩自愈", msg)
                    self._learn_window(msg_lower)
                    raise ContextOverflowError(msg) from e
                if "reasoning_text" not in msg or kwargs.get("reasoning_effort") == "none":
                    logger.warning("模型 400（%.400s）", msg)
                    raise
                logger.warning(
                    "网关思考回传校验 400（reasoning_text），本请求降级 reasoning_effort=none 重试"
                )
                # 内层重试同样可能撞 429/超时——外层 except 对 except 块内抛出的
                # 异常同样生效（sibling except 不接，嵌套一层才接得住）
                resp = self._inner.create(**{**kwargs, "reasoning_effort": "none"})
        except RateLimitError as e:
            _tag_agent_scope(e)
            _release(llm_throttle.HARD)
            raise
        except APITimeoutError as e:
            _tag_agent_scope(e)
            _release(llm_throttle.SOFT)
            raise
        except BaseException as e:
            _tag_agent_scope(e)
            _release(llm_throttle.NEUTRAL)
            raise
        # run 级 token 用量观测：主 agent 与子代理共享本实例，每次响应都过这里
        #（runctx 传播已验证；非 run 态在内部丢弃）。全链路流式——create(stream=True)
        # 返回的是逐块 Stream，usage 只在流吐完后的最后一块（stream_usage=True 让
        # langchain 请求 stream_options.include_usage 服务端才回），故流式包一层、
        # 消费完再记账；非流式（_generate 等）响应自带 .usage 直接取。
        if kwargs.get("stream") and resp is not None and hasattr(resp, "__iter__"):
            return _UsageCapturingStream(resp, on_release=_release)
        _release(llm_throttle.OK)
        try:
            token_usage.record_from_response(resp)
        except Exception:
            logger.debug("token 用量提取失败（不影响主流程）", exc_info=True)
        return resp

    def _learn_window(self, msg_lower: str) -> None:
        """撞线学习：解析真实窗口 → 回调写回共享模型实例 profile（内存态，不落库）。

        「用户没做过的选择不落库」同款铁则：学习只修正本进程内 agent 实例的派生
        档位，settings 存档不动；rebuild（改设置/重启）后回到四层取值序、必要时
        重学，每个进程生命周期最多撞一次线。回调异常不影响归一化主路径。
        """
        if self._on_overflow_window is None:
            return
        learned = _parse_context_limit(msg_lower)
        if learned is None:
            return
        try:
            self._on_overflow_window(learned)
            logger.info("撞线学习：按服务商披露校准上下文窗口为 %d token", learned)
        except Exception:
            logger.debug("撞线学习回调失败（不影响压缩自愈）", exc_info=True)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _UsageCapturingStream:
    """流式响应包装：逐块吐完后从最后一块的 usage 记账 + 并发闸归还。

    langchain 以 `with create(...) as stream: for chunk in stream` 消费，包这一层
    不改变迭代契约，只在流耗尽后取最后一块的 usage（服务端在 include_usage 时于
    末块回 usage）交给 token_usage——观测点从「请求返回」（此刻流未消费、usage 取
    不到）挪到「流消费完」。chunk 可能是 SDK 模型或 dict，防御性两种都取。

    on_release（并发闸归还，2026-09-15）：流式许可必须持有到流真正结束，归看点
    双路覆盖——生成器 finally（耗尽/中途异常/GC close 都会走）与 __exit__（with
    块提前退出还没耗尽时）；注入侧的幂等护栏保证只归还一次。归还**带结果语义**：
    正常吐完=OK（计回升进度），中途异常/提前放弃=NEUTRAL（半途而废不算成功样本）。
    """

    def __init__(self, inner, on_release=None):
        self._inner = inner
        self._on_release = on_release

    def __iter__(self):
        last_usage = None
        exhausted = False
        try:
            for chunk in self._inner:
                usage = getattr(chunk, "usage", None)
                if usage is None and isinstance(chunk, dict):
                    usage = chunk.get("usage")
                if usage is not None:
                    last_usage = usage
                yield chunk
            exhausted = True
            if last_usage is not None:
                try:
                    token_usage.record_usage(last_usage)
                except Exception:
                    logger.debug("token 用量提取失败（不影响主流程）", exc_info=True)
        except BaseException as e:
            # 流中途断连（502/RemoteProtocolError 多发生在这里）：裸 httpx 异常
            # 不经 langchain 包装直穿，抛出点是挂失败源的唯一机会
            _tag_agent_scope(e)
            raise
        finally:
            if self._on_release is not None:
                self._on_release(llm_throttle.OK if exhausted else llm_throttle.NEUTRAL)

    def __enter__(self):
        return self

    def close(self):
        # 显式 close 不走 __getattr__ 委派——否则直接打到内层、绕过 on_release
        # （没人 iter 过就 close 时生成器 finally 不存在，许可会漏）。提前终止
        # 不算成功样本（NEUTRAL）。
        try:
            close = getattr(self._inner, "close", None)
            if close:
                close()
        finally:
            if self._on_release is not None:
                self._on_release(llm_throttle.NEUTRAL)

    def __exit__(self, *exc_info):
        try:
            if hasattr(self._inner, "__exit__"):
                return self._inner.__exit__(*exc_info)
            close = getattr(self._inner, "close", None)
            if close:
                close()
            return False
        finally:
            if self._on_release is not None:
                # with 块带异常退出=半途而废（NEUTRAL）；正常退出（流已耗尽，
                # finally 多半已归还，幂等护栏吃掉）=OK
                self._on_release(
                    llm_throttle.OK if not (exc_info and exc_info[0]) else llm_throttle.NEUTRAL
                )

    def __getattr__(self, name):
        return getattr(self._inner, name)


# 上下文窗口取值优先序的兜底层（前两层：用户手选 > langchain_deepseek 注册表已知名）：
# 未知模型名统一给 17 万保守档并**进入比例模式**（85% 触发/保留 10%）——此前 profile
# 为 None 时 deepagents 走「17 万固定线+保留 6 条消息」，撞线学习校准 profile 后无法
# 回馈档位（构造时已定死）；预设了 max_input_tokens 后比例档每轮活读 profile，
# 学习立即生效（详见 model_registry 模块头与 _NoThinkingRetryCompletions 撞线学习）。
_FALLBACK_WINDOW_TOKENS = 170_000

# 摘要调用输入上限（token）：deepagents 工厂默认 trim=None——压缩触发时摘要生成
# 单发**全部**被逐出历史（≈窗口 75%，1M 模型一次 75 万 token，XML 序列化不吃前缀
# 缓存全价新鲜计费）。设 200K 上限后摘要只 recap 最近一段；完整历史仍落盘
# conversation_history（摘要消息内嵌文件路径可 read_file 回看，信息不丢）。窗口
# ≤256K 时逐出 ≈192K < 上限，行为与库默认一致——上限只对大窗口生效。
_SUMMARY_INPUT_CAP = 200_000


def _apply_window_profile(model, p: cfg.ModelProfile) -> None:
    """上下文窗口四层取值，就地合并进 model.profile（保留注册表能力键）。

    1. 用户手选（p.context_window，设置 → 模型 → 高级选项，存档真值）
    2. langchain_deepseek 注册表已知名（profile 自带窗口）→ 不动
    3. models.dev 社区注册表本地缓存命中（model_registry.lookup，零联网）
    4. 保守默认 17 万（比例档起步；真实窗口更小则撞一次线后由撞线学习校准）
    """
    if p.context_window:
        model.profile = {**(model.profile or {}), "max_input_tokens": p.context_window}
        return
    profile = model.profile
    if isinstance(profile, dict) and isinstance(profile.get("max_input_tokens"), int):
        return
    window = model_registry.lookup(p.model) or _FALLBACK_WINDOW_TOKENS
    model.profile = {**(profile or {}), "max_input_tokens": window}


def _make_summarization_middleware(model, backend) -> SummarizationMiddleware:
    """压缩中间件自建实例：复刻库工厂的模型感知默认档，仅改摘要输入上限。

    同名替换机制（deepagents 官方支持）：本实例 .name 恰为 "SummarizationMiddleware"，
    经 create_deep_agent 的 _apply_custom_middleware **原地顶掉**内置件并占其原栈位
    （主 agent middleware= 与 SubAgent spec 的 middleware 列表同机制；自动补的
    general-purpose 按名字继承主栈同名件）——不 monkey-patch、不 exclusion。
    """
    defaults = compute_summarization_defaults(model)
    return SummarizationMiddleware(
        model=model,
        backend=backend,
        trigger=defaults["trigger"],
        keep=defaults["keep"],
        trim_tokens_to_summarize=_SUMMARY_INPUT_CAP,
        truncate_args_settings=defaults["truncate_args_settings"],
    )


def build_agent(profile: cfg.ModelProfile | None = None):
    """按模型 profile 构造 DeepAgents 实例（profile=None 走 default profile）。

    settings 变更后调用 rebuild_agent()（清缓存，按 profile 惰性重建）。
    """
    p = profile or cfg.get_profile(cfg.default_model_id())
    if p is None:
        # 模型列表为空（用户删光）：给出人话错误；agent 缓存不落空值，
        # 下次带 profile 的调用还会重试（settings 改回即自愈）
        raise AgentConfigError("未配置任何模型（设置 → 模型 → 添加模型）")
    api_key = cfg.model_key(p.id)
    if not api_key:
        raise AgentConfigError(
            f"模型「{p.name}」未配置 API Key（设置 → 模型 → 填写并保存即生效）"
        )

    # ChatDeepSeek 会提取 DeepSeek 的 reasoning_content 到 additional_kwargs，
    # events._chunk_reasoning 据此发 agent.reasoning（非推理模型下与 ChatOpenAI 行为一致）。
    # 思考档位按 run 注入（reasoning_effort），见 _RunAwareChatDeepSeek。
    model = _RunAwareChatDeepSeek(
        api_key=api_key,
        base_url=p.base_url,
        model=p.model,
        timeout=180,
    )
    # 流式请求必须带回 usage：langchain 只在默认 base_url / LangSmith 网关下默认开
    # stream_usage（自定义 base_url 默认关），不开则不带 stream_options.include_usage、
    # 服务端不回 usage——run 级 token 用量统计（_UsageCapturingStream）就拿不到数。
    model.stream_usage = True
    # 上下文窗口四层取值（用户手选 > DeepSeek 注册表 > models.dev 缓存 > 保守默认），
    # 必须先于压缩中间件构造——deepagents 的默认档在构造时按 profile 有无定比例/固定
    _apply_window_profile(model, p)
    # 网关思考回传 400 兜底 + 超限归一化 + 撞线学习（client 是 init 时缓存的 SDK
    # 资源实例字段，直接换成交包装层；学习回调写回本实例 profile，下轮即生效）
    def _learn_overflow_window(window: int) -> None:
        model.profile = {**(model.profile or {}), "max_input_tokens": window}

    # 客户端自适应并发闸（AIMD，2026-09-15）：用户网关并发额度不可知，429/超时
    # 按背压自动收缩、连续成功缓慢回升（见 llm_throttle 模块头）；per-profile
    # 注册表共享——跨 run 同 profile 互护，rebuild 不清（纯运行态）
    limiter = llm_throttle.for_profile(p.id, ceiling=_MAX_CONCURRENT_STEPS)
    model.client = _NoThinkingRetryCompletions(model.client, on_overflow_window=_learn_overflow_window, limiter=limiter)
    # 写保护后端：通用文件工具对来源/产物包/谱系暂存/归档/技能目录只读（fs_guard）
    # ——读完全放开，work/ 下过程文件（parse/analysis/outline/body）正常可写
    backend = GuardedBackend(root_dir=str(cfg.workspace_dir()))
    # 压缩中间件自建实例（摘要输入上限 200K，见 _SUMMARY_INPUT_CAP）：主栈与两个
    # SUBAGENTS 条目经同名替换顶掉内置件；general-purpose 自动继承主栈同名件
    summ = _make_summarization_middleware(model, backend)

    agent = create_deep_agent(
        model=model,
        backend=backend,
        tools=TOOLS,
        subagents=[{**spec, "middleware": [summ, *spec["middleware"]]} for spec in SUBAGENTS],
        skills=["skills/"],  # 未加载时在 main 启动日志提示换写法（见 README）
        # 子代理归属插桩；todos 工具；任务清单陈旧提醒（波次循环里模型不回写
        # 清单→面板数小时停在旧阶段，2026-09-13）；任务上下文按 run 注入；
        # task 子代理异常收敛
        # （deepagents 内置工具不守「失败返回错误字符串」纪律，无此层时子代理
        # 永久错误会打死整个主 run——见 _task_failure_content）；文件工具路径自愈
        # （子代理各自 ToolNode 独立，故 SUBAGENTS 条目里还挂了一份）；tender-body-writer
        # 派发说明程序拼装（治「派发塌成节名五字→子代理开局自救烧 token」，
        # 见 dispatch_enrich 模块头）；本地重工具超时封顶（治卡死工具拖死 run，
        # 子代理同样直接调 docx 族工具故 SUBAGENTS 条目里还挂了一份）
        middleware=[
            summ,
            _SubagentTagMiddleware(),
            TodoListMiddleware(),
            _TodoFreshnessMiddleware(),
            _TaskContextMiddleware(),
            ToolErrorMiddleware(on_error=_task_failure_content, tools=["task"]),
            _PATH_RESCUE_MW,
            _REPLAY_GUARD_MW,
            _DISPATCH_ENRICH_MW,
            _TOOL_TIMEOUT_MW,
        ],
        system_prompt=(
            "你是标书助理，在一个投标任务下的会话里工作。产物归任务、单一当前版本："
            "同契约在任务内只有一份当前内容，重跑覆盖前系统自动留恢复点，"
            "你不需要维护版本状态。"
            "方法论在 skills 目录中，按各技能的 SKILL.md 执行（技能清单见下方列表，"
            "执行前先读对应 SKILL.md）：解析招标文件（文件→Markdown）用 document-parse；"
            "系统性提取投标要点用 tender-analysis；生成投标目录用 tender-outline；"
            "编写响应文件正文用 tender-body；"
            "就招标文件回答单个具体问题用 tender-qa；"
            "去除文本中的 AI 写作痕迹、让中文读起来更自然用 humanizer-zh。"
            "环节衔接：要点提取（tender-analysis）完成后必须停下——收尾汇报摆出"
            "关键要点与待澄清清单、提醒用户查看，本轮结束；即使用户的原始请求"
            "覆盖后续环节（如「帮我把标书做出来」）也不要自动生成投标目录，"
            "用户回复继续后再走 tender-outline。正文开工的两份确认件（写作指引、"
            "关键事实与承诺）同样：每份生成后汇报要点与缺口清单、停下等用户回复"
            "继续或给出承诺值，不用 ask_human 提问。"
            "向用户介绍能力、流程或产物时只说你确定的内容，不虚构具体章节名、"
            "步骤名、字段名；没读技能文件前说到概括层（如「按招标文件结构提取"
            "七个方面的要点」）。用户请求你没有的能力时，如实说明做不到并指出"
            "最接近的可行做法，不要发明替代路径凑合执行。"
            "用户上传的文件在当前任务工作目录的 sources/ 下（任务目录前缀见任务上下文，"
            "如 <任务目录>/sources/招标文件.docx）。"
            "资料词汇表——以下各词与日常语义不同，严格按此区分：知识库=公司事实"
            "（资质/案例/业绩）；写作素材库=用户手工挑选的章节素材块（内容资产，"
            "供拷贝改写）；版式库=纯版式资产（原「模板库」），只决定之后新建节与"
            "重新合册的样式，不改已写节的内容；版式库现状（数量/默认版式）用"
            " list_templates 工具查询（版式文件在任务工作区之外，不要用文件工具"
            "检索）。不存在「把版式应用到整本/已写章节」的工具：被这样"
            "要求时如实说明，可行做法是先在版式库把版式设为默认、再重新生成整本；"
            "不要把素材库文件当「模板」候选、不要发明路径。招标文件自带的格式模板"
            "（投标函/授权书等格式件）是招标方要求的格式，不属于版式库或素材库。"
            "临时参考件=用户上传 sources/ 并明说「参考/照着写」的非招标文件（类似"
            "案例/范文）：当写法参考用（parse_document 读取后按 outline 行号取"
            "区段，用法纪律见 tender-body），不当招标来源重新走来源确认，也不进"
            "素材库/知识库。"
            "引用结构化成果（如投标目录）时用 read_artifact 按契约读取当前内容，"
                "不要猜文件路径；中途想保存的未登记内容以 doc.note 笔记保存。"
                "完成阶段性工作后用 update_task_progress 更新任务进度便签（保持简短）。"
                "输出纪律：调用工具的那一轮，正文只写一句以内的当前动作说明"
                "（如「读取评分办法」），面向用户说清要做什么，不复述工具用法、"
                "输出格式等内部规则，也不展开计划、不罗列备选方案；"
                "完整的进展与结论只在最终回复（不再调用工具的那一轮）给出。"
                "任务清单（write_todos）是给用户的进度承诺：收尾汇报前把清单回写为"
                "真实终态——已完成项标 completed，确未做的如实保留 pending 并在最终"
                "回复说明原因；不要把半程状态的清单留给用户。阶段切换时也要回写："
                "用户裁决续跑后的第一轮、整本逐节生成每波派发前，把清单更新为当前"
                "真实进度，不要等收尾。"
                "派发子代理（task）时，description 第一行只写短名本身——不超过 16 字、"
                "概括该子代理的任务（如「检索中石化 dify 相关招标」），不要以「你是……」"
                "之类的角色自述开头，并发派发时各卡短名要能相互区分；详细任务说明从"
                "第二行开始。"
                "task 返回失败（子代理执行错误）时重派一次；仍失败则在最终回复"
                "向用户说明哪部分未完成，不要静默跳过。"
                "面向用户的回复用用户语言：内部路径（sources/、work/、任务目录前缀）与"
                "实现名词（工具名、文件名如 sources.json、子代理、run）不进回复，"
                "它们是你操作用的知识、不是用户的操作入口；汇报进度与状态按业务阶段"
                "说（文件是否上传、解析/要点提取/目录的进展），不要用目录状态与技能"
                "名拼进度清单；细则见"
                " skills/_shared/response-guidelines.md，执行业务技能时先读它。"
                "最终回复按「结果 → 影响/风险 → 下一步」组织；需要用户行动时只突出"
                "一个主要动作，备选路径放次要位置；结尾不用「你想先做哪一步？」式反问"
                "把选择抛回给用户，点出建议动作即可。"
                "回复显示在聊天界面、按 Markdown 渲染：结论先行，清单、对比、状态等"
                "可枚举内容用列表或表格组织，不写成无结构长段落；简单问题三五句话"
                "答完即可，不复述用户已知信息、不展开过程流水账（汇报类回复该详尽"
                "则详尽）。不用 emoji，不用「好的」「当然可以」式寒暄开头。"
                "排版细则见 skills/_shared/response-guidelines.md。"
                "缺少关键信息（如资质材料、报价策略）或遇到需要用户拍板的取舍时，"
                "用 ask_human 向用户提问，不要自行猜测；可以明确推断的小事不要问。"
                "需要用户在候选项里挑选时，把选项放进 options（「；」分隔）并按是否"
                "允许多选设置 multiple，用户点选与补充文字会一并作为回答回传。"
                "候选项与 guide_path 只写进各自参数，不要在 question 里写"
                " options=…、guide_path=… 赋值行——会原样显示且按钮不渲染。"
        ),
        checkpointer=_get_saver(),
        interrupt_on=INTERRUPT_ON,
    )
    return agent


async def get_agent(profile_id: str | None = None):
    """取（惰性构建）指定 profile 的 agent；None 走 default profile。

    in-flight run 各持 agent 引用互不影响；saver/checkpointer 全局共享线程安全；
    子代理在 deepagents 侧继承同一 model 实例（spec 未指定 model 时）。
    """
    pid = profile_id or cfg.default_model_id()
    async with _agent_lock:
        agent = _agents.get(pid)
        if agent is None:
            agent = await asyncio.to_thread(build_agent, cfg.get_profile(pid))
            _agents[pid] = agent
        return agent


async def rebuild_agent():
    """模型列表/配置变更后清空 agent 缓存（按 profile 惰性重建，不再预构建）。"""
    async with _agent_lock:
        _agents.clear()


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
    """在步骤树里按 tool_call_id（缺省退化按工具名）找可回填的步骤。

    可回填 = running / paused（HITL 续跑段经 _seed_resume_trace 承接的暂停
    ask_human 步骤，段首代答 tool.result 到达时照常回填，与前端 fillStep 同口径），
    或 error 但 error 是断流重试标记（2026-09-10 review：
    tools 节点失败的瞬时错误（子代理 LLM 断流上抛）重试时 langgraph 以同
    tool_call_id 复跑该工具调用——_retire_broken_steps 先行标死的步骤必须允许
    被真实 tool.result 覆写，否则重试成功后步骤永久显示「LLM 流中断」，而复用
    同 id 的子代理新事件又挂在同一张卡下、自相矛盾。按名退化匹配不放开到
    error 态——同工具名多步骤时可能复活错步骤）。"""
    for s in reversed(steps):
        tcid = payload.get("tool_call_id")
        revivable = s["status"] in ("running", "paused") or (
            bool(tcid) and s["status"] == "error" and s.get("error") == _RETRY_RETIRED_ERROR
        )
        if revivable:
            if tcid and s.get("tool_call_id") == tcid:
                return s
            if not tcid and s["tool"] == payload["tool"]:
                return s
        hit = _find_pending(s["children"], payload)
        if hit is not None:
            return hit
    return None


def _revive_step(top_steps: list[dict], payload: dict) -> dict | None:
    """按 tool_call_id 找已有步骤并复活为 running（tools 节点重试复用同 id 重新
    执行时，该步骤可能已被断流收尾标成 error；不复活则 trace 里出现两张同 id 卡）。

    只认断流假终态（error==标记）——done/真实 error 的同 id 重发不复活（防杂散
    重复事件把已完成步骤拖回运行中）。复位仅执行态字段（status/error/summary/
    endedAt/startedAt）——text/reasoning 是第一次调用的封段产物，覆写会丢旁白；
    cur_* 缓冲也不动（重试后的新旁白归下一次 tool.called 封段）。"""
    tcid = payload.get("tool_call_id")
    if not tcid:
        return None
    for s in top_steps:
        if (
            s.get("tool_call_id") == tcid
            and s["status"] == "error"
            and s.get("error") == _RETRY_RETIRED_ERROR
        ):
            s["status"] = "running"
            s["error"] = None
            s["summary"] = ""
            s["endedAt"] = None
            s["startedAt"] = int(time.time() * 1000)
            return s
        hit = _revive_step(s["children"], payload)
        if hit is not None:
            return hit
    return None


# 断流重试收尾的标记文案（_retire_broken_steps 落、_find_pending/_revive_step 据
# 此识别可覆写/复活的假终态——tools 节点失败重试会复用同 tool_call_id 真实执行）
_RETRY_RETIRED_ERROR = "LLM 流中断，已自动重试"

# 重试失败源归属（2026-09-15 重试可见性批）：LLM 调用异常在**抛出点**挂上
# main/sub——_SubagentScopeMiddleware 的 finally 在异常穿到 worker 前已复位
# contextvar，worker 侧读不到当前值，只能在作用域还在的抛出点挂到异常对象上；
# worker 经 _exc_agent_scope 沿 __cause__ 链读回（langchain 包装统一
# `raise ... from e`，cause 链保留；裸 httpx 断流不经包装、抛出点直挂）。
# 去向=agent.retry 载荷（additive scope 字段）+ llm_retry 伪步骤——用户可见
# 「这次重试断在主线程还是子代理」。
_SCOPE_LABELS = {"main": "主线程", "sub": "子代理"}


def _tag_agent_scope(exc: BaseException) -> None:
    try:
        exc._tender_agent_scope = runctx.current_scope()
    except Exception:
        pass  # 归属是观测增强，任何失败都不影响异常主路径


def _exc_agent_scope(exc: BaseException) -> str:
    cur, depth = exc, 0
    while cur is not None and depth < 8:
        scope = getattr(cur, "_tender_agent_scope", None)
        if scope in ("main", "sub"):
            return scope
        cur = cur.__cause__
        depth += 1
    return "main"  # 无标记（不经模型包装层的异常/旧路径）按主线程


def _llm_retry_step(attempt: int, err: str, backoff: float, scope: str = "main") -> dict:
    """断流自动重试的 trace 伪步骤（复用步骤 dict 形状，随 run_traces 落库，
    历史回放可见重试发生过；前端零改动，按普通步骤渲染）。scope=失败源
    （主线程/子代理），历史 trace 行直接可读。"""
    now = int(time.time() * 1000)
    label = _SCOPE_LABELS.get(scope, scope)
    return {
        "id": f"llm_retry@{now}",
        "tool": "llm_retry",
        "args": {"attempt": attempt, "error": err[:300], "backoff_s": backoff, "scope": scope},
        "status": "done",
        "summary": f"LLM 流式连接中断，{backoff:.0f}s 后从断点自动重试（第 {attempt} 次 · {label}）",
        "error": None,
        "tool_call_id": None,
        "reasoning": "",
        "text": "",
        "children": [],
        "startedAt": now,
        "endedAt": now,
    }


def _retire_broken_steps(top_steps: list[dict], rid: str, cid: str, _publish) -> None:
    """断流重试前把残留的 running 步骤收尾为终态——失败那轮的 tool 调用实际未执行
    （流中断在工具节点之前），重试会以全新 tool_call_id 重新发起，旧步骤不收尾会
    在 trace 历史里永远转圈。顶层步骤同步补发 tool.result（error）让前端实时卡片收敛；
    子代理 children 只改状态不发事件（agent_id 不在步骤里、且父卡已收敛）。

    已知边界（2026-09-10 review 收口）：tools 节点失败的瞬时错误（子代理 LLM 断流
    上抛）重试会**复用同 tool_call_id** 复跑——此前的假终态由 _find_pending（放宽
    回填）与 _revive_step（同 id tool.called 复活）接住覆写，不再永久错标。"""
    now = int(time.time() * 1000)

    def mark(step: dict) -> None:
        if step["status"] == "running":
            step["status"] = "error"
            step["error"] = _RETRY_RETIRED_ERROR
            step["endedAt"] = now
        for c in step["children"]:
            mark(c)

    for s in top_steps:
        was_running = s["status"] == "running"
        mark(s)
        if was_running:
            _publish(
                events.EVENT_TOOL_RESULT,
                {
                    "run_id": rid,
                    "conversation_id": cid,
                    "tool": s["tool"],
                    "summary": s["error"],
                    "error": s["error"],
                    "tool_call_id": s.get("tool_call_id"),
                    "agent_id": None,
                },
            )


def _run_agent_stream(
    agent, cid: str, rid: str, task_id: str | None, _publish, user_text: str | None, resume_decisions: list | None,
    cancel_event: threading.Event | None = None, thinking: str = "low",
    resume_payload: dict | None = None, continue_from_checkpoint: bool = False,
) -> tuple[str, str | None, str | None, dict, dict | None]:
    """worker 线程里跑完整流，逐块实时回调 _publish(event, data)。

    首段（user_text）与续段（resume_decisions，Command(resume=...) 从 checkpoint
    的 interrupt 处续跑）共用本函数；continue_from_checkpoint=True 是终态断点续跑
    （2026-09-12）：input=None 与断流重试同款——langgraph 从 checkpoint 恢复 pending
    任务只重跑未完成节点，上一段遗留的悬空 tool_calls 由 PatchToolCallsMiddleware
    在开头补插取消 ToolMessage 自愈。返回 (assistant_text, error, error_code, trace,
    interrupt)：assistant_text 是**最终回复**（最后一段未被 tool.called 跟随的正文）；
    此前各轮的正文旁白在 tool_called 到达时封段挂到对应 trace 步骤的 text 字段
    （过程/结果分通道，前端 useRun 用同一条封段规则，SSE 契约零改动）。
    error_code 是错误定性（llm_unavailable/llm_auth/internal/cancelled，2026-09-08
    契约 additive——前端据此区分「模型服务的错」与「程序的错」并给人话文案）。
    interrupt 非空 = HITL 暂停（events 归一化的 {"requests": [...]}），本段流到此
    结束、run 转入 waiting_input，等用户裁决后由 run_stream 再开一段续流。
    trace 是本次 run 的执行过程快照：顶层工具步骤树（task 步骤含子代理 children
    与 reasoning）+ 最新 todos + 主 agent 思考流整段（reasoning 键，随 run_traces
    落库供历史「深度思考」渲染），run 结束时由 run_stream 落库 run_traces。

    cancel_event 非空且被置位 = 用户请求停止：在每个流事件边界协作式退出
    （LLM 流式调用期间 token 事件持续到达，停止会在下一个事件处生效；
    长工具执行中则等工具返回），退出走 error 路径（半截回复落库 + run 标 error）。

    瞬时 LLM 错误（_is_llm_transient：langchain 包装的连接断开/超时/限流 + 流式断连的
    裸 httpx.RemoteProtocolError 与消息关键词兜底）自动从 checkpoint 断点
    重试（最多 _LLM_RETRY_BACKOFFS 次）：重试时 input=None，langgraph 恢复 pending
    任务只重跑失败节点；失败那轮的半截正文清空（重试会完整重流出）并先发 agent.retry
    事件（前端同样清空未封口正文、显示「正在自动重试」shimmer——半截 token 不再
    重复出现）；残留 running 步骤收尾为 error；每次重试在 trace 里留 llm_retry 伪
    步骤。重试额度用尽仍失败才走 error 路径（llm_unavailable + 人话文案带原文）。
    """
    # run 上下文随 context 拷贝进入本线程：工具据此记录产物来源与作用域，
    # _TaskContextMiddleware 据此注入任务上下文，模型壳据此注入思考档位（同线程同一份 context）
    runctx.set_run(cid, rid, task_id, thinking)
    if resume_payload is not None:
        # 多中断恢复（langgraph 要求 {interrupt_id: value} 映射；api/runs.py 按
        # 快照里的 interrupt_id 分组组装）——单中断旧格式仍走 resume_decisions
        stream_input: object = Command(resume=resume_payload)
    elif resume_decisions is not None:
        stream_input = Command(resume={"decisions": resume_decisions})
    elif continue_from_checkpoint:
        stream_input = None
    else:
        stream_input = {"messages": [("user", user_text or "")]}
    # 正文按轮次分段：cur_text_parts 是当前未封口段；主 agent 的 tool_called 到达即
    # 封口为旁白（挂该步骤 text），run 结束时最后未封口段 = 最终回复。
    cur_text_parts: list[str] = []
    # 主 agent 思考流按轮分段：reasoning 先于它催生的 tool_called 到达，tool_called
    # 到达即封口挂该步骤 reasoning（与旁白封段同一条规则；同轮连发多调用只有首个带），
    # run 结束时最后未封口段 = 最终回复前的思考，随 trace 落 run_traces.reasoning。
    # 子代理 reasoning 走 sub_reasoning_bufs 缓冲（dict STORE_SUBSCR += 每 chunk 整串
    # 拷贝，长思考是 O(n²)），结构性事件/段收尾经 _sync_sub_reasoning 统一 join 落值。
    cur_reasoning: list[str] = []
    sub_reasoning_bufs: dict[str, list[str]] = {}
    error = None
    error_code: str | None = None
    top_steps: list[dict] = []
    last_todos: list = []
    if resume_decisions is not None or resume_payload is not None or continue_from_checkpoint:
        # 续跑段（HITL 裁决 / 断点继续）先承接既有 run_traces 行的步骤树与 todos：
        # 暂停段留下的 paused ask_human 步骤只存在于旧行，本段流开头 HITL 伪节点
        # 下发的「代答」tool.result（events._HITL_NODE_PREFIX 放行）要能经
        # _find_pending 回填它，段尾 _save_merged_trace 才把「已答 + 用户回答」落进
        # 最终 trace——否则步骤永远 paused、历史问答组缺「你的回答」。断点继续路径
        # 同样受益：活树快照与续段 trace 不再只剩本段步骤（2026-09-12）。
        prior = _seed_resume_trace(rid)
        top_steps, last_todos = prior
    interrupt: dict | None = None
    n_retries = 0
    try:
        attempt_input: object = stream_input
        while True:
            try:
                stream = agent.stream(
                    attempt_input,
                    config={
                        "configurable": {"thread_id": cid},
                        "max_concurrency": _MAX_CONCURRENT_STEPS,
                    },
                    stream_mode=["messages", "updates"],
                    subgraphs=True,  # 子代理内部事件浮现父流；events.iter_stream 按 ns 归属
                )
                for kind, payload in events.iter_stream(stream, rid):
                    if cancel_event is not None and cancel_event.is_set():
                        error = events.CANCELLED_MESSAGE
                        error_code = "cancelled"
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
                            sub_reasoning_bufs.setdefault(payload["agent_id"], []).append(payload["text"])
                        else:
                            cur_reasoning.append(payload["text"])
                        # reasoning chunk 是 token 级高频事件：不在此处更新快照（逐 chunk
                        # 全树 deepcopy 会拖慢 worker），reasoning 随下一个结构性事件入库
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
                        # 先尝试复活（tools 节点断流重试复用同 tool_call_id 重新执行，
                        # 此前步骤可能已被假终态标死）；复活不动封段字段与 cur_* 缓冲
                        step = _revive_step(top_steps, payload)
                        if step is None:
                            step = _new_trace_step(payload)
                            if not payload.get("agent_id"):
                                # 主 agent 调用：把之前流出的正文封为旁白、思考流封为本步
                                # 骤的 reasoning（同轮连发的后续调用两者均为空串）；子代理
                                # 调用不封段（其正文 token 不透传，reasoning 走 agent_id 归属）
                                step["text"] = "".join(cur_text_parts)
                                cur_text_parts.clear()
                                step["reasoning"] = "".join(cur_reasoning)
                                cur_reasoning.clear()
                            _attach_step(top_steps, step, payload.get("agent_id"))
                        _sync_sub_reasoning(top_steps, sub_reasoning_bufs)
                        set_live_trace(
                            rid,
                            {"tools": top_steps, "todos": last_todos, "reasoning": "".join(cur_reasoning)},
                        )
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
                        _sync_sub_reasoning(top_steps, sub_reasoning_bufs)
                        set_live_trace(
                            rid,
                            {"tools": top_steps, "todos": last_todos, "reasoning": "".join(cur_reasoning)},
                        )
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
                        _sync_sub_reasoning(top_steps, sub_reasoning_bufs)
                        set_live_trace(
                            rid,
                            {"tools": top_steps, "todos": last_todos, "reasoning": "".join(cur_reasoning)},
                        )
                    elif kind == "interrupt":
                        # HITL 暂停：流到此为止，run_stream 落半截消息并转 waiting_input
                        interrupt = payload
                        break
                break  # 流耗尽或 interrupt/cancel 中断内层循环 → 本段结束
            except Exception as e:
                if not _is_llm_transient(e):
                    raise  # 永久错误（认证/参数等）：交外层统一落 error
                # 瞬时断流：重试以 input=None 从 checkpoint 恢复 pending 任务（成功节点
                # 的写入已提交，只重跑失败的那个节点）
                if cancel_event is not None and cancel_event.is_set():
                    error = events.CANCELLED_MESSAGE
                    error_code = "cancelled"
                    break
                if n_retries >= len(_LLM_RETRY_BACKOFFS):
                    error = (
                        f"模型服务暂时不可用，已自动重试 {n_retries} 次仍失败，请稍后重试。\n"
                        f"服务方返回：{str(e)[:300]}"
                    )
                    error_code = "llm_unavailable"
                    logger.error("agent 流重试耗尽（cid=%s rid=%s）：%s", cid, rid, e)
                    break
                backoff = _jittered_backoff(_LLM_RETRY_BACKOFFS[n_retries])
                n_retries += 1
                failure_scope = _exc_agent_scope(e)
                logger.warning(
                    "agent 流瞬时错误，%.0fs 后从 checkpoint 断点重试（第 %d 次）：%s",
                    backoff, n_retries, e,
                )
                # 重试可见（契约 additive 2026-09-08）：等待期前端在输出区显示
                # 「正在自动重试」shimmer，并同时清空未封口正文（与本函数
                # cur_text_parts.clear() 对齐，重流出后半截 token 不重复）；
                # scope=失败源（additive 2026-09-15），前端文案区分主线程/子代理
                _publish(
                    events.EVENT_AGENT_RETRY,
                    events.retry_payload(
                        rid, cid, n_retries, len(_LLM_RETRY_BACKOFFS), backoff, scope=failure_scope
                    ),
                )
                # 失败那轮的半截正文清空（重试会完整重流出，保留会拼进最终回复）；
                # reasoning 不清（跨轮累积，只可能尾部多一小段重复，展示层瑕疵无害）
                cur_text_parts.clear()
                _retire_broken_steps(top_steps, rid, cid, _publish)
                top_steps.append(_llm_retry_step(n_retries, str(e), backoff, failure_scope))
                if cancel_event is not None and cancel_event.wait(timeout=backoff):
                    error = events.CANCELLED_MESSAGE
                    error_code = "cancelled"
                    break
                attempt_input = None
        # cancelled 判定在 worker 内完成（error_code 直接产出），run_stream 不再做
        # 字符串比对
    except Exception as e:  # 永久错误（认证/参数）与其他意外错误：不重试
        logger.exception("agent stream failed")
        if not error:
            # 异常与取消竞态（含 _ToolCancelledError：取消感知 middleware 从工具等待中
            # 抛出）——cancel 已置位时按 cancelled 收尾，不误归类 internal/llm_auth
            if cancel_event is not None and cancel_event.is_set():
                error_code, error = "cancelled", events.CANCELLED_MESSAGE
            else:
                error_code, error = _classify_error(e)
    finally:
        clear_live_trace(rid)
        runctx.clear_run()
        events.clear_subagent_registry(rid)
    # 最终回复 = 最后未封口段（未被 tool.called 跟随）；旁白已挂在 trace 步骤 text 上
    _sync_sub_reasoning(top_steps, sub_reasoning_bufs)
    return (
        "".join(cur_text_parts),
        error,
        error_code,
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


def _pause_snapshot(text: str, tools: list[dict]) -> tuple[str, list[dict]]:
    """interrupt/error 半截回复快照：优先最终回复段，空则用最后一段旁白兜底。

    兜底时同步把该段旁白从 trace 步骤 text 中清空——同一句话不既当落库消息正文
    又在 trace 旁白行里重复渲染（2026-08-29 实测发现的双写）。
    """
    if text.strip():
        return text, tools
    narration = _last_narration(tools)
    if not narration:
        return "", tools
    stripped = [
        {**s, "text": ""} if s.get("text") == narration else s for s in tools
    ]
    return narration, stripped


def _iter_trace_steps(steps: list[dict]):
    for s in steps:
        yield s
        yield from _iter_trace_steps(s.get("children") or [])


def _sync_sub_reasoning(top_steps: list[dict], bufs: dict[str, list[str]]) -> None:
    """把子代理思考缓冲 join 落值到对应 task 步骤。落值点=结构性事件快照与段收尾
    （live 快照语义不变：reasoning 本就随下一个结构性事件入库），chunk 级只 append。"""
    if not bufs:
        return
    for s in _iter_trace_steps(top_steps):
        if s.get("tool") == "task":
            buf = bufs.get(s.get("tool_call_id"))
            if buf is not None:
                joined = "".join(buf)
                # 收敛为单元素：保留后续 chunk 追加的增量 join 语义，同时避免
                # chunk 列表与拼好串双份驻留整个 run（join 复用同一字符串对象）
                buf[:] = [joined]
                s["reasoning"] = joined


def _merge_trace_trees(old: list[dict], new: list[dict]) -> list[dict]:
    """续跑段收尾时与暂停段步骤树合并：同 step.id（tool_call_id）以新段副本就地替换。

    被门禁拦下的调用在续跑段重发时携带同一 tool_call_id（langgraph 复用原 AIMessage），
    新副本是终态（含子代理 children），替换旧树里的 paused 冻结副本；新段增量按序
    追加。替换时新副本的 text/reasoning 为空则回退旧值——重发的 tool.called 在新段
    开场即到、其封段字段必为空串，暂停前封下的旁白/思考不能因此丢失。保证同一 run
    跨暂停/续跑只有一棵连续的执行过程树。
    """
    old_ids = {s.get("id") for s in _iter_trace_steps(old) if s.get("id")}
    repl = {s["id"]: s for s in _iter_trace_steps(new) if s.get("id") in old_ids}

    def with_fallback(new_step: dict, old_step: dict) -> dict:
        merged = new_step
        for field in ("text", "reasoning"):
            if not merged.get(field) and old_step.get(field):
                merged = {**merged, field: old_step[field]}
        return merged

    def swap(steps: list[dict]) -> list[dict]:
        out = []
        for s in steps:
            sid = s.get("id")
            if sid in repl:
                out.append(with_fallback(repl[sid], s))
                continue
            children = s.get("children") or []
            out.append({**s, "children": swap(children)} if children else s)
        return out

    merged = swap(old)
    merged.extend(s for s in new if s.get("id") not in old_ids)
    return merged


def _save_merged_trace(
    rid: str,
    cid: str,
    message_id: str | None,
    trace: dict,
    duration_ms: int | None,
    files: list | None = None,
) -> None:
    """落 trace 前与既有行合并（同 run 暂停->续跑不再整行覆盖丢暂停段）。

    message_id 新值优先；新段无产出（error 半截 message_id=None）时保留旧值，
    暂停消息继续挂全程 trace。reasoning 拼接、duration 累加（分段计时之和≈全程）。
    files 是本段 work/ 变更 diff：None（无任务/探测失败）保留旧值，否则与旧段
    合并（任一分段新建过即 created，见 run_files.merge_files）。
    """
    existing = db.get_run_trace(rid)
    if existing is None:
        db.save_run_trace(
            rid, cid, message_id, trace["tools"], trace["todos"], duration_ms,
            trace.get("reasoning", ""), files=files,
        )
        return
    merged_tools = _merge_trace_trees(existing.get("tools") or [], trace["tools"])
    old_reasoning = existing.get("reasoning") or ""
    new_reasoning = trace.get("reasoning", "")
    reasoning = f"{old_reasoning}\n{new_reasoning}" if old_reasoning and new_reasoning else (old_reasoning or new_reasoning)
    merged_duration = (existing.get("durationMs") or 0) + (duration_ms or 0)
    merged_files = run_files.merge_files(existing.get("files"), files)
    db.save_run_trace(
        rid, cid, message_id or existing.get("message_id"), merged_tools,
        trace["todos"], merged_duration, reasoning, files=merged_files,
    )


def _seed_resume_trace(rid: str) -> tuple[list[dict], list]:
    """续跑段起步时承接既有 run_traces 行的步骤树与 todos（无行/读失败回空，行为同旧）。

    deepcopy 防本段改写步骤 dict 时污染后续多次读到的同一份 JSON 解析产物。"""
    try:
        prior = db.get_run_trace(rid)
    except Exception:
        logger.exception("续跑段承接 trace 失败（rid=%s），按空树起步", rid)
        return [], []
    if not prior:
        return [], []
    return (
        copy.deepcopy(prior.get("tools") or []),
        copy.deepcopy(prior.get("todos") or []),
    )


# 活跃 run 的协作式取消事件（rid → Event）：POST /runs/{rid}/cancel 置位，
# worker 线程在下一个流事件边界退出（见 _run_agent_stream）
CANCEL_EVENTS: dict[str, threading.Event] = {}

# 运行中过程快照：只在当前 sidecar 进程内用于 SSE 断线/页面重挂对账。
# 终态仍以 app.db 的 run_traces 为历史真值，快照不伪造消息、不轮询 agent.db。
#
# 拷贝节流（SSE 微合批同思路）：结构性事件密集期整树 deepcopy 是 O(事件数×树大小)
# 的平方放大（32 节 run ~500+ 步）。窗口内只记树引用+脏标记，下一个事件或读侧
# 超窗才真拷——快照最多滞后 _LIVE_TRACE_WINDOW。树只在事件边界被 worker 线程改写，
# 读侧补拷与 worker 并发改树撞 deepcopy 异常时沿用旧快照下次再补（探测+兜底，不加锁）。
_LIVE_TRACE_WINDOW = 0.5
_LIVE_TRACE_LOCK = threading.Lock()
_LIVE_TRACES: dict[str, dict] = {}  # 最近一次已拷贝的安全快照
_LIVE_TRACE_PENDING: dict[str, dict] = {}  # 窗口内未拷贝的最新树引用
_LIVE_TRACE_TS: dict[str, float] = {}  # 每 rid 最近一次真实拷贝时间（monotonic）


def _copy_live_trace(rid: str, trace: dict) -> dict:
    return {
        "run_id": rid,
        "tools": copy.deepcopy(trace.get("tools") or []),
        "todos": copy.deepcopy(trace.get("todos") or []),
        "reasoning": trace.get("reasoning") or "",
    }


def set_live_trace(rid: str, trace: dict) -> None:
    with _LIVE_TRACE_LOCK:
        now = time.monotonic()
        if now - _LIVE_TRACE_TS.get(rid, 0.0) < _LIVE_TRACE_WINDOW:
            _LIVE_TRACE_PENDING[rid] = trace
            return
        _LIVE_TRACES[rid] = _copy_live_trace(rid, trace)
        _LIVE_TRACE_TS[rid] = now
        _LIVE_TRACE_PENDING.pop(rid, None)


def get_live_trace(rid: str) -> dict | None:
    with _LIVE_TRACE_LOCK:
        if rid in _LIVE_TRACE_PENDING and (
            time.monotonic() - _LIVE_TRACE_TS.get(rid, 0.0) >= _LIVE_TRACE_WINDOW
        ):
            try:  # worker 单线程改树，仅与事件边界并发时可能撞——沿用旧快照
                _LIVE_TRACES[rid] = _copy_live_trace(rid, _LIVE_TRACE_PENDING[rid])
                _LIVE_TRACE_TS[rid] = time.monotonic()
                _LIVE_TRACE_PENDING.pop(rid, None)
            except Exception:
                pass
        trace = _LIVE_TRACES.get(rid)
        return copy.deepcopy(trace) if trace is not None else None


def clear_live_trace(rid: str) -> None:
    with _LIVE_TRACE_LOCK:
        _LIVE_TRACES.pop(rid, None)
        _LIVE_TRACE_PENDING.pop(rid, None)
        _LIVE_TRACE_TS.pop(rid, None)


def get_run_snapshot(rid: str) -> dict | None:
    """取运行中快照；进程内没有时回退到已落库的最终/暂停 trace。"""
    live = get_live_trace(rid)
    if live is not None:
        return live
    trace = db.get_run_trace(rid)
    if trace is None:
        return None
    return {
        "run_id": rid,
        "tools": trace.get("tools") or [],
        "todos": trace.get("todos") or [],
        "reasoning": trace.get("reasoning") or "",
    }


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


def _usage_json_final(rid: str) -> str | None:
    """run 终态/暂停时的用量快照：已落库值（此前 HITL 段累计）+ 本段累计（取走清零）。

    两边都空返回 None——db 层 None=保留旧值（续段无新增模型调用时不覆盖）。"""
    current = token_usage.take(rid)
    if not current:
        return None
    prev: dict = {}
    try:
        loaded = json.loads((db.get_run(rid) or {}).get("token_usage") or "{}")
        if isinstance(loaded, dict):
            prev = {str(k): v for k, v in loaded.items() if isinstance(v, (int, float))}
    except (TypeError, ValueError):
        prev = {}
    merged = dict(prev)
    for k, v in current.items():
        merged[k] = int(merged.get(k, 0)) + v
    return json.dumps(merged, ensure_ascii=False)


async def run_stream(
    cid: str,
    rid: str,
    user_text: str | None = None,
    resume_decisions: list | None = None,
    start_seq: int = 0,
    thinking: str = "low",
    model: str | None = None,
    resume_payload: dict | None = None,
    continue_from_checkpoint: bool = False,
) -> None:
    """后台任务：驱动一段 agent 流式执行并实时发布 §5.5 事件。

    首段传 user_text；HITL 续段传 resume_decisions（同一 run 从 interrupt 处续跑，
    start_seq 接上一段的事件序号--前端按 run_id 去重，重置会吞掉续段事件）。
    多中断续段传 resume_payload（{interrupt_id: {"decisions": [...]}} 映射，
    langgraph 对多个 pending interrupt 的恢复要求）。continue_from_checkpoint=True
    是终态断点续跑（2026-09-12，POST /runs/{rid}/continue）：无新输入，从 checkpoint
    恢复 pending 任务只重跑未完成节点。thinking 是本 run 的思考档位
    （low/medium/high，续跑沿用首段存档值）。model 是本 run 选用的模型 profile id
    （None=default；续跑沿用首段存档值）。
    """
    # 用户请求停止（POST /runs/{rid}/cancel）：注册协作式取消事件，run 结束时摘除
    cancel_event = threading.Event()
    CANCEL_EVENTS[rid] = cancel_event
    # 收尾状态预置：异常可能发生在 worker 返回之前（取 agent、发布 started 等），
    # except 兜底路径需要安全的空值；segment_saved 标记 worker 分支已完成
    # 半截消息/trace 落库，兜底路径据此防双写
    text: str = ""
    error: str | None = None
    error_code: str | None = None
    trace: dict = {"tools": [], "todos": []}
    interrupt: dict | None = None
    segment_saved = False
    # 「本轮文件」探测：run 起点 work/ 快照 + 各段终态 diff（含续跑分段，合并进同一
    # run_traces 行）。None=无任务/探测失败，落库语义为「保留旧值」
    start_files: dict | None = None
    segment_files: list | None = None
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
            {"event": events.EVENT_STARTED, "data": events.started_payload(rid, cid, next_seq())},
        )
        agent = await get_agent(model)
        loop = asyncio.get_running_loop()

        # worker 线程里逐块发布：把协程调度回事件循环（queue.put_nowait 即时返回）
        def _publish(event: str, data: dict) -> None:
            payload = {**data, "seq": next_seq()}
            fut = asyncio.run_coroutine_threadsafe(publish(cid, {"event": event, "data": payload}), loop)
            fut.result()

        t0 = time.monotonic()
        task_id = (db.get_conversation(cid) or {}).get("task_id")
        if task_id:
            # 目录自愈：骨架预建（2026-08-29）之前创建的任务只有库行、没有磁盘目录，
            # 纯检索/对话任务也没有按需建目录的时机——run 启动兜底补齐，模型第一步
            # ls <task_id>/ 不再 path_not_found（mkdir exist_ok，幂等无锁）
            artifact_store.ensure_task_skeleton(task_id)
        # 快照在骨架自愈之后、worker 启动之前：起止之间的 work/ 变更即「本轮文件」。
        # 与终态 diff 同一条纪律：探测失败只损失本轮文件数据，绝不打死 run
        try:
            start_files = run_files.snapshot_work_files(task_id)
        except Exception:
            logger.exception("本轮文件起点快照失败（cid=%s rid=%s）", cid, rid)
            start_files = None
        text, error, error_code, trace, interrupt = await asyncio.to_thread(
            _run_agent_stream, agent, cid, rid, task_id, _publish, user_text, resume_decisions,
            cancel_event, thinking, resume_payload, continue_from_checkpoint,
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

        # 本段 work/ 变更 diff（completed/error/waiting_input 三分支共用；含 HITL
        # 续跑分段=每段起止各一次，分段结果进 _save_merged_trace 合并）。探测本身
        # 绝不打断收尾：失败按「无新数据」处理（None=保留旧值）
        try:
            segment_files = run_files.diff_work_files(task_id, start_files)
        except Exception:
            logger.exception("本轮文件 diff 失败（cid=%s rid=%s）", cid, rid)
            segment_files = None

        if error:
            # 半截回复快照：优先最终回复段，空则用最后一段旁白兜底（并从 trace 步骤去重）
            snapshot_text, tools_snapshot = _pause_snapshot(text, trace["tools"])
            error_msg_id = None
            if snapshot_text.strip():
                # 中断 run 的半截回复落库：checkpoint 里模型"说过"这些话（或 dangling 修复后
                # 仍残留半截上下文），messages 表同步记一份（带中断标记），UI 与模型记忆对齐
                error_msg_id = db.append_assistant_message(
                    cid, snapshot_text.rstrip() + "\n\n（任务中断）", rid=rid
                )["id"]
            else:
                # 续跑段终止且无任何新产出：改写暂停消息的「等待你的输入…」标记，
                # 否则对话最后一句永远宣称在等输入、与已终止的 run 矛盾
                db.retire_pause_marker((db.get_run(rid) or {}).get("pause_msg_id"))
            # 中断 run 的执行过程也落 trace（与暂停段合并）：本段有新产出消息则挂新消息
            # （GET /messages 按 message_id 挂载——2026-09-08 前写死 None，首段 error 的
            # trace 永远挂不上任何消息，历史里过程全丢）；无新消息传 None=保留暂停消息挂载
            _save_merged_trace(rid, cid, error_msg_id, {**trace, "tools": tools_snapshot}, duration_ms, files=segment_files)
            segment_saved = True
            # 先落库后发事件（与 completed 分支一致）：客户端收到终态事件即可立即对账
            seq = next_seq()
            db.finish_run(rid, "error", error, last_seq=seq, token_usage_json=_usage_json_final(rid), error_code=error_code)
            _frozen_ctx_cleanup(rid)  # 终态清冻结块（前缀缓存铁律的缓存不再占用）
            # code（契约 additive）：错误定性（cancelled/llm_unavailable/llm_auth/internal，
            # 2026-09-08 扩展取值域），前端据此选人话文案与操作入口
            await publish(
                cid,
                {
                    "event": events.EVENT_ERROR,
                    "data": events.error_payload(
                        rid,
                        cid,
                        error,
                        error_code,
                        seq,
                    ),
                },
            )
            return

        if interrupt:
            # HITL 暂停：半截回复落库 + trace，run 转 waiting_input，快照与 last_seq 存进
            # runs 行——重启后 run.state/前端恢复审批卡、seq 续接都靠它。
            # 暂停消息**无条件落库**（正文为空就只落标记）：它是回合里首个 assistant 段，
            # 前端头像头/过程卡的载体——缺失时最终回复会变成全回合第一条 assistant，
            # 头像头错落到回合尾部（2026-08-30 实测「另一个时空」缺陷的根因）。
            snapshot_text, tools_snapshot = _pause_snapshot(text, trace["tools"])
            content = (snapshot_text.rstrip() + "\n\n（等待你的输入…）").lstrip()
            msg_id = db.append_assistant_message(cid, content, rid=rid)["id"]
            _save_merged_trace(
                rid, cid, msg_id,
                {**trace, "tools": _freeze_paused_steps(tools_snapshot)},
                duration_ms,
                files=segment_files,
            )
            segment_saved = True
            # 先落库后发事件（与 completed/error 分支一致）
            seq = next_seq()
            db.interrupt_run(rid, interrupt["requests"], seq, pause_msg_id=msg_id, token_usage_json=_usage_json_final(rid))
            await publish(
                cid,
                {
                    "event": events.EVENT_RUN_INTERRUPT,
                    "data": events.interrupt_payload(rid, cid, interrupt["requests"], seq),
                },
            )
            return

        if not text.strip():
            text = "（空回复）"
        msg = db.append_assistant_message(cid, text, rid=rid)
        segment_saved = True
        # 执行过程快照与 assistant 消息关联落库（与暂停段合并成全程一棵树，
        # 历史会话/刷新后执行过程仍可见）
        _save_merged_trace(rid, cid, msg["id"], trace, duration_ms, files=segment_files)
        # 交付物呈现（2026-09-13 二批改定：run 正常完成时呈现）：本轮 run 内声明的
        # 交付物取**最后一个**在终态事件前发出（多个时面板只开最新的一个，先目录后
        # 整本自然选整本；逐个发会在毫秒内连环换页）。只在 completed 分支发——
        # error（含取消）/interrupt（等待输入）段不呈现：那时该看错误卡/提问卡，
        # 暂停段声明的交付物随之丢弃（finally 清桶），续跑完成后由**续跑段**的新
        # 声明或转录产物卡兜底。
        items = deliverables.drain(rid)
        if items:
            await publish(
                cid,
                {
                    "event": events.EVENT_DELIVERABLE_CREATED,
                    "data": events.deliverable_created_payload(items[-1], rid, cid, next_seq()),
                },
            )
        seq = next_seq()
        db.finish_run(rid, "completed", last_seq=seq, token_usage_json=_usage_json_final(rid))
        _frozen_ctx_cleanup(rid)
        await publish(
            cid,
            {
                "event": events.EVENT_COMPLETED,
                "data": events.completed_payload(rid, cid, msg["id"], seq),
            },
        )
    except Exception as e:
        logger.exception("run_stream failed")
        # 收尾兜底（与 worker error 分支同规则）：失败前已流出的半截正文与执行过程
        # 照常落库，否则历史里只剩一条红错、已流出内容全失。worker 分支已完成的
        # 落库（segment_saved）不重做；零流出（异常在取 agent/发布 started 等）只
        # 清可能残留的暂停标记（续段场景），不落空 trace。
        if not segment_saved:
            try:
                snapshot_text, tools_snapshot = _pause_snapshot(text, trace["tools"])
                fallback_msg_id = None
                if snapshot_text.strip() or trace["tools"]:
                    if snapshot_text.strip():
                        fallback_msg_id = db.append_assistant_message(
                            cid, snapshot_text.rstrip() + "\n\n（任务中断）", rid=rid
                        )["id"]
                    else:
                        db.retire_pause_marker((db.get_run(rid) or {}).get("pause_msg_id"))
                    # 同 error 分支：有新产出消息则挂载（过程在历史可见），None=保留旧挂载
                    _save_merged_trace(rid, cid, fallback_msg_id, {**trace, "tools": tools_snapshot}, None, files=segment_files)
                else:
                    db.retire_pause_marker((db.get_run(rid) or {}).get("pause_msg_id"))
            except Exception:
                logger.exception("run_stream 异常收尾落库失败（cid=%s rid=%s）", cid, rid)
        try:
            seq = next_seq()
            # 异常与取消竞态：cancel 已置位按 cancelled 收尾（含取消感知 middleware 抛出的
            # _ToolCancelledError 从 worker 外漏到本层的场景），不误归类 internal
            if cancel_event.is_set():
                outer_code, outer_error = "cancelled", events.CANCELLED_MESSAGE
            else:
                outer_code, outer_error = _classify_error(e)
            # 终态守卫：worker 分支已落的终态不被覆盖——error 分支写入的原始错误
            # 文案不被内部异常顶掉、completed 不被翻成 error（error 事件照发）
            db.finish_run_if_running(
                rid, "error", outer_error, last_seq=seq,
                token_usage_json=_usage_json_final(rid), error_code=outer_code,
            )
            _frozen_ctx_cleanup(rid)
            # code 恒有键（契约 2026-08-27 additive）：此前此处漏发 code，靠前端 ?? null 兜住
            await publish(
                cid,
                {"event": events.EVENT_ERROR, "data": events.error_payload(rid, cid, outer_error, outer_code, seq)},
            )
        except Exception:
            logger.exception("run_stream 终态落库/事件发布失败（cid=%s rid=%s）", cid, rid)
    finally:
        CANCEL_EVENTS.pop(rid, None)
        _REPLAY_GUARD_STATE.pop(rid, None)  # 重派守卫状态（起点缓存/泄压计数）不跨 run 残留
        deliverables.clear(rid)  # 清呈现信号桶：防异常路径残留累积（正常路径 drain 已空）
