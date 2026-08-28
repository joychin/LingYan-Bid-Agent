"""baidu_ocr：token 换取/缓存、提交-轮询-下载全链（mock）、markdown/outline 构造。"""

import json
import threading

import httpx
import pytest

from app import baidu_ocr
from app import config as cfg
from app.parse import outline_with_lines


@pytest.fixture(autouse=True)
def _reset_token():
    baidu_ocr._reset_token_cache()


@pytest.fixture
def baidu_env(monkeypatch):
    monkeypatch.setenv("BAIDU_OCR_API_KEY", "test-ak")
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "test-sk")
    return baidu_env


def test_available_requires_both_keys(monkeypatch):
    monkeypatch.delenv("BAIDU_OCR_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_OCR_SECRET_KEY", raising=False)
    assert baidu_ocr.baidu_ocr_available() is False
    monkeypatch.setenv("BAIDU_OCR_API_KEY", "ak")
    assert baidu_ocr.baidu_ocr_available() is False  # 只有 AK 不算
    monkeypatch.setenv("BAIDU_OCR_SECRET_KEY", "sk")
    assert baidu_ocr.baidu_ocr_available() is True


def test_exchange_token_caches(baidu_env, monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return httpx.Response(
            200, json={"access_token": "tok-1", "expires_in": 2592000}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(baidu_ocr.httpx, "post", fake_post)
    assert baidu_ocr.exchange_access_token() == "tok-1"
    assert baidu_ocr.exchange_access_token() == "tok-1"
    assert len(calls) == 1  # 第二次走缓存

    baidu_ocr.exchange_access_token(force_refresh=True)
    assert len(calls) == 2


def test_exchange_token_error(baidu_env, monkeypatch):
    monkeypatch.setattr(
        baidu_ocr.httpx,
        "post",
        lambda url, **kw: httpx.Response(200, json={"error": "invalid_client"}, request=httpx.Request("POST", url)),
    )
    with pytest.raises(baidu_ocr.BaiduOcrUnavailable, match="invalid_client"):
        baidu_ocr.exchange_access_token()


def test_exchange_token_thread_safe_single_fetch(baidu_env, monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return httpx.Response(
            200, json={"access_token": "tok-1", "expires_in": 2592000}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(baidu_ocr.httpx, "post", fake_post)
    threads = [threading.Thread(target=baidu_ocr.exchange_access_token) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


def test_parse_via_baidu_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv("BAIDU_OCR_API_KEY", raising=False)
    monkeypatch.delenv("BAIDU_OCR_SECRET_KEY", raising=False)
    with pytest.raises(baidu_ocr.BaiduOcrUnavailable):
        baidu_ocr.parse_via_baidu(tmp_path / "x.pdf")


def test_parse_via_baidu_full_chain(baidu_env, monkeypatch, tmp_path):
    f = tmp_path / "标书.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    parse_result = {
        "pages": [
            {
                "page_num": 1,
                "text": "第一章 项目概况 全文……",
                "layouts": [
                    {"type": "header", "text": "某公司机密"},
                    {"type": "title", "text": "第一章 项目概况"},
                    {"type": "text", "text": "本项目为某某系统建设项目。"},
                    {"type": "table", "text": "| 序号 | 项目 |\n| 1 | A |"},
                ],
            },
            {
                "page_num": 2,
                "text": "第二章 技术要求 全文……",
                "layouts": [
                    {"type": "title", "text": "第二章 技术要求"},
                    {"type": "image", "text": "架构图"},
                    {"type": "footer", "text": "- 1 -"},
                    {"type": "seal", "text": "XX公司公章"},
                ],
            },
        ]
    }

    poll_calls = {"n": 0}

    def fake_post(url, data=None, params=None, **kw):
        if url == baidu_ocr._TOKEN_URL:
            return httpx.Response(
                200, json={"access_token": "tok-1", "expires_in": 2592000}, request=httpx.Request("POST", url)
            )
        assert params and params.get("access_token") == "tok-1"
        if url == baidu_ocr._SUBMIT_URL:
            assert data["file_name"] == "标书.pdf"
            return httpx.Response(
                200, json={"error_code": 0, "result": {"task_id": "T-1"}}, request=httpx.Request("POST", url)
            )
        if url == baidu_ocr._QUERY_URL:
            # 首次 pending，二次 success
            status = "success" if poll_calls["n"] > 0 else "Running"
            poll_calls["n"] += 1
            return httpx.Response(
                200,
                json={"error_code": 0, "result": {"status": status, "parse_result_url": "https://r/json"}},
                request=httpx.Request("POST", url),
            )
        raise AssertionError(url)

    monkeypatch.setattr(baidu_ocr.httpx, "post", fake_post)
    monkeypatch.setattr(baidu_ocr.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        baidu_ocr, "_download", lambda url: json.dumps(parse_result) if url.endswith("/json") else "# md"
    )

    result = baidu_ocr.parse_via_baidu(f)
    assert result.info["conversion"] == "paddleocr-vl"
    assert result.info["pages"] == 2
    assert result.info["tables"] == 1
    assert result.info["top_level"][0] == "第一章 项目概况"
    assert "云端 OCR" in result.info["warnings"][0]
    # 页锚点 + 标题 + header/footer 剔除 + 印章标注
    assert "<!-- p:1 -->" in result.md and "<!-- p:2 -->" in result.md
    assert "## 第一章 项目概况" in result.md
    assert "某公司机密" not in result.md and "- 1 -" not in result.md
    assert "[印章：XX公司公章]" in result.md
    assert "（图片：架构图）" in result.md
    # outline 行号对齐：title 行上取得到区间
    nodes = outline_with_lines(result.md)
    assert nodes and nodes[0]["标题"] == "第一章 项目概况"
    start = nodes[0]["start_line"]
    assert result.md.splitlines()[start - 1] == "## 第一章 项目概况"


def test_parse_via_baidu_failed_status(baidu_env, monkeypatch, tmp_path):
    f = tmp_path / "x.doc"
    f.write_bytes(b"doc")

    def fake_post(url, data=None, params=None, **kw):
        if url == baidu_ocr._TOKEN_URL:
            return httpx.Response(
                200, json={"access_token": "tok-1", "expires_in": 2592000}, request=httpx.Request("POST", url)
            )
        if url == baidu_ocr._SUBMIT_URL:
            return httpx.Response(
                200, json={"error_code": 0, "result": {"task_id": "T-2"}}, request=httpx.Request("POST", url)
            )
        return httpx.Response(
            200,
            json={"error_code": 0, "result": {"status": "failed", "task_error": "文件格式不支持"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(baidu_ocr.httpx, "post", fake_post)
    monkeypatch.setattr(baidu_ocr.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="文件格式不支持"):
        baidu_ocr.parse_via_baidu(f)


def test_parse_via_baidu_poll_timeout(baidu_env, monkeypatch, tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"pdf")
    monkeypatch.setattr(baidu_ocr, "_POLL_TIMEOUT", 0.05)

    def fake_post(url, data=None, params=None, **kw):
        if url == baidu_ocr._TOKEN_URL:
            return httpx.Response(
                200, json={"access_token": "tok-1", "expires_in": 2592000}, request=httpx.Request("POST", url)
            )
        if url == baidu_ocr._SUBMIT_URL:
            return httpx.Response(
                200, json={"error_code": 0, "result": {"task_id": "T-3"}}, request=httpx.Request("POST", url)
            )
        return httpx.Response(
            200, json={"error_code": 0, "result": {"status": "Running"}}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(baidu_ocr.httpx, "post", fake_post)
    monkeypatch.setattr(baidu_ocr.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="超时"):
        baidu_ocr.parse_via_baidu(f)


def test_build_markdown_fallback_to_page_text():
    raw = {"pages": [{"page_num": 1, "text": "纯文本页", "layouts": []}]}
    md = baidu_ocr._build_markdown(raw, None)
    assert "<!-- p:1 -->" in md and "纯文本页" in md


def test_cfg_baidu_getters_wire_to_env(baidu_env):
    assert cfg.baidu_ocr_api_key() == "test-ak"
    assert cfg.baidu_ocr_secret_key() == "test-sk"
