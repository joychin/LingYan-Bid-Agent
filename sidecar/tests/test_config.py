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


def test_image_support_from_file_only(tmp_path, monkeypatch):
    # image_support 只读 settings.json（无 env 层）；缺省 False
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"llm": {"base_url": "https://x/v1", "model": "m", "image_support": true}}', encoding="utf-8"
    )
    assert config.llm_image_support() is True

    (tmp_path / "settings.json").write_text(
        '{"llm": {"base_url": "https://x/v1", "model": "m"}}', encoding="utf-8"
    )
    assert config.llm_image_support() is False


def test_baidu_ocr_keys_env_only(tmp_path, monkeypatch):
    # 凭证只认 env，settings.json 里的同名键不生效
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"baidu_ocr": {"api_key": "from-file", "secret_key": "from-file"}}', encoding="utf-8"
    )
    assert config.baidu_ocr_api_key() is None
    assert config.baidu_ocr_secret_key() is None
    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")
    assert config.baidu_ocr_api_key() == "ak"
    assert config.baidu_ocr_secret_key() == "sk"
