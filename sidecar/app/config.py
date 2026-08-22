"""读取环境变量。数据目录默认 <sidecar>/data，可通过 DATA_DIR 覆盖。

base_url/model 优先级：环境变量 > data/settings.json > 内置默认值。
settings.json 是 Tauri 与 sidecar 共享的单一配置真值（Tauri 侧 lib.rs 也读写它）。
"""

import json
import os
from pathlib import Path

SIDECAR_ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or (SIDECAR_ROOT / "data")).resolve()


def app_db_path() -> Path:
    return data_dir() / "app.db"


def agent_db_path() -> Path:
    return data_dir() / "agent.db"


def workspace_dir() -> Path:
    return data_dir() / "workspace"


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


def llm_api_key() -> str | None:
    return os.environ.get("LLM_API_KEY")


def llm_base_url() -> str:
    v = os.environ.get("LLM_BASE_URL")
    if v:
        return v
    return str(_file_overrides().get("base_url") or "https://api.deepseek.com/v1")


def llm_model() -> str:
    v = os.environ.get("LLM_MODEL")
    if v:
        return v
    return str(_file_overrides().get("model") or "deepseek-v4-flash")


def sidecar_token() -> str | None:
    v = os.environ.get("SIDECAR_TOKEN")
    return v.strip() if v else None
