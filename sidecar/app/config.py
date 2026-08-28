"""读取环境变量。数据目录默认 <sidecar>/data，可通过 DATA_DIR 覆盖。

base_url/model 优先级：环境变量 > data/settings.json > 内置默认值。
settings.json 是 Tauri 与 sidecar 共享的单一配置真值（Tauri 侧 lib.rs 也读写它），
结构为双角色嵌套 {llm:{base_url,model,image_support}, vlm:{...}}；llm 读侧兼容旧扁平 {base_url,model}。
vlm 无内置默认：base_url 为空即未配置（知识库图片/扫描件走降级链）。
百度云文档解析（PaddleOCR-VL）凭证 BAIDU_OCR_API_KEY/SECRET_KEY 只认环境变量
（同 API Key 纪律：Tauri 钥匙串 → spawn 注入 env），不落 settings.json。
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


def _file_role(role: str) -> dict:
    """读 settings.json 某角色块。llm 兼容旧扁平格式（顶层 base_url/model 视作 llm 块）。"""
    data = _file_overrides()
    block = data.get(role)
    if isinstance(block, dict):
        return block
    if role == "llm" and ("base_url" in data or "model" in data):
        return data
    return {}


def llm_api_key() -> str | None:
    return os.environ.get("LLM_API_KEY")


def llm_base_url() -> str:
    v = os.environ.get("LLM_BASE_URL")
    if v:
        return v
    return str(_file_role("llm").get("base_url") or "https://api.deepseek.com/v1")


def llm_model() -> str:
    v = os.environ.get("LLM_MODEL")
    if v:
        return v
    return str(_file_role("llm").get("model") or "deepseek-v4-flash")


def llm_image_support() -> bool:
    """对话模型是否声明支持图片输入（仅 settings.json llm 块，无 env 层）。"""
    return bool(_file_role("llm").get("image_support"))


def baidu_ocr_api_key() -> str | None:
    return os.environ.get("BAIDU_OCR_API_KEY")


def baidu_ocr_secret_key() -> str | None:
    return os.environ.get("BAIDU_OCR_SECRET_KEY")


def vlm_api_key() -> str | None:
    return os.environ.get("VLM_API_KEY")


def vlm_base_url() -> str:
    return os.environ.get("VLM_BASE_URL") or str(_file_role("vlm").get("base_url") or "")


def vlm_model() -> str:
    return os.environ.get("VLM_MODEL") or str(_file_role("vlm").get("model") or "")


def sidecar_token() -> str | None:
    v = os.environ.get("SIDECAR_TOKEN")
    return v.strip() if v else None
