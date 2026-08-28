"""/api/settings：多模型 profile 列表读写、迁移、校验、连通测试。"""

import json


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
    """旧 {llm, vlm} 双角色 → default + vision 两条 profile（读侧迁移）。"""
    from app import config as cfg

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


def test_get_settings_migrates_legacy_flat(client):
    """更旧扁平 {base_url, model} → default profile。"""
    from app import config as cfg

    cfg.settings_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.settings_path().write_text(
        json.dumps({"base_url": "https://legacy.example.com/v1", "model": "legacy-model"}),
        encoding="utf-8",
    )
    data = client.get("/api/settings").json()
    dflt = data["models"][0]
    assert dflt["id"] == "default"
    assert dflt["base_url"] == "https://legacy.example.com/v1"


def test_put_models_roundtrip_and_legacy_cleanup(client):
    from app import config as cfg

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

    raw = json.loads(cfg.settings_path().read_text(encoding="utf-8"))
    assert "llm" not in raw and "vlm" not in raw and "base_url" not in raw  # 旧键清掉
    assert raw["default_model"] == "m1"


def test_put_models_key_configured_via_env(client, monkeypatch):
    monkeypatch.setenv("MODEL_KEYS", '{"m1": "sk-test"}')
    client.put(
        "/api/settings/models",
        json={
            "models": [{"id": "m1", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"}],
            "default_model": "m1",
        },
    )
    data = client.get("/api/settings").json()
    assert data["models"][0]["key_configured"] is True


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


def test_settings_test_model(client, monkeypatch):
    monkeypatch.setenv("MODEL_KEYS", '{"m1": "sk-test"}')
    client.put(
        "/api/settings/models",
        json={
            "models": [{"id": "m1", "name": "X", "base_url": "https://x.example/v1", "model": "x-1"}],
            "default_model": "m1",
        },
    )

    # 未配 key 的模型 → 400
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
    r = client.get("/api/settings/test?model=m2")
    assert r.status_code == 400

    calls = {}

    class FakeResp:
        choices = [object()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls["kwargs"] = kwargs
            return FakeResp()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", lambda **kw: FakeClient(), raising=False)
    r = client.get("/api/settings/test?model=m1")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "model": "m1"}
    assert calls["kwargs"]["model"] == "x-1"

    # 不存在的模型 → 404
    assert client.get("/api/settings/test?model=nope").status_code == 404
    # 两个参数都没有 → 422
    assert client.get("/api/settings/test").status_code == 422


def test_settings_test_ocr_success(client, monkeypatch):
    from app import baidu_ocr

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")
    monkeypatch.setattr(baidu_ocr, "exchange_access_token", lambda force_refresh=False: "token-1")
    r = client.get("/api/settings/test?role=ocr")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "role": "ocr"}


def test_settings_test_ocr_failure(client, monkeypatch):
    from app import baidu_ocr

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")

    def boom(force_refresh=False):
        raise baidu_ocr.BaiduOcrUnavailable("获取 access_token 失败：bad credentials")

    monkeypatch.setattr(baidu_ocr, "exchange_access_token", boom)
    r = client.get("/api/settings/test?role=ocr")
    assert r.status_code == 502
    assert "bad credentials" in r.json()["detail"]


def test_message_with_model_profile_stored_on_run(client, monkeypatch):
    """POST /messages 带 model：run 行存档 profile id；未知 id 静默回落 default（空串）。"""
    import asyncio

    from app import db

    monkeypatch.setenv("MODEL_KEYS", '{"m1": "sk-1", "m2": "sk-2"}')
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
