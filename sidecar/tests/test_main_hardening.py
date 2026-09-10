"""入口加固（2026-09-10 review 批次 A）：

- Origin 守卫：浏览器开发模式（无 SIDECAR_TOKEN）下，跨站点对 127.0.0.1 的
  「简单请求」POST（text/plain 免预检）可盲打 /api 状态变更端点；带 Origin 且
  不在本机白名单 → 403。无 Origin（TestClient/curl/Tauri）放行、白名单放行。
- 文档端点关闭：/docs、/openapi.json 不在 /api 前缀下吃不到 token 中间件，
  免鉴权暴露全 API 形状——直接 404。
"""

from tests.util import create_task


def test_origin_guard_blocks_foreign_origin(client):
    task = create_task(client)  # 无 Origin 的正常请求先证明通路
    assert task["task"]["id"].startswith("t_")
    r = client.post(
        "/api/tasks",
        json={"title": "跨站任务"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "origin not allowed"}


def test_origin_guard_allows_local_and_absent(client):
    # 无 Origin（TestClient/curl）放行
    assert client.get("/api/healthz").status_code == 200
    # 本机白名单：Vite 端口 / 127.0.0.1 任意端口 / Tauri webview 两种 origin 形态
    for origin in (
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "http://tauri.localhost",
        "tauri://localhost",
    ):
        r = client.get("/api/healthz", headers={"Origin": origin})
        assert r.status_code == 200, origin
    # 带白名单 Origin 的 POST 也放行（前端 fetch 同源形态）
    r = client.post(
        "/api/tasks",
        json={"title": "本机任务"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert r.status_code == 201, r.text


def test_docs_endpoints_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
