"""孤儿 sidecar 清扫锚点（sidecar.pid，2026-09-12）。

sidecar 就绪时写 data/sidecar.pid（壳被强杀时残留，供 Rust 侧下次启动核身份清扫）、
优雅关停时删除。Rust 侧清扫逻辑无测试基建，手动验收（起应用→强杀壳→重启无孤儿）。
"""

import json
import os

from fastapi.testclient import TestClient


def test_sidecar_pidfile_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "SIDECAR_TOKEN",
                "BAIDU_OCR_API_KEY", "BAIDU_OCR_SECRET_KEY", "MODEL_KEYS"):
        monkeypatch.delenv(var, raising=False)
    from app import agent as _agent_mod

    if _agent_mod._saver_conn is not None:
        _agent_mod._saver_conn.close()
    _agent_mod._saver_conn = None
    _agent_mod._saver = None
    _agent_mod._agent = None

    from app.main import app

    pidfile = tmp_path / "data" / "sidecar.pid"
    with TestClient(app):
        assert pidfile.exists()
        assert json.loads(pidfile.read_text(encoding="utf-8"))["pid"] == os.getpid()
    # 优雅关停（with 退出）即删除——正常退出不留锚点，孤儿只在强杀时残留
    assert not pidfile.exists()
