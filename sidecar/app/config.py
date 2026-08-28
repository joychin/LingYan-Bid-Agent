"""读取环境变量。数据目录默认 <sidecar>/data，可通过 DATA_DIR 覆盖。

模型配置是多 profile 列表（2026-08-29 重构）：settings.json 形如
{models: [{id, name, base_url, model, image_support}], default_model}。
API Key 只认环境变量——Rust 把每个 profile 的钥匙串 account 组成 MODEL_KEYS
（JSON {id: key}）spawn 注入；浏览器开发模式 .env 可配 MODEL_KEYS，或对
id="default" 的 profile 回退 LLM_API_KEY。

读侧迁移（与 Rust read_settings_file 同语义）：旧 {llm:{...}} 块（含更旧扁平格式）
→ id="default" 的 profile；旧 {vlm:{...}} 块 → id="vision" 的 profile
（image_support=true）。旧 LLM_BASE_URL/LLM_MODEL env 仍覆盖 default profile
（开发期 .env 优先级习惯不变）。视觉能力不再独立配置：resolve_vision() =
default 若支持图片，否则第一个 image_support 的 profile，无则未配置。
"""

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path

SIDECAR_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class ModelProfile:
    """一个可对话的模型接入配置（多 profile：用户可配任意多家供应商任意个模型）。"""

    id: str
    name: str
    base_url: str
    model: str
    image_support: bool = False


def _builtin_default_profile() -> ModelProfile:
    return ModelProfile(id="default", name="默认模型", base_url=_DEFAULT_BASE_URL, model=_DEFAULT_MODEL)


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or (SIDECAR_ROOT / "data")).resolve()


def app_db_path() -> Path:
    return data_dir() / "app.db"


def agent_db_path() -> Path:
    return data_dir() / "agent.db"


def workspace_dir() -> Path:
    return data_dir() / "workspace"


def knowledge_dir() -> Path:
    """知识库目录（workspace 下与 skills/archive 同级的全局目录，不属于任何任务）。"""
    return workspace_dir() / "knowledge"


def skills_source_dir() -> Path:
    return SIDECAR_ROOT / "app" / "skills"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def _file_overrides() -> dict:
    """读 settings.json；不存在/损坏时返回空 dict。"""
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _profile_from(block: dict, pid: str, name: str, *, image_support: bool = False) -> ModelProfile:
    return ModelProfile(
        id=pid,
        name=str(block.get("name") or name),
        base_url=str(block.get("base_url") or ""),
        model=str(block.get("model") or ""),
        image_support=bool(block.get("image_support", image_support)),
    )


def _apply_env_override_to_default(profiles: list[ModelProfile]) -> list[ModelProfile]:
    """LLM_BASE_URL/LLM_MODEL env 覆盖 default profile（开发期 .env 优先级习惯：
    env > settings.json > 内置默认；Rust 不注入这两个 env，只有浏览器模式 .env 有）。"""
    if os.environ.get("LLM_BASE_URL") or os.environ.get("LLM_MODEL"):
        return [
            (
                dataclasses.replace(
                    p,
                    base_url=os.environ.get("LLM_BASE_URL") or p.base_url,
                    model=os.environ.get("LLM_MODEL") or p.model,
                )
                if p.id == "default"
                else p
            )
            for p in profiles
        ]
    return profiles


def model_profiles() -> list[ModelProfile]:
    """全部模型 profile（含旧格式读侧迁移）。空配置时返回内置默认单条。"""
    data = _file_overrides()
    raw = data.get("models")
    if isinstance(raw, list):
        out: list[ModelProfile] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "").strip()
            if not pid:
                continue
            out.append(
                ModelProfile(
                    id=pid,
                    name=str(item.get("name") or pid),
                    base_url=str(item.get("base_url") or ""),
                    model=str(item.get("model") or ""),
                    image_support=bool(item.get("image_support")),
                )
            )
        return _apply_env_override_to_default(out) if out else [_builtin_default_profile()]
    # 旧双角色/扁平格式 → 迁移为 profile（default / vision）
    migrated: list[ModelProfile] = []
    llm_block = data.get("llm") if isinstance(data.get("llm"), dict) else None
    if llm_block is None and ("base_url" in data or "model" in data):
        llm_block = data  # 更旧的扁平格式
    if llm_block is not None:
        migrated.append(_profile_from(llm_block, "default", "默认模型"))
    else:
        migrated.append(_builtin_default_profile())
    vlm_block = data.get("vlm") if isinstance(data.get("vlm"), dict) else None
    if vlm_block is not None and str(vlm_block.get("base_url") or "").strip():
        migrated.append(_profile_from(vlm_block, "vision", "视觉模型", image_support=True))
    return _apply_env_override_to_default(migrated)


def default_model_id() -> str:
    profiles = model_profiles()
    data = _file_overrides()
    want = str(data.get("default_model") or "").strip()
    if want and any(p.id == want for p in profiles):
        return want
    if any(p.id == "default" for p in profiles):
        return "default"
    return profiles[0].id if profiles else "default"


def get_profile(pid: str) -> ModelProfile | None:
    return next((p for p in model_profiles() if p.id == pid), None)


def _model_keys() -> dict:
    raw = os.environ.get("MODEL_KEYS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def model_key(pid: str) -> str | None:
    """profile 的 API Key：MODEL_KEYS JSON env；default 回退 LLM_API_KEY（浏览器模式 .env 兼容）。"""
    k = _model_keys().get(pid)
    if isinstance(k, str) and k:
        return k
    if pid == "default":
        return os.environ.get("LLM_API_KEY")
    return None


# ---- 旧调用面薄壳（titler / KB 抽取 / test 端点）：恒走 default profile ----

def llm_api_key() -> str | None:
    return model_key(default_model_id())


def llm_base_url() -> str:
    v = os.environ.get("LLM_BASE_URL")
    if v:
        return v
    p = get_profile(default_model_id())
    return p.base_url if p and p.base_url else _DEFAULT_BASE_URL


def llm_model() -> str:
    v = os.environ.get("LLM_MODEL")
    if v:
        return v
    p = get_profile(default_model_id())
    return p.model if p and p.model else _DEFAULT_MODEL


def resolve_vision() -> ModelProfile | None:
    """视觉能力解析：default 若支持图片，否则第一个 image_support 的 profile。"""
    profiles = model_profiles()
    dflt = get_profile(default_model_id())
    if dflt and dflt.image_support:
        return dflt
    return next((p for p in profiles if p.image_support), None)


def baidu_ocr_api_key() -> str | None:
    return os.environ.get("BAIDU_OCR_API_KEY")


def baidu_ocr_secret_key() -> str | None:
    return os.environ.get("BAIDU_OCR_SECRET_KEY")


def sidecar_token() -> str | None:
    v = os.environ.get("SIDECAR_TOKEN")
    return v.strip() if v else None
