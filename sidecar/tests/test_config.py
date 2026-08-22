"""config.py 读取优先级：env > data/settings.json > 默认值。"""

from app import config


def test_env_wins_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    (tmp_path / "settings.json").write_text(
        '{"base_url": "https://file.example/v1", "model": "from-file"}', encoding="utf-8"
    )
    assert config.llm_base_url() == "https://env.example/v1"
    assert config.llm_model() == "env-model"


def test_file_override_without_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    (tmp_path / "settings.json").write_text(
        '{"base_url": "https://file.example/v1", "model": "from-file"}', encoding="utf-8"
    )
    assert config.llm_base_url() == "https://file.example/v1"
    assert config.llm_model() == "from-file"


def test_defaults_without_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert config.llm_base_url() == "https://api.deepseek.com/v1"
    assert config.llm_model() == "deepseek-v4-flash"
