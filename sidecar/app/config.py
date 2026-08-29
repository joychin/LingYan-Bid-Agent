"""模型配置与凭证的读取（2026-08-29 起真值在 app.db 的 app_settings KV 表）。

用户明令（2026-08-29）：所有 LLM 配置包括 Key 都放本地库，弃钥匙串/MODEL_KEYS env
桥接——本地单机应用里明文落盘的威胁模型与 .env 完全等价，换来的是「配置一处、
即改即生效（agent 缓存重建，毫秒级）、浏览器/桌面两端同一套录入 UI」。
保留的安全性质：GET /settings 永不回读 Key（只回 key_configured 布尔）。

app_settings 键：
- model_profiles：[{id, name, base_url, model, image_support}]（JSON）
- default_model：profile id（字符串）
- model_keys：{profile_id: api_key}（JSON）
- baidu_ocr：{api_key, secret_key}（JSON）

env 兜底（只读，向后兼容 .env / 旧安装）：LLM_API_KEY 作用于 default profile、
MODEL_KEYS JSON、BAIDU_OCR_API_KEY/SECRET_KEY；LLM_BASE_URL/LLM_MODEL 覆盖
default profile 的地址/模型名。旧 settings.json（双角色/扁平/新形状）在 db 为空时
一次性导入（不含 key——旧机制里 key 从不落 settings.json）。
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
    """旧 settings.json（只作一次性导入来源，不再是真值；保留路径供导入与测试用）。"""
    return data_dir() / "settings.json"


def _legacy_file() -> dict:
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ---- app_settings KV 薄封装（JSON 值；db 为空时从旧 settings.json 一次性导入） ----

_KV_PROFILES = "model_profiles"
_KV_DEFAULT = "default_model"
_KV_KEYS = "model_keys"
_KV_BAIDU = "baidu_ocr"


def _kv_get(key: str) -> object | None:
    from . import db  # 函数级导入：db.py 顶部 import config，避免循环

    raw = db.get_setting(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _kv_set(key: str, value: object) -> None:
    from . import db

    db.set_setting(key, json.dumps(value, ensure_ascii=False))


def _legacy_profiles_from_file() -> list[ModelProfile]:
    """旧 settings.json（{models} / {llm,vlm} / 扁平）→ profile 列表（读侧迁移）。"""
    data = _legacy_file()
    raw = data.get("models")
    if isinstance(raw, list):
        out: list[ModelProfile] = []
        for item in raw:
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
        if out:
            return out
        return [_builtin_default_profile()]
    migrated: list[ModelProfile] = []
    llm_block = data.get("llm") if isinstance(data.get("llm"), dict) else None
    if llm_block is None and ("base_url" in data or "model" in data):
        llm_block = data  # 更旧的扁平格式
    if llm_block is not None:
        migrated.append(
            ModelProfile(
                id="default",
                name="默认模型",
                base_url=str(llm_block.get("base_url") or _DEFAULT_BASE_URL),
                model=str(llm_block.get("model") or _DEFAULT_MODEL),
                image_support=bool(llm_block.get("image_support")),
            )
        )
    else:
        migrated.append(_builtin_default_profile())
    vlm_block = data.get("vlm") if isinstance(data.get("vlm"), dict) else None
    if vlm_block is not None and str(vlm_block.get("base_url") or "").strip():
        migrated.append(
            ModelProfile(
                id="vision",
                name="视觉模型",
                base_url=str(vlm_block.get("base_url") or ""),
                model=str(vlm_block.get("model") or ""),
                image_support=True,
            )
        )
    return migrated


def model_profiles() -> list[ModelProfile]:
    """全部模型 profile。db 为空且旧 settings.json 有内容时一次性导入（write-through）；
    空配置不固化（每次回落内置默认，文件/写入后到即生效）。"""
    raw = _kv_get(_KV_PROFILES)
    if raw is None:
        if _legacy_file():
            imported = _legacy_profiles_from_file()
            _kv_set(_KV_PROFILES, [dataclasses.asdict(p) for p in imported])
            return _apply_env_override(imported)
        return _apply_env_override([_builtin_default_profile()])
    out: list[ModelProfile] = []
    for item in raw if isinstance(raw, list) else []:
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
    return _apply_env_override(out) if out else [_builtin_default_profile()]


def _apply_env_override(profiles: list[ModelProfile]) -> list[ModelProfile]:
    """LLM_BASE_URL/LLM_MODEL env 覆盖 default profile（开发期 .env 优先级习惯不变）。"""
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


def save_models(profiles: list[ModelProfile], default_id: str) -> None:
    """全量覆盖写模型列表 + 默认模型（API 层已做校验；env 覆盖只在读侧，不落库）。"""
    _kv_set(_KV_PROFILES, [dataclasses.asdict(p) for p in profiles])
    _kv_set(_KV_DEFAULT, default_id)


def default_model_id() -> str:
    profiles = model_profiles()
    want = _kv_get(_KV_DEFAULT)
    if isinstance(want, str) and want and any(p.id == want for p in profiles):
        return want
    if any(p.id == "default" for p in profiles):
        return "default"
    return profiles[0].id if profiles else "default"


def get_profile(pid: str) -> ModelProfile | None:
    return next((p for p in model_profiles() if p.id == pid), None)


def _model_keys() -> dict:
    """db 键为主，env MODEL_KEYS 补充 db 里没有的 profile（旧安装过渡）。"""
    raw = _kv_get(_KV_KEYS)
    keys: dict = dict(raw) if isinstance(raw, dict) else {}
    env_raw = os.environ.get("MODEL_KEYS")
    if env_raw:
        try:
            env_keys = json.loads(env_raw)
            if isinstance(env_keys, dict):
                for pid, k in env_keys.items():
                    if pid not in keys:
                        keys[pid] = k
        except ValueError:
            pass
    return keys


def model_key(pid: str) -> str | None:
    """profile 的 API Key：db（设置页写入）→ env MODEL_KEYS → LLM_API_KEY（default）。"""
    k = _model_keys().get(pid)
    if isinstance(k, str) and k:
        return k
    if pid == "default":
        return os.environ.get("LLM_API_KEY")
    return None


def set_model_key(pid: str, key: str) -> None:
    keys = _model_keys()
    keys[pid] = key
    _kv_set(_KV_KEYS, keys)


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
    raw = _kv_get(_KV_BAIDU)
    if isinstance(raw, dict):
        k = raw.get("api_key")
        if isinstance(k, str) and k:
            return k
    return os.environ.get("BAIDU_OCR_API_KEY")


def baidu_ocr_secret_key() -> str | None:
    raw = _kv_get(_KV_BAIDU)
    if isinstance(raw, dict):
        k = raw.get("secret_key")
        if isinstance(k, str) and k:
            return k
    return os.environ.get("BAIDU_OCR_SECRET_KEY")


def set_baidu_ocr_keys(api_key: str, secret_key: str) -> None:
    _kv_set(_KV_BAIDU, {"api_key": api_key, "secret_key": secret_key})


def sidecar_token() -> str | None:
    v = os.environ.get("SIDECAR_TOKEN")
    return v.strip() if v else None
