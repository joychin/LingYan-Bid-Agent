"""config.py：多模型 profile 读取（app.db 真值）、settings.json 一次性导入、key 解析、vision 解析。"""

import json

from app import config, db


def _init(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()


def test_profiles_new_shape_db(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    config.save_models(
        [
            config.ModelProfile(id="m1", name="A", base_url="https://a/v1", model="a-1", image_support=True),
            config.ModelProfile(id="m2", name="B", base_url="https://b/v1", model="b-1"),
        ],
        "m2",
    )
    ps = config.model_profiles()
    assert [p.id for p in ps] == ["m1", "m2"]
    assert ps[0].image_support is True
    assert config.default_model_id() == "m2"


def test_default_model_fallbacks(tmp_path, monkeypatch):
    # default_model 不在列表 → 回落 id=default，再回落第一条
    _init(tmp_path, monkeypatch)
    config.save_models([config.ModelProfile(id="m1", name="A", base_url="https://a/v1", model="a-1")], "gone")
    assert config.default_model_id() == "m1"


def test_legacy_settings_json_imported_once(tmp_path, monkeypatch):
    """db 为空时旧 settings.json（双角色）一次性导入；之后文件不再被读。"""
    _init(tmp_path, monkeypatch)
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "llm": {"base_url": "https://a/v1", "model": "a-1", "image_support": True},
                "vlm": {"base_url": "https://v/v1", "model": "v-1"},
            }
        ),
        encoding="utf-8",
    )
    ps = {p.id: p for p in config.model_profiles()}
    assert set(ps) == {"default", "vision"}
    assert ps["vision"].image_support is True

    # 文件此后不再是真值：改文件不影响读取
    (tmp_path / "settings.json").write_text(json.dumps({"llm": {"base_url": "https://x/v1", "model": "x"}}), encoding="utf-8")
    assert config.model_profiles()[0].base_url == "https://a/v1"


def test_legacy_flat_settings_json_imported(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    (tmp_path / "settings.json").write_text(
        json.dumps({"base_url": "https://legacy.example.com/v1", "model": "legacy-model"}),
        encoding="utf-8",
    )
    dflt = config.model_profiles()[0]
    assert dflt.id == "default"
    assert dflt.base_url == "https://legacy.example.com/v1"


def test_profiles_empty_falls_back_to_builtin(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    assert [p.id for p in config.model_profiles()] == ["default"]
    assert config.llm_base_url() == "https://api.deepseek.com/v1"
    assert config.llm_model() == "deepseek-v4-flash"


def test_profiles_empty_with_env_override(tmp_path, monkeypatch):
    """空配置 + env 覆盖：builtin default 也要应用 env（e2e 曾因漏这条 401 两次）。"""
    _init(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("LLM_MODEL", "gw-model")
    ps = config.model_profiles()
    assert ps[0].base_url == "https://gateway.example/v1"
    assert ps[0].model == "gw-model"
    assert config.llm_base_url() == "https://gateway.example/v1"


def test_llm_shell_env_override_default_profile(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    config.save_models([config.ModelProfile(id="m1", name="A", base_url="https://a/v1", model="a-1")], "m1")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    assert config.llm_base_url() == "https://env.example/v1"
    assert config.llm_model() == "env-model"


def test_model_key_resolution(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-legacy")
    # db 写入优先
    config.set_model_key("m1", "sk-1")
    assert config.model_key("m1") == "sk-1"
    # default 走 LLM_API_KEY 兜底（.env 习惯）；db 写入后覆盖
    assert config.model_key("default") == "sk-legacy"
    config.set_model_key("default", "sk-db")
    assert config.model_key("default") == "sk-db"
    assert config.model_key("m9") is None
    # env MODEL_KEYS 兜底（旧安装）
    monkeypatch.setenv("MODEL_KEYS", '{"m2": "sk-2"}')
    assert config.model_key("m2") == "sk-2"


def test_resolve_vision(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    # 无任何 image_support → None
    config.save_models([config.ModelProfile(id="m1", name="A", base_url="https://a/v1", model="a-1")], "m1")
    assert config.resolve_vision() is None
    # default 不支持但 m2 支持 → m2
    config.save_models(
        [
            config.ModelProfile(id="m1", name="A", base_url="https://a/v1", model="a-1"),
            config.ModelProfile(id="m2", name="B", base_url="https://b/v1", model="b-1", image_support=True),
        ],
        "m1",
    )
    assert config.resolve_vision().id == "m2"
    # default 自己支持 → default 优先
    config.save_models(
        [
            config.ModelProfile(id="m1", name="A", base_url="https://a/v1", model="a-1", image_support=True),
            config.ModelProfile(id="m2", name="B", base_url="https://b/v1", model="b-1", image_support=True),
        ],
        "m1",
    )
    assert config.resolve_vision().id == "m1"


def test_baidu_keys_db_with_env_fallback(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    monkeypatch.setenv("BAIDU_OCR_API_KEY", "env-ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "env-sk")
    # env 兜底
    assert config.baidu_ocr_api_key() == "env-ak"
    # db 写入优先
    config.set_baidu_ocr_keys("db-ak", "db-sk")
    assert config.baidu_ocr_api_key() == "db-ak"
    assert config.baidu_ocr_secret_key() == "db-sk"
