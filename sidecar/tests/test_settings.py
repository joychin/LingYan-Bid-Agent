"""/api/settings：无 key 不 500、base_url 校验、持久化。"""

import pytest


def test_put_settings_without_key_ok(client):
    # 未配置 LLM_API_KEY 时也能保存 base_url/model（不应重建 agent 而 500）
    r = client.put("/api/settings", json={"base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_put_settings_persists_and_gets(client):
    client.put("/api/settings", json={"base_url": "https://example.com/v1", "model": "my-model"})
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {"base_url": "https://example.com/v1", "model": "my-model"}


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
    r = client.put("/api/settings", json={"base_url": url})
    assert r.status_code == 422


def test_put_settings_allows_loopback_http(client):
    # Ollama 等本地 http 端点应放行
    r = client.put("/api/settings", json={"base_url": "http://127.0.0.1:11434/v1"})
    assert r.status_code == 200
