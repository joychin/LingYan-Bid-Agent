"""Settings 端点（PRD §5.4）：双角色（llm/vlm）嵌套读写 + 连通性测试。

LLM_API_KEY / VLM_API_KEY / BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY 不接受 HTTP 修改
——只能经环境变量（即 Tauri 侧改钥匙串后重启 sidecar）。base_url/model/image_support
持久化到 data/settings.json（与 Tauri 共享的单一配置真值，结构 {llm:{...},vlm:{...}}）。
PUT 后：llm base_url/model 变更即时重建 agent；image_support 与 vml 均无需重建
（vlm/ocr 是无状态客户端，改 env 即生效）。
"""

import asyncio
import json
import os
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import config as cfg
from ..agent import rebuild_agent

router = APIRouter()

Role = Literal["llm", "vlm"]


class RoleBody(BaseModel):
    base_url: str | None = None
    model: str | None = None
    image_support: bool | None = None  # 仅 llm 角色消费；vlm 天然支持图片


class SettingsBody(BaseModel):
    llm: RoleBody | None = None
    vlm: RoleBody | None = None


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


@router.get("/settings")
async def get_settings():
    return {
        "llm": {
            "base_url": cfg.llm_base_url(),
            "model": cfg.llm_model(),
            "key_configured": bool(cfg.llm_api_key()),
            "image_support": cfg.llm_image_support(),
        },
        "vlm": {
            "base_url": cfg.vlm_base_url(),
            "model": cfg.vlm_model(),
            "key_configured": bool(cfg.vlm_api_key()),
        },
        "ocr": {
            "configured": bool(cfg.baidu_ocr_api_key() and cfg.baidu_ocr_secret_key()),
        },
        "paths": {
            "data_dir": str(cfg.data_dir()),
            "log_file": str(cfg.data_dir() / "logs" / "sidecar.log"),
        },
    }


def _persist(llm: RoleBody | None, vlm: RoleBody | None) -> None:
    """读现有 settings.json → 应用变更 → 写回（保留未知键；llm 写入即从旧扁平格式迁移）。"""
    data = cfg._file_overrides()
    if llm is not None:
        block = data.get("llm") if isinstance(data.get("llm"), dict) else {}
        if llm.base_url is not None:
            block["base_url"] = llm.base_url
        if llm.model is not None:
            block["model"] = llm.model
        if llm.image_support is not None:
            block["image_support"] = llm.image_support
        data["llm"] = block
        # 迁移：清掉旧扁平顶层键，避免两处真值
        data.pop("base_url", None)
        data.pop("model", None)
    if vlm is not None:
        base = (vlm.base_url or "").strip()
        if base:
            block = data.get("vlm") if isinstance(data.get("vlm"), dict) else {}
            if vlm.base_url is not None:
                block["base_url"] = vlm.base_url
            if vlm.model is not None:
                block["model"] = vlm.model
            data["vlm"] = block
        else:
            # vlm base_url 传空 = 清除视觉模型配置（知识库图片/扫描件走降级链）
            data.pop("vlm", None)
    cfg.settings_path().parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.put("/settings")
async def put_settings(body: SettingsBody):
    if body.llm is None and body.vlm is None:
        raise HTTPException(status_code=422, detail="至少提供 llm 或 vlm 之一")

    llm_changed = False
    if body.llm is not None:
        base_url = _validate_base_url(body.llm.base_url) if body.llm.base_url else None
        if base_url:
            os.environ["LLM_BASE_URL"] = base_url
        if body.llm.model:
            os.environ["LLM_MODEL"] = body.llm.model
        llm_changed = bool(base_url or body.llm.model)

    if body.vlm is not None:
        if body.vlm.base_url:
            base_url = _validate_base_url(body.vlm.base_url)
            os.environ["VLM_BASE_URL"] = base_url
        else:
            os.environ.pop("VLM_BASE_URL", None)
        if body.vlm.model:
            os.environ["VLM_MODEL"] = body.vlm.model
        else:
            os.environ.pop("VLM_MODEL", None)

    _persist(body.llm, body.vlm)
    # 无 key 时不重建 agent（build_agent 需要 key）；首次调用时惰性构建即可。
    # vlm 无状态（每次调用现读 env），无需重建。
    if llm_changed and cfg.llm_api_key():
        await rebuild_agent()
    return {"ok": True}


def _test_role_sync(role: str) -> str:
    """同步最小连通性测试：llm/vlm 发一条 ping chat；ocr 用 AK/SK 换一次 access_token。"""
    from openai import OpenAI

    if role == "ocr":
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

    if role == "llm":
        base_url, model, api_key = cfg.llm_base_url(), cfg.llm_model(), cfg.llm_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="LLM API Key 未配置（Tauri 设置里保存）")
        content = "ping"
    else:
        base_url, model, api_key = cfg.vlm_base_url(), cfg.vlm_model(), cfg.vlm_api_key()
        if not (base_url and api_key):
            raise HTTPException(status_code=400, detail="VLM 未配置（base_url / API Key 缺失）")
        # VL 模型对纯文本输入普遍兼容（qwen-vl / glm-4v 均支持 text-only chat）
        content = "ping"
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=15.0, max_retries=0)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_tokens=1,
        )
    except Exception as e:  # noqa: BLE001 - 测试端点要把原始错误透给用户
        raise HTTPException(status_code=502, detail=f"连通失败：{e}") from e
    if not resp.choices:
        raise HTTPException(status_code=502, detail="连通失败：响应无 choices")
    return "ok"


@router.get("/settings/test")
async def test_settings(role: str = Query(pattern="^(llm|vlm|ocr)$")):
    """轻量连通性测试（设置对话框「测试」按钮）：最小 chat 请求，返回 ok 或错误详情。"""
    result = await asyncio.to_thread(_test_role_sync, role)
    return {"ok": result == "ok", "role": role}
