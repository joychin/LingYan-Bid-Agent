"""/api/settings：多模型 profile 列表读写（app.db 真值）、迁移、校验、连通测试、Key 端点。"""

import json

# 测试端点的自定义头（前端恒带；缺失 → 403，防任意网页免预检触发出站请求）
_PING = {"X-Sidecar-Ping": "1"}


def test_settings_test_requires_ping_header(client):
    """GET 是免预检简单请求：无自定义头一律 403（跨站触发被 CORS 预检挡住）。"""
    assert client.get("/api/settings/test?model=default").status_code == 403


def test_put_key_rejects_unknown_model(client):
    """孤儿 key 防护：只给已存在的 profile 存 Key（否则写错 id 静默存一个
    GET 永不可见的凭证）。"""
    r = client.put("/api/settings/keys", json={"model_id": "ghost", "api_key": "sk-x"})
    assert r.status_code == 404
    assert "不存在" in r.json()["detail"]


def test_get_settings_default_single_profile(client):
    data = client.get("/api/settings").json()
    # 空配置：内置默认单条（default），key 未配置
    assert [m["id"] for m in data["models"]] == ["default"]
    assert data["default_model"] == "default"
    assert data["models"][0]["key_configured"] is False
    assert data["models"][0]["image_support"] is False
    assert data["ocr"]["configured"] is False
    assert data["paths"]["data_dir"]
    assert data["paths"]["log_file"].endswith("sidecar.log")


def test_get_settings_migrates_legacy_roles(client):
    """旧 {llm, vlm} 双角色 settings.json → default + vision 两条 profile（一次性导入）。"""
    from app import config as cfg
    from app import db

    db.init_db()
    cfg.settings_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.settings_path().write_text(
        json.dumps(
            {
                "llm": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash", "image_support": True},
                "vlm": {"base_url": "https://dashscope.example/v1", "model": "qwen-vl-max"},
            }
        ),
        encoding="utf-8",
    )
    data = client.get("/api/settings").json()
    ids = {m["id"] for m in data["models"]}
    assert ids == {"default", "vision"}
    vision = next(m for m in data["models"] if m["id"] == "vision")
    assert vision["model"] == "qwen-vl-max"
    assert vision["image_support"] is True  # vlm 迁移恒标支持图片
    dflt = next(m for m in data["models"] if m["id"] == "default")
    assert dflt["image_support"] is True  # 旧 llm 块的 image_support 保留


def test_put_models_roundtrip(client):
    r = client.put(
        "/api/settings/models",
        json={
            "models": [
                {"id": "m1", "name": "DeepSeek 主力", "base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-v4-flash", "image_support": False},
                {"id": "m2", "name": "通义", "base_url": "https://dashscope.example/v1",
                 "model": "qwen-vl-max", "image_support": True},
            ],
            "default_model": "m1",
        },
    )
    assert r.status_code == 200
    data = client.get("/api/settings").json()
    assert [m["id"] for m in data["models"]] == ["m1", "m2"]
    assert data["default_model"] == "m1"
    # 真值在 db（settings.json 不再被写）
    from app import config as cfg

    assert not cfg.settings_path().exists() or "m1" not in cfg.settings_path().read_text(encoding="utf-8")


def test_put_models_context_window_roundtrip_and_validation(client):
    """context_window 可选字段：合法值 roundtrip（GET 带出、缺省 null）、非法值 422。"""
    r = client.put(
        "/api/settings/models",
        json={
            "models": [
                {"id": "m1", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"},
                {"id": "m2", "base_url": "https://x.example/v1", "model": "custom-x", "context_window": 128000},
            ],
            "default_model": "m1",
        },
    )
    assert r.status_code == 200
    data = client.get("/api/settings").json()
    by_id = {m["id"]: m for m in data["models"]}
    assert by_id["m1"]["context_window"] is None
    assert by_id["m2"]["context_window"] == 128000

    for bad in (0, -128, 1.5):
        r = client.put(
            "/api/settings/models",
            json={
                "models": [{"id": "m1", "base_url": "https://x.example/v1", "model": "m", "context_window": bad}],
                "default_model": "m1",
            },
        )
        assert r.status_code == 422, f"context_window={bad!r} 应 422"


def test_put_models_validations(client):
    base = {"models": [{"id": "m1", "base_url": "https://x.example/v1", "model": "m"}], "default_model": "m1"}
    # 空 id
    r = client.put("/api/settings/models", json={"models": [{**base["models"][0], "id": " "}], "default_model": "m1"})
    assert r.status_code == 422
    # id 重复
    r = client.put(
        "/api/settings/models",
        json={"models": base["models"] + base["models"], "default_model": "m1"},
    )
    assert r.status_code == 422
    # default 不在列表
    r = client.put("/api/settings/models", json={"models": base["models"], "default_model": "m9"})
    assert r.status_code == 422
    # base_url 非法（非本机 http）
    r = client.put(
        "/api/settings/models",
        json={"models": [{"id": "m1", "base_url": "http://evil.example/v1", "model": "m"}], "default_model": "m1"},
    )
    assert r.status_code == 422
    # model 名缺失
    r = client.put(
        "/api/settings/models",
        json={"models": [{"id": "m1", "base_url": "https://x.example/v1", "model": ""}], "default_model": "m1"},
    )
    assert r.status_code == 422


def test_put_models_background_roles_roundtrip(client):
    """后台任务角色：PUT 随 models 全量写，GET 回显；未知 id 拒绝；不传=保留现值。"""
    base = {
        "models": [
            {"id": "m1", "base_url": "https://x.example/v1", "model": "m"},
            {"id": "m2", "base_url": "https://y.example/v1", "model": "v", "image_support": True},
        ],
        "default_model": "m1",
    }
    client.put("/api/settings/models", json=base)
    # 带 roles 写入
    r = client.put(
        "/api/settings/models",
        json={**base, "background_roles": {"extract": "m2", "vision": "m2"}},
    )
    assert r.status_code == 200
    data = client.get("/api/settings").json()
    assert data["background_roles"] == {"extract": "m2", "vision": "m2"}
    # 不传 roles = 保留现值（模型弹窗保存不碰角色）
    client.put("/api/settings/models", json=base)
    assert client.get("/api/settings").json()["background_roles"] == {"extract": "m2", "vision": "m2"}
    # 引用未知模型 → 422
    r = client.put(
        "/api/settings/models",
        json={**base, "background_roles": {"extract": "ghost", "vision": ""}},
    )
    assert r.status_code == 422
    # 空串清空
    client.put("/api/settings/models", json={**base, "background_roles": {"extract": "", "vision": ""}})
    assert client.get("/api/settings").json()["background_roles"] == {"extract": "", "vision": ""}


def test_keys_endpoint_roundtrip_and_get_never_returns(client):
    """PUT /settings/keys 写本地库；GET 永不回读 Key（只回 key_configured 布尔）。"""
    client.put(
        "/api/settings/models",
        json={
            "models": [{"id": "m1", "name": "X", "base_url": "https://x.example/v1", "model": "x-1"}],
            "default_model": "m1",
        },
    )
    assert client.get("/api/settings").json()["models"][0]["key_configured"] is False

    r = client.put("/api/settings/keys", json={"model_id": "m1", "api_key": "sk-test-123"})
    assert r.status_code == 200
    data = client.get("/api/settings").json()
    assert data["models"][0]["key_configured"] is True
    assert "sk-test-123" not in json.dumps(data)  # GET 永不回读

    # 空值 422；未知模型也可写（先配 key 后配模型的顺序容忍）
    assert client.put("/api/settings/keys", json={"model_id": "m1", "api_key": " "}).status_code == 422
    assert client.put("/api/settings/keys", json={"model_id": " ", "api_key": "k"}).status_code == 422


def test_ocr_keys_endpoint(client):
    r = client.put("/api/settings/ocr-keys", json={"api_key": "ak-1", "secret_key": "sk-1"})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["ocr"]["configured"] is True
    # 空值 422
    assert client.put("/api/settings/ocr-keys", json={"api_key": "", "secret_key": "s"}).status_code == 422


def test_settings_test_model(client):
    client.put(
        "/api/settings/models",
        json={
            "models": [
                {"id": "m1", "name": "X", "base_url": "https://x.example/v1", "model": "x-1"},
                {"id": "m2", "name": "Y", "base_url": "https://y.example/v1", "model": "y-1"},
            ],
            "default_model": "m1",
        },
    )
    # 未配 key 的模型 → 400
    r = client.get("/api/settings/test?model=m2", headers=_PING)
    assert r.status_code == 400

    # 配 key 后成功（mock OpenAI）
    client.put("/api/settings/keys", json={"model_id": "m1", "api_key": "sk-test"})
    calls = {}

    class FakeResp:
        choices = [object()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls["kwargs"] = kwargs
            return FakeResp()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai

    original = openai.OpenAI
    openai.OpenAI = lambda **kw: FakeClient()
    try:
        r = client.get("/api/settings/test?model=m1", headers=_PING)
    finally:
        openai.OpenAI = original
    assert r.status_code == 200
    assert r.json() == {"ok": True, "model": "m1"}
    assert calls["kwargs"]["model"] == "x-1"

    # 不存在的模型 → 404；两个参数都没有 → 422
    assert client.get("/api/settings/test?model=nope", headers=_PING).status_code == 404
    assert client.get("/api/settings/test", headers=_PING).status_code == 422


def test_settings_test_ocr_success(client, monkeypatch):
    from app import baidu_ocr

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")
    monkeypatch.setattr(baidu_ocr, "exchange_access_token", lambda force_refresh=False: "token-1")
    r = client.get("/api/settings/test?role=ocr", headers=_PING)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "role": "ocr"}


def test_settings_test_ocr_failure(client, monkeypatch):
    from app import baidu_ocr

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")

    def boom(force_refresh=False):
        raise baidu_ocr.BaiduOcrUnavailable("获取 access_token 失败：bad credentials")

    monkeypatch.setattr(baidu_ocr, "exchange_access_token", boom)
    r = client.get("/api/settings/test?role=ocr", headers=_PING)
    assert r.status_code == 502
    assert "bad credentials" in r.json()["detail"]


def test_message_with_model_profile_stored_on_run(client, monkeypatch):
    """POST /messages 带 model：run 行存档 profile id；未知 id 静默回落 default（空串）。"""
    import asyncio

    from app import db

    client.put(
        "/api/settings/models",
        json={
            "models": [
                {"id": "m1", "name": "A", "base_url": "https://a.example/v1", "model": "a-1"},
                {"id": "m2", "name": "B", "base_url": "https://b.example/v1", "model": "b-1"},
            ],
            "default_model": "m1",
        },
    )
    from tests.util import create_conversation

    conv = create_conversation(client)
    cid = conv["conversation"]["id"] if "conversation" in conv else conv["id"]

    captured = []

    async def fake_run_stream(cid_, rid_, *args, **kwargs):
        captured.append(kwargs.get("model"))
        db.finish_run(rid_, "completed")

    monkeypatch.setattr("app.api.conversations.run_stream", fake_run_stream)

    async def fake_titler(cid_, content):
        return None

    monkeypatch.setattr("app.api.conversations.titler.maybe_generate_title", fake_titler)

    def _post(model_value):
        r = client.post(f"/api/conversations/{cid}/messages", json={"content": "你好", "model": model_value})
        assert r.status_code == 202, r.text
        return db.get_run(r.json()["run_id"])

    run = _post("m2")
    assert run["model"] == "m2"
    assert captured == ["m2"]
    run = _post("gone")  # 已删/未知 profile → 回落 default
    assert run["model"] == ""
    assert captured == ["m2", None]
    assert asyncio.iscoroutinefunction(fake_run_stream)
