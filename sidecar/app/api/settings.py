"""Settings 端点（PRD §5.4）：GET 只返回 base_url/model，PUT 即时重建 agent。

LLM_API_KEY 不接受 HTTP 修改——只能经环境变量（即 Tauri 侧改钥匙串后重启 sidecar）。
base_url/model 持久化到 data/settings.json（与 Tauri 共享的单一配置真值）。
"""

import json
import os
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config as cfg
from ..agent import rebuild_agent

router = APIRouter()


class SettingsBody(BaseModel):
    base_url: str | None = None
    model: str | None = None


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
    return {"base_url": cfg.llm_base_url(), "model": cfg.llm_model()}


def _persist(base_url: str | None, model: str | None) -> None:
    data = cfg._file_overrides()
    if base_url is not None:
        data["base_url"] = base_url
    if model is not None:
        data["model"] = model
    cfg.settings_path().parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.put("/settings")
async def put_settings(body: SettingsBody):
    base_url = _validate_base_url(body.base_url) if body.base_url is not None else None
    if base_url:
        os.environ["LLM_BASE_URL"] = base_url
    if body.model:
        os.environ["LLM_MODEL"] = body.model
    _persist(base_url, body.model)
    # 无 key 时不重建 agent（build_agent 需要 key）；首次调用时惰性构建即可
    if cfg.llm_api_key():
        await rebuild_agent()
    return {"ok": True}
