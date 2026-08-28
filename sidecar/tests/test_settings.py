"""/api/settings：双角色（llm/vlm）嵌套读写、无 key 不 500、base_url 校验、持久化、连通测试。"""

import json

import pytest


def test_put_settings_without_key_ok(client):
    # 未配置 LLM_API_KEY 时也能保存 base_url/model（不应重建 agent 而 500）
    r = client.put(
        "/api/settings",
        json={"llm": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"}},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_put_settings_persists_and_gets(client):
    client.put("/api/settings", json={"llm": {"base_url": "https://example.com/v1", "model": "my-model"}})
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["llm"]["base_url"] == "https://example.com/v1"
    assert data["llm"]["model"] == "my-model"
    assert data["llm"]["key_configured"] is False
    assert data["vlm"]["base_url"] == ""  # 未配置 vlm 返回空而非报错


def test_put_settings_vlm_persist_and_clear(client):
    client.put(
        "/api/settings",
        json={"vlm": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-vl-max"}},
    )
    r = client.get("/api/settings").json()
    assert r["vlm"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert r["vlm"]["model"] == "qwen-vl-max"

    # base_url 传空串 = 清除 vlm 配置
    client.put("/api/settings", json={"vlm": {"base_url": "", "model": ""}})
    assert client.get("/api/settings").json()["vlm"]["base_url"] == ""
    # llm 配置不受 vlm 清除影响
    assert client.get("/api/settings").json()["llm"]["base_url"] != ""


def test_settings_migrates_legacy_flat_format(client, monkeypatch):
    # 旧扁平 settings.json（顶层 base_url/model）读侧仍生效（Rust 侧同款兼容）
    from app import config as cfg

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    cfg.settings_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.settings_path().write_text(
        json.dumps({"base_url": "https://legacy.example.com/v1", "model": "legacy-model"}),
        encoding="utf-8",
    )
    assert cfg.llm_base_url() == "https://legacy.example.com/v1"
    assert cfg.llm_model() == "legacy-model"


def test_put_settings_writes_nested_and_drops_legacy_keys(client):
    # 写入新结构时清掉旧扁平顶层键，避免两处真值
    client.put("/api/settings", json={"llm": {"base_url": "https://example.com/v1", "model": "m1"}})
    from app import config as cfg

    data = json.loads(cfg.settings_path().read_text(encoding="utf-8"))
    assert data["llm"] == {"base_url": "https://example.com/v1", "model": "m1"}
    assert "base_url" not in data and "model" not in data


@pytest.mark.parametrize(
    "url",
    [
        "ftp://x",
        "not a url",
        "//no-scheme",
        "http://evil.example.com/v1",  # 非本机 http 必须拒绝
        "javascript:alert(1)",
    ],
)
def test_put_settings_rejects_bad_base_url(client, url):
    r = client.put("/api/settings", json={"llm": {"base_url": url}})
    assert r.status_code == 422
    r2 = client.put("/api/settings", json={"vlm": {"base_url": url}})
    assert r2.status_code == 422


def test_put_settings_allows_loopback_http(client):
    # Ollama 等本地 http 端点应放行
    r = client.put("/api/settings", json={"llm": {"base_url": "http://127.0.0.1:11434/v1"}})
    assert r.status_code == 200


def test_settings_test_unconfigured_vlm(client):
    r = client.get("/api/settings/test?role=vlm")
    assert r.status_code == 400
    assert "VLM" in r.json()["detail"]


def test_settings_test_bad_role(client):
    assert client.get("/api/settings/test?role=nope").status_code == 422


def test_settings_test_llm_success(client, monkeypatch):
    calls = {}

    class FakeResp:
        choices = [object()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls["kwargs"] = kwargs
            return FakeResp()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()


    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr("openai.OpenAI", lambda **kw: FakeClient(), raising=False)
    r = client.get("/api/settings/test?role=llm")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "role": "llm"}


def test_image_support_persist_and_read(client):
    # image_support 仅 llm 角色消费；不触发重建（无 key 时 PUT 恒 200 已有覆盖）
    client.put(
        "/api/settings",
        json={"llm": {"base_url": "https://example.com/v1", "model": "m1", "image_support": True}},
    )
    data = client.get("/api/settings").json()
    assert data["llm"]["image_support"] is True

    # 回写 base_url 不带该字段时保留原值（_persist 合并不清键）
    client.put("/api/settings", json={"llm": {"model": "m2"}})
    assert client.get("/api/settings").json()["llm"]["image_support"] is True

    # 可关回
    client.put("/api/settings", json={"llm": {"image_support": False}})
    assert client.get("/api/settings").json()["llm"]["image_support"] is False

    # vlm 不消费该字段（持久化块不落 vlm.image_support）
    from app import config as cfg

    raw = json.loads(cfg.settings_path().read_text(encoding="utf-8"))
    client.put("/api/settings", json={"vlm": {"base_url": "https://example.com/vl", "model": "vl-1"}})
    raw = json.loads(cfg.settings_path().read_text(encoding="utf-8"))
    assert "image_support" not in raw.get("vlm", {})


def test_get_settings_ocr_and_paths(client, monkeypatch):
    data = client.get("/api/settings").json()
    assert data["ocr"]["configured"] is False
    assert data["paths"]["data_dir"]
    assert data["paths"]["log_file"].endswith("sidecar.log")

    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")
    assert client.get("/api/settings").json()["ocr"]["configured"] is True

    # 只有 AK 不算配置齐
    monkeypatch.delenv("BAIDU_OCR_SECRET_KEY", raising=False)
    assert client.get("/api/settings").json()["ocr"]["configured"] is False


def test_settings_test_ocr_unconfigured(client):
    r = client.get("/api/settings/test?role=ocr")
    assert r.status_code == 400
    assert "文档解析" in r.json()["detail"]


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
