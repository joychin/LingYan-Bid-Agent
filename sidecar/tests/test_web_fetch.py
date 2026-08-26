"""fetch_url 工具：协议限制、content-type 白名单、正文抽取回退、截断与失败路径（mock httpx，不依赖真网）。

失败约定：一律返回 "[抓取失败] …" 字符串、不抛异常（deepagents 0.7.7 工具异常会打崩整个 run）。
正文抽取：text/html 走 trafilatura.extract（mock 掉）；抽取为 None/抛异常时回退原文。
"""

from unittest import mock

import httpx

from app.tools.web_fetch import fetch_url as fetch_tool


def _resp(status=200, ctype="text/html", text="hello"):
    return httpx.Response(
        status,
        headers={"content-type": ctype},
        text=text,
        request=httpx.Request("GET", "https://example.com"),
    )


def test_rejects_non_https():
    assert fetch_tool.invoke({"url": "http://example.com"}).startswith("[抓取失败]")


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
