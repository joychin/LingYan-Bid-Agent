"""Settings 端点：多模型 profile 列表读写 + 连通性测试。

API Key 永不接受 HTTP 修改——每个 profile 的 key 只经环境变量 MODEL_KEYS
（Tauri 侧改钥匙串后重启 sidecar 注入）。base_url/model/image_support/name 与
default_model 持久化到 data/settings.json（与 Tauri 共享的单一配置真值，形状
{models: [...], default_model}）。
PUT /settings/models 后清空 agent 缓存（按 profile 惰性重建）。
"""

import asyncio
import json
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import config as cfg
from ..agent import rebuild_agent

router = APIRouter()


class ModelBody(BaseModel):
    id: str
    name: str | None = None
    base_url: str | None = None
    model: str | None = None
    image_support: bool = False


class ModelsBody(BaseModel):
    models: list[ModelBody]
    default_model: str


def _validate_base_url(v: str) -> str:
    v = (v or "").strip()
    if not v:
        raise HTTPException(status_code=422, detail="base_url 不能为空")
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="base_url 必须是合法 http/https URL")
    host = (parsed.hostname or "").lower()
    loopback = host in ("127.0.0.1", "localhost", "::1")
    if parsed.scheme != "https" and not loopback:
        raise HTTPException(status_code=422, detail="非本机 base_url 必须使用 https")
    return v


def _profile_to_api(p: cfg.ModelProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "model": p.model,
        "image_support": p.image_support,
        "key_configured": bool(cfg.model_key(p.id)),
    }


@router.get("/settings")
async def get_settings():
    return {
        "models": [_profile_to_api(p) for p in cfg.model_profiles()],
        "default_model": cfg.default_model_id(),
        "ocr": {
            "configured": bool(cfg.baidu_ocr_api_key() and cfg.baidu_ocr_secret_key()),
        },
        "paths": {
            "data_dir": str(cfg.data_dir()),
            "log_file": str(cfg.data_dir() / "logs" / "sidecar.log"),
        },
    }


@router.put("/settings/models")
async def put_settings_models(body: ModelsBody):
    ids = [m.id.strip() for m in body.models]
    if not ids or any(not i for i in ids):
        raise HTTPException(status_code=422, detail="models 不能为空且每条必须有 id")
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="模型 id 重复")
    if body.default_model not in ids:
        raise HTTPException(status_code=422, detail="default_model 必须是 models 之一")

    normalized: list[dict] = []
    for m, mid in zip(body.models, ids):
        base_url = _validate_base_url(m.base_url or "")
        if not (m.model or "").strip():
            raise HTTPException(status_code=422, detail=f"模型 {mid} 缺少 model 名")
        normalized.append(
            {
                "id": mid,
                "name": (m.name or "").strip() or mid,
                "base_url": base_url,
                "model": m.model.strip(),
                "image_support": m.image_support,
            }
        )

    data = cfg._file_overrides()
    data["models"] = normalized
    data["default_model"] = body.default_model
    # 迁移收尾：新形状写入即清旧结构（双角色块与更旧扁平键），避免两处真值
    data.pop("llm", None)
    data.pop("vlm", None)
    data.pop("base_url", None)
    data.pop("model", None)
    cfg.settings_path().parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 模型列表变了：清 agent 缓存（按 profile 惰性重建；无 key 的 profile 在
    # 实际被选用时才报错，不影响其他 profile）
    await rebuild_agent()
    return {"ok": True}


def _test_model_sync(pid: str) -> str:
    """同步最小连通性测试：向 profile 端点发一条 ping chat。"""
    from openai import OpenAI

    p = cfg.get_profile(pid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"模型不存在：{pid}")
    api_key = cfg.model_key(pid)
    if not api_key:
        raise HTTPException(status_code=400, detail=f"模型 {p.name} 未配置 API Key（Tauri 设置里保存）")
    client = OpenAI(api_key=api_key, base_url=p.base_url, timeout=15.0, max_retries=0)
    try:
        resp = client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as e:  # noqa: BLE001 - 测试端点要把原始错误透给用户
        raise HTTPException(status_code=502, detail=f"连通失败：{e}") from e
    if not resp.choices:
        raise HTTPException(status_code=502, detail="连通失败：响应无 choices")
    return "ok"


def _test_ocr_sync() -> str:
    from ..baidu_ocr import BaiduOcrUnavailable, exchange_access_token

    if not (cfg.baidu_ocr_api_key() and cfg.baidu_ocr_secret_key()):
        raise HTTPException(status_code=400, detail="文档解析未配置（API Key / Secret Key 缺失）")
    try:
        exchange_access_token(force_refresh=True)
    except BaiduOcrUnavailable as e:
        raise HTTPException(status_code=502, detail=f"连通失败：{e}") from e
    except Exception as e:  # noqa: BLE001 - 测试端点要把原始错误透给用户
        raise HTTPException(status_code=502, detail=f"连通失败：{e}") from e
    return "ok"


@router.get("/settings/test")
async def test_settings(
    role: str | None = Query(default=None, pattern="^(ocr)$"),
    model: str | None = None,
):
    """轻量连通性测试：model=<profile id> 发最小 chat；role=ocr 用 AK/SK 换 token。"""
    if model:
        result = await asyncio.to_thread(_test_model_sync, model)
        return {"ok": result == "ok", "model": model}
    if role == "ocr":
        result = await asyncio.to_thread(_test_ocr_sync)
        return {"ok": result == "ok", "role": role}
    raise HTTPException(status_code=422, detail="必须提供 model 或 role=ocr 之一")
