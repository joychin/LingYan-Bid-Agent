"""config.py：多模型 profile 读取、旧格式迁移、key 解析、vision 解析。"""

from app import config


def test_profiles_new_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"models": [{"id": "m1", "name": "A", "base_url": "https://a/v1", "model": "a-1", "image_support": true},'
        ' {"id": "m2", "name": "B", "base_url": "https://b/v1", "model": "b-1"}], "default_model": "m2"}',
        encoding="utf-8",
    )
    ps = config.model_profiles()
    assert [p.id for p in ps] == ["m1", "m2"]
    assert ps[0].image_support is True
    assert config.default_model_id() == "m2"


def test_default_model_fallbacks(tmp_path, monkeypatch):
    # default_model 不在列表 → 回落 id=default，再回落第一条
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"models": [{"id": "m1", "base_url": "https://a/v1", "model": "a-1"}], "default_model": "gone"}',
        encoding="utf-8",
    )
    assert config.default_model_id() == "m1"


def test_profiles_legacy_roles_migrate(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"llm": {"base_url": "https://a/v1", "model": "a-1"}, "vlm": {"base_url": "https://v/v1", "model": "v-1"}}',
        encoding="utf-8",
    )
    ps = {p.id: p for p in config.model_profiles()}
    assert set(ps) == {"default", "vision"}
    assert ps["vision"].image_support is True
    assert ps["default"].image_support is False
    # 空 vlm 块不算（vlm base_url 为空 = 未配置）
    (tmp_path / "settings.json").write_text(
        '{"llm": {"base_url": "https://a/v1", "model": "a-1"}, "vlm": {"base_url": "", "model": ""}}',
        encoding="utf-8",
    )
    assert [p.id for p in config.model_profiles()] == ["default"]


def test_profiles_empty_falls_back_to_builtin(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert [p.id for p in config.model_profiles()] == ["default"]
    assert config.llm_base_url() == "https://api.deepseek.com/v1"
    assert config.llm_model() == "deepseek-v4-flash"


def test_llm_shell_env_override_default_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"models": [{"id": "m1", "base_url": "https://a/v1", "model": "a-1"}], "default_model": "m1"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    assert config.llm_base_url() == "https://env.example/v1"
    assert config.llm_model() == "env-model"


def test_model_key_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_KEYS", '{"m1": "sk-1", "default": ""}')
    monkeypatch.setenv("LLM_API_KEY", "sk-legacy")
    assert config.model_key("m1") == "sk-1"
    # MODEL_KEYS 里 default 为空串 → 回退 LLM_API_KEY（浏览器模式 .env 兼容）
    assert config.model_key("default") == "sk-legacy"
    assert config.model_key("m9") is None
    monkeypatch.delenv("MODEL_KEYS")
    assert config.model_key("default") == "sk-legacy"
    assert config.model_key("m1") is None


def test_resolve_vision(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # 无任何 image_support → None
    (tmp_path / "settings.json").write_text(
        '{"models": [{"id": "m1", "base_url": "https://a/v1", "model": "a-1"}], "default_model": "m1"}',
        encoding="utf-8",
    )
    assert config.resolve_vision() is None
    # default 不支持但 m2 支持 → m2
    (tmp_path / "settings.json").write_text(
        '{"models": [{"id": "m1", "base_url": "https://a/v1", "model": "a-1"},'
        ' {"id": "m2", "base_url": "https://b/v1", "model": "b-1", "image_support": true}], "default_model": "m1"}',
        encoding="utf-8",
    )
    assert config.resolve_vision().id == "m2"
    # default 自己支持 → default 优先
    (tmp_path / "settings.json").write_text(
        '{"models": [{"id": "m1", "base_url": "https://a/v1", "model": "a-1", "image_support": true},'
        ' {"id": "m2", "base_url": "https://b/v1", "model": "b-1", "image_support": true}], "default_model": "m1"}',
        encoding="utf-8",
    )
    assert config.resolve_vision().id == "m1"
