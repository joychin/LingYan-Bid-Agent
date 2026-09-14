"""/api/settings：多模型 profile 列表读写（app.db 真值）、迁移、校验、连通测试、Key 端点。"""

import json

# 测试端点的自定义头（前端恒带；缺失 → 403，防任意网页免预检触发出站请求）
_PING = {"X-Sidecar-Ping": "1"}


def test_settings_test_requires_ping_header(client):
    """GET 是免预检简单请求：无自定义头一律 403（跨站触发被 CORS 预检挡住）。"""
    assert client.get("/api/settings/test?role=ocr").status_code == 403


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


def test_settings_test_model_draft(client, monkeypatch):
    """POST /settings/test-model：测表单草稿值——草稿 Key 直测 / key_ref 借用已存 Key / 入参校验。"""
    import openai

    calls = {}

    class FakeResp:
        choices = [object()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return FakeResp()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: FakeClient())

    # 草稿 Key 直测（不需要先保存模型、不落库）
    r = client.post(
        "/api/settings/test-model",
        json={"base_url": "https://x.example/v1", "model": "x-1", "api_key": "sk-draft"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["message"] == "连接正常"
    assert body["latency_ms"] >= 0
    assert calls["model"] == "x-1"
    # ping 不带 token 上限：GPT-5/o 系拒绝 max_tokens，带了就是假失败（2026-09-12）
    assert "max_tokens" not in calls

    # 未提供 Key（也无 key_ref）→ 400
    assert client.post("/api/settings/test-model", json={"base_url": "https://x.example/v1", "model": "x-1"}).status_code == 400

    # key_ref 借用已保存 profile 的 Key（编辑未改 Key / 同厂商复用两条路径）
    client.put(
        "/api/settings/models",
        json={"models": [{"id": "m1", "name": "X", "base_url": "https://x.example/v1", "model": "x-1"}], "default_model": "m1"},
    )
    client.put("/api/settings/keys", json={"model_id": "m1", "api_key": "sk-saved"})
    r = client.post("/api/settings/test-model", json={"base_url": "https://x.example/v1", "model": "x-1", "key_ref": "m1"})
    assert r.status_code == 200 and r.json()["ok"] is True

    # 入参非法 → 422（非本机 http 地址 / 空模型名）
    assert client.post("/api/settings/test-model", json={"base_url": "http://evil.example/v1", "model": "x", "api_key": "k"}).status_code == 422
    assert client.post("/api/settings/test-model", json={"base_url": "https://x.example/v1", "model": " ", "api_key": "k"}).status_code == 422


def test_settings_key_ref_binds_base_url(client, monkeypatch):
    """key_ref 借用绑定地址（2026-09-12）：已存 Key 只允许发往其所属地址。

    不一致 → 400 人话（Key 不出库、不发往陌生地址），test-model 与
    available-models 两条路径同款收口；尾斜杠变体视为一致放行。
    """
    import openai

    class FakeResp:
        choices = [object()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kw: type("C", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})(),
    )
    client.put(
        "/api/settings/models",
        json={"models": [{"id": "m1", "base_url": "https://x.example/v1", "model": "x-1"}], "default_model": "m1"},
    )
    client.put("/api/settings/keys", json={"model_id": "m1", "api_key": "sk-saved"})

    # 地址不一致 → 400（不再拿 m1 的 Key 去连新地址）
    r = client.post("/api/settings/test-model", json={"base_url": "https://evil.example/v1", "model": "x-1", "key_ref": "m1"})
    assert r.status_code == 400
    assert "不一致" in r.json()["detail"]

    r = client.post("/api/settings/available-models", json={"base_url": "https://evil.example/v1", "key_ref": "m1"})
    assert r.status_code == 400
    assert "不一致" in r.json()["detail"]

    # 尾斜杠变体视为一致 → 放行
    r = client.post("/api/settings/test-model", json={"base_url": "https://x.example/v1/", "model": "x-1", "key_ref": "m1"})
    assert r.status_code == 200 and r.json()["ok"] is True

    # 草稿 api_key 直填不经绑定（用户自己填的 Key 自己负责去向）
    r = client.post("/api/settings/test-model", json={"base_url": "https://evil.example/v1", "model": "x-1", "api_key": "sk-draft"})
    assert r.status_code == 200

    # key_ref 指向不存在的模型 → 400
    r = client.post("/api/settings/test-model", json={"base_url": "https://x.example/v1", "model": "x-1", "key_ref": "ghost"})
    assert r.status_code == 400
    assert "不存在" in r.json()["detail"]


def test_settings_test_model_upstream_error_is_200_with_human_message(client, monkeypatch):
    """上游错误归一：401/402/404 都返回 200 + ok=false + 人话（前端就地展示，不靠 4xx 猜）。"""
    import httpx
    import openai

    def make_client(status: int, body_message: str = "boom"):
        class FakeCompletions:
            def create(self, **kwargs):
                req = httpx.Request("POST", "https://x.example/v1/chat/completions")
                resp = httpx.Response(status, request=req, json={"error": {"message": body_message}})
                raise openai.APIStatusError(body_message, response=resp, body=None)

        return type("C", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})()

    def make_openai(client_obj):
        def factory(**_kw):
            return client_obj
        return factory

    cases = [
        (401, "boom", "API Key 无效"),
        (402, "boom", "欠费"),
        (404, "boom", "404"),
        # 实测形态：DeepSeek 对未知模型名回 400、自建网关回 422，原文带模型线索
        (400, "The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed bad-model.", "模型名不被该服务商支持"),
        (422, "model not found: gpt-5.6-luna", "模型名不被该服务商支持"),
        (400, "some other bad request", "连接失败（HTTP 400）"),
    ]
    for status, raw, keyword in cases:
        monkeypatch.setattr(openai, "OpenAI", make_openai(make_client(status, raw)))
        r = client.post(
            "/api/settings/test-model",
            json={"base_url": "https://x.example/v1", "model": "x-1", "api_key": "k"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert keyword in body["message"], f"status={status} 文案={body['message']!r}"
        assert body["image_ok"] is None  # 不带 with_image 时无图片探测字段值


def test_settings_test_model_image_probe(client, monkeypatch):
    """with_image=True：文本 ping 通过后附带图片探测；拒绝/接受/文本失败三态。"""
    import httpx
    import openai

    create_kwargs: list[dict] = []

    def make_openai(reject_image: bool, text_fails: bool = False):
        class FakeCompletions:
            def create(self, **kwargs):
                create_kwargs.append(kwargs)
                content = kwargs.get("messages", [{}])[0].get("content")
                if isinstance(content, list):  # 图片 ping（content 为多段数组）
                    if reject_image:
                        req = httpx.Request("POST", "https://x.example/v1/chat/completions")
                        resp = httpx.Response(400, request=req, json={"error": {"message": "image not supported"}})
                        raise openai.APIStatusError("image not supported", response=resp, body=None)
                elif text_fails:
                    req = httpx.Request("POST", "https://x.example/v1/chat/completions")
                    resp = httpx.Response(401, request=req, json={"error": {"message": "bad key"}})
                    raise openai.APIStatusError("bad key", response=resp, body=None)

                class FakeResp:
                    choices = [object()]
                return FakeResp()

        client_obj = type("C", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})()
        return lambda **_kw: client_obj

    def post(with_image):
        return client.post(
            "/api/settings/test-model",
            json={"base_url": "https://x.example/v1", "model": "x-1", "api_key": "k", "with_image": with_image},
        ).json()

    # 图片被拒（文本模型）：主结果 ok + image_ok=false + 人话
    monkeypatch.setattr(openai, "OpenAI", make_openai(reject_image=True))
    body = post(with_image=True)
    assert body["ok"] is True
    assert body["image_ok"] is False
    assert "不支持图片输入" in body["image_message"]

    # 图片接受（视觉模型）：image_ok=true
    monkeypatch.setattr(openai, "OpenAI", make_openai(reject_image=False))
    body = post(with_image=True)
    assert body["image_ok"] is True
    assert "接受" in body["image_message"]
    # 图片 ping 的载荷必须是多段 content（text + image_url）
    # （由 make_openai 内 isinstance 分支隐式验证：list 路径才走拒绝逻辑）

    # 文本 ping 就失败：不附带图片探测（image_ok 保持 None）
    monkeypatch.setattr(openai, "OpenAI", make_openai(reject_image=False, text_fails=True))
    body = post(with_image=True)
    assert body["ok"] is False
    assert body["image_ok"] is None

    # 不带 with_image：不探测图片
    monkeypatch.setattr(openai, "OpenAI", make_openai(reject_image=True))
    body = post(with_image=False)
    assert body["image_ok"] is None

    # 文本/图片 ping 均不带 token 上限（GPT-5/o 系拒绝 max_tokens，2026-09-12）
    assert create_kwargs and all("max_tokens" not in kw for kw in create_kwargs)


def test_settings_available_models(client, monkeypatch):
    """POST /settings/available-models：拉厂商 /models（去重排序）；失败归一 ok=false；无 Key 400。"""
    import openai

    class FakeModel:
        def __init__(self, mid):
            self.id = mid

    class FakeModels:
        def list(self):
            return type("R", (), {"data": [FakeModel("b-1"), FakeModel("a-1"), FakeModel("a-1")]})()

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: type("C", (), {"models": FakeModels()})())
    r = client.post("/api/settings/available-models", json={"base_url": "https://x.example/v1", "api_key": "k"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "models": ["a-1", "b-1"], "error": None}

    # 未提供 Key → 400
    assert client.post("/api/settings/available-models", json={"base_url": "https://x.example/v1"}).status_code == 400

    # 上游不支持 /models → 200 + ok=false + error（前端静默回落静态预设）
    class BoomModels:
        def list(self):
            raise RuntimeError("no /models endpoint")

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: type("C", (), {"models": BoomModels()})())
    r = client.post("/api/settings/available-models", json={"base_url": "https://x.example/v1", "api_key": "k"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "no /models" in r.json()["error"]


def test_settings_copy_key(client):
    """PUT /settings/keys/copy：服务端读源写目标，Key 仍不出库；源/目标/同源校验齐全。"""
    client.put(
        "/api/settings/models",
        json={
            "models": [
                {"id": "m1", "base_url": "https://x.example/v1", "model": "x-1"},
                {"id": "m2", "base_url": "https://x.example/v1", "model": "x-2"},
            ],
            "default_model": "m1",
        },
    )
    client.put("/api/settings/keys", json={"model_id": "m1", "api_key": "sk-shared"})
    assert client.get("/api/settings").json()["models"][1]["key_configured"] is False

    r = client.put("/api/settings/keys/copy", json={"from": "m1", "to": "m2"})
    assert r.status_code == 200
    data = client.get("/api/settings").json()
    assert data["models"][1]["key_configured"] is True
    assert "sk-shared" not in json.dumps(data)  # 依然永不回读

    # 源无 Key → 400；未知源/目标 → 404；同源 → 422
    client.put(
        "/api/settings/models",
        json={
            "models": [
                {"id": "m1", "base_url": "https://x.example/v1", "model": "x-1"},
                {"id": "m3", "base_url": "https://x.example/v1", "model": "x-3"},
            ],
            "default_model": "m1",
        },
    )
    assert client.put("/api/settings/keys/copy", json={"from": "m3", "to": "m1"}).status_code == 400
    assert client.put("/api/settings/keys/copy", json={"from": "ghost", "to": "m1"}).status_code == 404
    assert client.put("/api/settings/keys/copy", json={"from": "m1", "to": "ghost"}).status_code == 404
    assert client.put("/api/settings/keys/copy", json={"from": "m1", "to": "m1"}).status_code == 422


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
