"""run 级 token 用量累计 + per-turn 明细（2026-09-06 观测层；2026-09-08 加明细）。

捕获点在模型壳（_NoThinkingRetryCompletions.create 的返回）——主 agent 与全部
子代理共享同一模型实例、runctx 的 contextvars 已随线程传播，这一层能看到本 run
的每一次 API 响应。rid 经 runctx 解析：非 run 态（titler 独立实例本就不经此层，
测试直调工具等）丢弃不计。

字段（能取到就记，取不到不硬凑）：
- input / output：prompt_tokens / completion_tokens
- cached：缓存命中的输入 token（openai SDK 的 prompt_tokens_details.cached_tokens
  或 DeepSeek 非标的 prompt_cache_hit_tokens，两者都试）
- reasoning：输出中的思考 token（usage.completion_tokens_details.reasoning_tokens）

两层落库：
- run 级聚合：db.finish_run / interrupt_run 的 token_usage 参数（JSON 文本），
  take() 取走即清零——每个 run 只落一次；
- per-turn 明细：run_turn_usage 每次调用一行，scope 取 runctx.current_scope()
  （main/sub，子代理 scope 中间件打标），供「token 都花在哪」的归因查询。
"""

from __future__ import annotations

import logging
import threading

from . import db, runctx

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_by_run: dict[str, dict[str, int]] = {}


def _extract(usage) -> dict[str, int]:
    """从 openai SDK 的 usage 对象提取字段（缺字段返回空 dict，不抛）。"""
    if usage is None:
        return {}
    out: dict[str, int] = {}

    def _int(v) -> int | None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    pt = _int(getattr(usage, "prompt_tokens", None))
    ct = _int(getattr(usage, "completion_tokens", None))
    if pt is not None:
        out["input"] = pt
    if ct is not None:
        out["output"] = ct
    # 缓存命中：标准字段 prompt_tokens_details.cached_tokens；DeepSeek 网关把
    # prompt_cache_hit_tokens 放 usage 根部（非标，openai SDK 不映射）——都试
    details = getattr(usage, "prompt_tokens_details", None)
    cached = _int(getattr(details, "cached_tokens", None)) if details is not None else None
    if cached is None:
        cached = _int(getattr(usage, "prompt_cache_hit_tokens", None))
    if cached is not None:
        out["cached"] = cached
    cd = getattr(usage, "completion_tokens_details", None)
    reasoning = _int(getattr(cd, "reasoning_tokens", None)) if cd is not None else None
    if reasoning is not None:
        out["reasoning"] = reasoning
    return out


def record_usage(usage) -> None:
    """从一次 API 响应的 usage 对象提取字段并计入当前 run（非 run 态丢弃）。

    主入口：流式/非流式的 usage 都经这里。流式时 usage 取自流吐完后的最后一块
    （`stream_options.include_usage` 开启时服务端才回），取不到就什么都不记。
    run 级聚合之外同步落 per-turn 明细行（归因用）。
    """
    ctx = runctx.current_run()
    if ctx is None:
        return
    fields = _extract(usage)
    if not fields:
        return
    with _lock:
        bucket = _by_run.setdefault(ctx.run_id, {})
        for k, v in fields.items():
            bucket[k] = bucket.get(k, 0) + v
    _record_turn_detail(ctx.run_id, fields)


def _record_turn_detail(rid: str, fields: dict[str, int]) -> None:
    """per-turn 明细：run_turn_usage 一行 + INFO 日志（现场 tail 观察）。

    明细失败不影响主流程（聚合与 run 终态落库照常）；日志恒发——它是唯一
    实时可见的通道，库写挂了日志还在。
    """
    scope = runctx.current_scope()
    try:
        db.insert_run_turn_usage(rid, scope, fields)
    except Exception:
        logger.debug("token 明细落库失败（不影响主流程）", exc_info=True)
    logger.info(
        "llm 用量 rid=%s scope=%s in=%s cached=%s out=%s reasoning=%s",
        rid,
        scope,
        fields.get("input", 0),
        fields.get("cached", 0),
        fields.get("output", 0),
        fields.get("reasoning", 0),
    )


def record_from_response(resp) -> None:
    """从一次非流式 chat.completions 响应（带 .usage）记账。"""
    record_usage(getattr(resp, "usage", None))


def peek(rid: str) -> dict[str, int]:
    with _lock:
        return dict(_by_run.get(rid) or {})


def take(rid: str) -> dict[str, int]:
    """取走并清零（run 终态落库用，每 run 一次）。"""
    with _lock:
        return dict(_by_run.pop(rid, {}))
