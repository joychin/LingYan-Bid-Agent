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
    from app.main import app

    with TestClient(app) as c:
        yield c
