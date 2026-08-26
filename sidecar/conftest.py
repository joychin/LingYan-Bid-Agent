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
    from app import agent as _agent_mod

    # agent 模块的 saver/_agent 是进程级单例且绑定首个 DATA_DIR；删会话接口会触碰
    # saver，跨测试必须复位，否则写到上一个测试的临时目录
    if _agent_mod._saver_conn is not None:
        _agent_mod._saver_conn.close()
    _agent_mod._saver_conn = None
    _agent_mod._saver = None
    _agent_mod._agent = None
    from app.main import app

    with TestClient(app) as c:
        yield c
