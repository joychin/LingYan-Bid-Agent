"""共享测试夹具。

放在 sidecar/ 根目录：pytest 会把 conftest 所在目录加入 sys.path，保证 `import app` 可用。
所有测试用独立的临时 DATA_DIR，不触碰真实数据；LLM_API_KEY 置空，避免触发真实调用。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("BAIDU_OCR_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_OCR_SECRET_KEY", raising=False)
    monkeypatch.delenv("MODEL_KEYS", raising=False)
    from app import baidu_ocr as _baidu

    _baidu._reset_token_cache()
    from app import agent as _agent_mod

    # agent 模块的 saver/_agent 是进程级单例且绑定首个 DATA_DIR；删会话接口会触碰
    # saver，跨测试必须复位，否则写到上一个测试的临时目录
    if _agent_mod._saver_conn is not None:
        _agent_mod._saver_conn.close()
    _agent_mod._saver_conn = None
    _agent_mod._saver = None
    _agent_mod._agent = None
    from app import model_registry as _registry

    # 设置动作（PUT /settings/models 等）会 fire-and-forget 拉 models.dev（离线/
    # 沙箱下 8s 超时）：测试打桩成 no-op——此前裸 create_task 无人等、随 TestClient
    # 退出被弃掉才没拖慢套件；排空逻辑会如实等完它。刷新本体在 test_model_registry
    # 有独立覆盖，不依赖端点侧触发。
    monkeypatch.setattr(_registry, "maybe_refresh", lambda: None)

    from app.main import app

    # 手工 enter/exit 而不是 `with`：yield 后、lifespan shutdown 前先排空 bg 后台
    # 任务——KB/素材入库走 bg 强引用集合 + ingest 线程池，TestClient 退出不等它们，
    # 上个测试的解析线程仍持旧临时 DATA_DIR 的连接写库，与下一测试建新库撞
    # 「database is locked」锁（偶发 flake，2026-09-17 批次④止血）。任务跑在
    # TestClient 的 portal 事件循环上，主线程有界等待即可推进；超时兜底防挂死。
    import time as _time

    from app import bg as _bg

    test_client = TestClient(app)
    test_client.__enter__()
    try:
        yield test_client
        deadline = _time.monotonic() + 15.0
        while _bg._tasks and _time.monotonic() < deadline:
            _time.sleep(0.01)  # 细粒度轮询：数百个测试各等一轮，粗粒度会累计拖慢套件
        if _bg._tasks:
            pending = [getattr(t.get_coro(), "__qualname__", "?") for t in _bg._tasks]
            print(f"[conftest] 后台任务 15s 未排空（测试隔离可能受影响）：{pending}")
    finally:
        test_client.__exit__(None, None, None)
