"""Settings 端点：多模型 profile 列表读写 + 连通性测试。

配置与凭证的真值在 app.db 的 app_settings KV 表（用户明令 2026-08-29 弃钥匙串）：
模型列表/默认模型经 PUT /settings/models，Key 经 PUT /settings/keys（只写不读——
GET 永不回回 Key，只回 key_configured 布尔），百度 AK/SK 经 PUT /settings/ocr-keys。
env 只作兜底读取（.env 开发习惯不变）。变更即时生效（agent 缓存清空惰性重建），
无需重启服务。
"""

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
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


class BackgroundRolesBody(BaseModel):
    """后台任务角色 → profile id（空串=跟随缺省：extract 回 default，vision 走自动解析）。"""

    extract: str = ""
    vision: str = ""


class ModelsBody(BaseModel):
    models: list[ModelBody]
    default_model: str
    background_roles: BackgroundRolesBody | None = None


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
        "background_roles": cfg.background_roles(),
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
    if body.background_roles is not None:
        for role, pid in (
            ("extract", body.background_roles.extract.strip()),
            ("vision", body.background_roles.vision.strip()),
        ):
            if pid and pid not in ids:
                raise HTTPException(status_code=422, detail=f"后台任务角色 {role} 引用了未知模型：{pid}")

    normalized: list[cfg.ModelProfile] = []
    for m, mid in zip(body.models, ids):
        base_url = _validate_base_url(m.base_url or "")
        if not (m.model or "").strip():
            raise HTTPException(status_code=422, detail=f"模型 {mid} 缺少 model 名")
        normalized.append(
            cfg.ModelProfile(
                id=mid,
                name=(m.name or "").strip() or mid,
                base_url=base_url,
                model=m.model.strip(),
                image_support=m.image_support,
            )
        )

    roles = (
        {"extract": body.background_roles.extract, "vision": body.background_roles.vision}
        if body.background_roles is not None
        else None
    )
    cfg.save_models_and_roles(normalized, body.default_model, roles)
    # 模型列表变了：清 agent 缓存（按 profile 惰性重建，毫秒级；无 key 的 profile 在
    # 实际被选用时才报错，不影响其他 profile）
    await rebuild_agent()
    return {"ok": True}


class KeyBody(BaseModel):
    model_id: str
    api_key: str


@router.put("/settings/keys")
async def put_settings_key(body: KeyBody):
    """保存模型 Key 到本地库（用户明令 2026-08-29：凭证存 SQLite，弃钥匙串）。

    安全性质保留：GET 永不回读 Key（只回 key_configured 布尔）；本端点只写不读。
    即时生效（agent 缓存清空惰性重建），无需重启服务。
    """
    pid = body.model_id.strip()
    key = body.api_key.strip()
    if not pid:
        raise HTTPException(status_code=422, detail="model_id 不能为空")
    if not key:
        raise HTTPException(status_code=422, detail="api_key 不能为空")
    # 孤儿 key 防护：只给存在的 profile 存 Key（对齐 put_settings_models 的 roles
    # 校验先例）——否则写错 id 会静默存一个 GET 永不可见的凭证
    if cfg.get_profile(pid) is None:
        raise HTTPException(status_code=404, detail=f"模型 {pid} 不存在，请先保存模型配置")
    cfg.set_model_key(pid, key)
    await rebuild_agent()
    return {"ok": True}


class OcrKeysBody(BaseModel):
    api_key: str
    secret_key: str


@router.put("/settings/ocr-keys")
async def put_settings_ocr_keys(body: OcrKeysBody):
    ak, sk = body.api_key.strip(), body.secret_key.strip()
    if not ak or not sk:
        raise HTTPException(status_code=422, detail="API Key 与 Secret Key 均不能为空")
    cfg.set_baidu_ocr_keys(ak, sk)
    # AK/SK 换取的 access_token 缓存作废，下次解析用新凭证重取
    from ..baidu_ocr import _reset_token_cache

    _reset_token_cache()
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
    request: Request,
    role: str | None = Query(default=None, pattern="^(ocr)$"),
    model: str | None = None,
):
    """轻量连通性测试：model=<profile id> 发最小 chat；role=ocr 用 AK/SK 换 token。

    要求自定义头 X-Sidecar-Ping（前端恒带）：GET 是免预检的简单请求，无此防护时
    任意网站可静默触发「用存储的 Key 向已配置 base_url 发出站请求」（本机开发模式
    无 token，主要是调用费消耗）；自定义头使跨站触发必须过 CORS 预检、被 origin
    白名单挡住。本机 localhost 页面在开发模式下本就有完整 API 访问权，不在此防护
    范围内。"""
    if (request.headers.get("x-sidecar-ping") or "") != "1":
        raise HTTPException(status_code=403, detail="缺少 X-Sidecar-Ping 头")
    if model:
        result = await asyncio.to_thread(_test_model_sync, model)
        return {"ok": result == "ok", "model": model}
    if role == "ocr":
        result = await asyncio.to_thread(_test_ocr_sync)
        return {"ok": result == "ok", "role": role}
    raise HTTPException(status_code=422, detail="必须提供 model 或 role=ocr 之一")
