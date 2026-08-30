"""fetch_url 工具：协议限制、逐跳 SSRF 校验、content-type 白名单、正文抽取回退、截断与失败路径（mock httpx，不依赖真网）。

失败约定：一律返回 "[抓取失败] …" 字符串、不抛异常（deepagents 0.7.7 工具异常会打崩整个 run）。
正文抽取：text/html 走 trafilatura.extract（mock 掉）；抽取为 None/抛异常时回退原文。
"""

from unittest import mock

import httpx
import pytest

import app.tools.web_fetch as web_fetch
from app.tools.web_fetch import fetch_url as fetch_tool

_PRIVATE_HOSTS = {"127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5", "192.168.1.1"}

# autouse fixture 会替换 _host_allows；本体单测用 import 时捕获的原函数
_REAL_HOST_ALLOWS = web_fetch._host_allows


@pytest.fixture(autouse=True)
def _fake_host_allows(monkeypatch):
    """测试不真解析 DNS：内网名单拒绝、其余放行（_host_allows 本体另测字面量 IP）。"""
    monkeypatch.setattr(
        web_fetch, "_host_allows", lambda host: (host or "").lower() not in _PRIVATE_HOSTS
    )


def _resp(status=200, ctype="text/html", text="hello"):
    return httpx.Response(
        status,
        headers={"content-type": ctype},
        text=text,
        request=httpx.Request("GET", "https://example.com"),
    )


def _redirect(location, url="https://example.com/a"):
    req = httpx.Request("GET", url)
    return httpx.Response(302, headers={"location": location}, request=req)


def test_rejects_non_https():
    assert fetch_tool.invoke({"url": "http://example.com"}).startswith("[抓取失败]")


def test_rejects_private_initial_host():
    assert fetch_tool.invoke({"url": "https://127.0.0.1:8765/api"}).startswith("[抓取失败]")


def test_redirect_to_http_denied():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _redirect(
            "http://127.0.0.1:8765/api/healthz"
        )
        out = fetch_tool.invoke({"url": "https://example.com/news"})
    assert out.startswith("[抓取失败]")
    assert "非 https" in out


def test_redirect_to_private_host_denied():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _redirect(
            "https://169.254.169.254/latest/meta-data/"
        )
        out = fetch_tool.invoke({"url": "https://example.com/news"})
    assert out.startswith("[抓取失败]")
    assert "169.254.169.254" in out


def test_redirect_chain_followed():
    client_mock = mock.MagicMock()
    client_mock.get.side_effect = [
        _redirect("https://other.example.com/final"),
        _resp(text="final page"),
    ]
    with mock.patch("app.tools.web_fetch.httpx.Client", return_value=client_mock):
        client_mock.__enter__ = mock.MagicMock(return_value=client_mock)
        client_mock.__exit__ = mock.MagicMock(return_value=False)
        out = fetch_tool.invoke({"url": "https://example.com/a"})
    assert "final page" in out


def test_redirect_loop_exceeded():
    client_mock = mock.MagicMock()
    client_mock.__enter__ = mock.MagicMock(return_value=client_mock)
    client_mock.__exit__ = mock.MagicMock(return_value=False)
    client_mock.get.side_effect = lambda url, **kw: _redirect(
        f"https://h{len(kw)}{url[-6:]}/x"
    )
    with mock.patch("app.tools.web_fetch.httpx.Client", return_value=client_mock):
        out = fetch_tool.invoke({"url": "https://example.com/loop"})
    assert out.startswith("[抓取失败]")
    assert "重定向超过" in out


def test_host_allows_rejects_non_global_literals():
    # 字面量 IP 不触发网络查询
    assert _REAL_HOST_ALLOWS("127.0.0.1") is False
    assert _REAL_HOST_ALLOWS("169.254.169.254") is False
    assert _REAL_HOST_ALLOWS("10.0.0.5") is False
    assert _REAL_HOST_ALLOWS("::1") is False
    assert _REAL_HOST_ALLOWS("93.184.216.34") is True


def test_rejects_bad_input():
    assert fetch_tool.invoke({"url": "   "}).startswith("[抓取失败]")


def test_returns_body_text():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls, mock.patch(
        "app.tools.web_fetch.trafilatura.extract", return_value="# 标题\n正文 markdown"
    ) as extract:
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(
            text="<html><body><h1>标题</h1><p>正文</p></body></html>"
        )
        out = fetch_tool.invoke({"url": "https://example.com/news"})
    extract.assert_called_once()
    assert "正文 markdown" in out
    assert "<html>" not in out


def test_html_extract_none_falls_back_to_raw():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls, mock.patch(
        "app.tools.web_fetch.trafilatura.extract", return_value=None
    ):
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(
            text="<html><body><p>raw body</p></body></html>"
        )
        out = fetch_tool.invoke({"url": "https://example.com"})
    assert "raw body" in out


def test_html_extract_exception_falls_back_to_raw():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls, mock.patch(
        "app.tools.web_fetch.trafilatura.extract", side_effect=RuntimeError("boom")
    ):
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(
            text="<html><body>fallback</body></html>"
        )
        out = fetch_tool.invoke({"url": "https://example.com"})
    assert "fallback" in out


def test_non_html_types_skip_extraction():
    for ctype, body in (
        ("application/rss+xml", "<rss>feed</rss>"),
        ("text/plain", "plain text"),
    ):
        with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls, mock.patch(
            "app.tools.web_fetch.trafilatura.extract"
        ) as extract:
            client_cls.return_value.__enter__.return_value.get.return_value = _resp(
                ctype=ctype, text=body
            )
            out = fetch_tool.invoke({"url": "https://example.com/feed"})
        extract.assert_not_called()
        assert body in out


def test_truncates_long_body():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(text="x" * 30_000)
        out = fetch_tool.invoke({"url": "https://example.com"})
    assert len(out) < 30_000
    assert "已截断" in out


def test_http_error_returns_error_string():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(status=404)
        out = fetch_tool.invoke({"url": "https://example.com/none"})
    assert out.startswith("[抓取失败]")
    assert "404" in out


def test_network_error_returns_error_string():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectTimeout("boom")
        out = fetch_tool.invoke({"url": "https://unreachable.invalid"})
    assert out.startswith("[抓取失败]")
    assert "网络错误" in out


def test_unsupported_content_type_returns_error_string():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(ctype="application/pdf")
        out = fetch_tool.invoke({"url": "https://example.com/a.pdf"})
    assert out.startswith("[抓取失败]")
    assert "content-type" in out


def test_rss_content_type_allowed():
    with mock.patch("app.tools.web_fetch.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = _resp(
            ctype="application/rss+xml", text="<rss>feed</rss>"
        )
        out = fetch_tool.invoke({"url": "https://example.com/feed.xml"})
    assert "feed" in out
