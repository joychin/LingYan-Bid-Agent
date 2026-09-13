"""model_registry.py：models.dev 社区注册表缓存——拍平取值链、lookup 零联网、
TTL 守卫、失败保旧缓存、超限响应防护。"""

import time
import types

from app import model_registry


def _init(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


_API = {
    "openai": {
        "models": {
            # input 齐备：优先取 input
            "gpt-5": {"limit": {"context": 400000, "input": 272000, "output": 128000}},
            # 无 input：回退 context - output
            "gpt-4o": {"limit": {"context": 128000, "output": 16384}},
            # 无效 limit：跳过
            "broken": {"limit": {"context": 0}},
        }
    },
    "other": {
        "models": {
            # 无 limit 键：跳过
            "no-limit": {"name": "x"},
            # 只有 context：回退链末端
            "ctx-only": {"limit": {"context": 65536}},
        }
    },
    "not-a-provider": "junk",
}


class _FakeResponse(types.SimpleNamespace):
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self, url):
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok_response(api=None, content=b"{}"):
    return _FakeResponse(
        status_code=200,
        content=content,
        json=lambda: api if api is not None else {},
    )


def test_flatten_prefers_input_and_fallbacks():
    out = model_registry._flatten(_API)
    assert out["gpt-5"]["input"] == 272000
    assert out["gpt-5"]["context"] == 400000
    assert out["gpt-4o"]["input"] == 128000 - 16384
    assert out["ctx-only"]["input"] == 65536
    assert "broken" not in out
    assert "no-limit" not in out


def test_lookup_reads_cache_without_network(tmp_path, monkeypatch):
    """lookup 纯读本地缓存：即便 httpx 完全不可用也能命中（run 路径零联网铁则）。"""
    _init(tmp_path, monkeypatch)
    model_registry._write_cache(model_registry._flatten(_API))

    def _no_network(*a, **kw):
        raise AssertionError("lookup 不应发起任何网络请求")

    monkeypatch.setattr(model_registry.httpx, "Client", _no_network)

    assert model_registry.lookup("gpt-5") == 272000
    assert model_registry.lookup("GPT-5") == 272000  # 大小写归一兜底
    assert model_registry.lookup("nope") is None
    assert model_registry.lookup("") is None
    assert model_registry.lookup("   ") is None


def test_refresh_failure_keeps_old_cache(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    model_registry._write_cache({"gpt-5": {"input": 272000}})

    import httpx

    monkeypatch.setattr(
        model_registry.httpx,
        "Client",
        lambda **kw: _FakeClient([httpx.ConnectError("offline")]),
    )
    assert model_registry.refresh() is False
    assert model_registry.lookup("gpt-5") == 272000  # 旧缓存原样保留


def test_refresh_writes_flattened_cache(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    monkeypatch.setattr(
        model_registry.httpx,
        "Client",
        lambda **kw: _FakeClient([_ok_response(api=_API)]),
    )
    assert model_registry.refresh() is True
    assert model_registry.lookup("gpt-5") == 272000
    assert model_registry.lookup("ctx-only") == 65536


def test_refresh_rejects_oversize_response(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    monkeypatch.setattr(model_registry, "_MAX_BYTES", 4)
    monkeypatch.setattr(
        model_registry.httpx,
        "Client",
        lambda **kw: _FakeClient([_ok_response(content=b"12345678")]),
    )
    assert model_registry.refresh() is False
    assert model_registry.lookup("anything") is None  # 未写缓存


def test_maybe_refresh_ttl_guard(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(model_registry, "refresh", lambda: calls.append(1) or True)

    # 新鲜缓存：TTL 内不拉
    model_registry._write_cache({"m": {"input": 1}})  # fetched_at = now
    model_registry.maybe_refresh()
    assert calls == []

    # 过期缓存：拉
    stale = {"fetched_at": int(time.time()) - model_registry._TTL_SECONDS - 60, "models": {}}
    (tmp_path / "model_registry.json").write_text(
        __import__("json").dumps(stale), encoding="utf-8"
    )
    model_registry.maybe_refresh()
    assert calls == [1]
