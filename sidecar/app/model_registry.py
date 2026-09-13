"""社区模型注册表缓存（models.dev）——上下文窗口的取值层之一。

窗口取值优先序（build_agent 侧 _apply_window_profile，2026-09-13 用户拍板分层路线）：
1. 用户手选（设置 → 模型 → 高级选项，存档真值）
2. langchain_deepseek 注册表已知模型名（DeepSeek 系，随库版本自带窗口）
3. 本模块缓存命中（models.dev 社区数据）
4. 保守默认 17 万 token（比例档起步；真实窗口更小的模型撞一次服务方上限后由
   agent 侧超限报错解析就地校准——见 _NoThinkingRetryCompletions）

设计约束：
- 程序自身永不含模型窗口数字（静态预设值机制已删：过期值有害——GLM-5.1 预设
  256K > 官方 204.8K 曾配了照样撞线；且厂商每次更新窗口都得跟版发程序）。
  数据活在社区库（models.dev，MIT、免费无 key、社区 PR + CI 校验），程序只消费。
- **run 路径零联网**：lookup 纯读本地缓存文件，离线可用。
- 只在用户主动联网动作（保存模型 / 测试连接 / 获取模型列表）后台尽力刷新，
  失败静默保留旧缓存（「配置类 UX 禁自动监控层」拍板：不做后台定时探活）。
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

import httpx

from . import config as cfg

logger = logging.getLogger(__name__)

_REGISTRY_URL = "https://models.dev/api.json"
_REFRESH_TIMEOUT = 8.0
_MAX_BYTES = 5_000_000  # 响应体上限（正常 ~1-2MB；防异常大响应）
_TTL_SECONDS = 24 * 3600  # 缓存新鲜期：期内设置动作不再打注册表


def _cache_path() -> Path:
    return cfg.data_dir() / "model_registry.json"


def _flatten(api: dict) -> dict[str, dict]:
    """api.json → {model_id: {"input": N, "context": N}}。

    input 取值回退链：limit.input → limit.context − limit.output → limit.context
    （deepagents 压缩档读的是 max_input_tokens 语义，优先输入上限）。
    无有效 limit 的条目跳过；跨 provider 同名模型后者覆盖（同模型限额一致）。
    """
    out: dict[str, dict] = {}
    for provider in api.values():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for mid, spec in models.items():
            if not isinstance(spec, dict):
                continue
            limit = spec.get("limit")
            if not isinstance(limit, dict):
                continue
            inp = limit.get("input")
            ctx = limit.get("context")
            outp = limit.get("output")
            value = inp
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                value = (
                    ctx - outp
                    if isinstance(ctx, int) and isinstance(outp, int) and ctx - outp > 0
                    else ctx
                )
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                continue
            entry = {"input": value}
            if isinstance(ctx, int) and not isinstance(ctx, bool):
                entry["context"] = ctx
            out[str(mid)] = entry
    return out


def _write_cache(models: dict[str, dict]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": int(time.time()), "models": models}
    # tmp+rename 原子替换（artifact_store 同款）：并发刷新互不撕写
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_cache() -> dict:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def refresh() -> bool:
    """拉取 models.dev 并重建本地缓存。失败静默（旧缓存保留），返回是否成功。"""
    try:
        with httpx.Client(timeout=_REFRESH_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(_REGISTRY_URL)
            resp.raise_for_status()
            if len(resp.content) > _MAX_BYTES:
                logger.warning("模型注册表响应超限（%d 字节），跳过", len(resp.content))
                return False
            api = resp.json()
        if not isinstance(api, dict):
            logger.warning("模型注册表响应形状异常，跳过")
            return False
        models = _flatten(api)
        if not models:
            logger.warning("模型注册表拍平后为空，保留旧缓存")
            return False
        _write_cache(models)
        logger.info("模型注册表缓存已刷新：%d 个模型", len(models))
        return True
    except Exception:
        logger.debug("模型注册表刷新失败（离线或服务不可达，保留旧缓存）", exc_info=True)
        return False


def maybe_refresh() -> None:
    """TTL 内不重复拉。挂在用户主动联网的设置动作后（fire-and-forget，见 api/settings.py）。"""
    fetched_at = _read_cache().get("fetched_at")
    if isinstance(fetched_at, int) and time.time() - fetched_at < _TTL_SECONDS:
        return
    refresh()


def lookup(model_name: str) -> int | None:
    """按模型名查窗口（输入上限 token）。纯读缓存、零联网；未命中返回 None。"""
    name = (model_name or "").strip()
    if not name:
        return None
    models = _read_cache().get("models")
    if not isinstance(models, dict):
        return None
    entry = models.get(name)
    if not isinstance(entry, dict):
        # 大小写归一兜底（社区库 id 惯用小写；不做前后缀剥离或模糊匹配——猜错比不猜糟）
        lower = name.lower()
        for mid, e in models.items():
            if isinstance(mid, str) and mid.lower() == lower:
                entry = e
                break
    if isinstance(entry, dict):
        value = entry.get("input")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return None
