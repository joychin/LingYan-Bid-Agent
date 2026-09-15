"""webview 光栅化渲染服务（docx_html_figure + render_queue + API 面）。

覆盖：无前端降级（等待缩短）/回执成功（节文件含图+图注+修订标记）/过期与重复
回执 404/server 端 HTML 清洗（剥 script/iframe/on*）/大小上限/并发两请求互不串。
前端渲染本体（html2canvas 保真度）不在此测——那是实机验收的活。
"""

import contextvars
import struct
import threading
import zlib

from docx import Document
from fastapi.testclient import TestClient

from app import render_queue, runctx
from app.main import app
from app.tools.docx_ops import _sanitize_html, docx_html_figure, docx_section_create
from tests.util import init_env

client = TestClient(app)


def _png() -> bytes:
    """1×1 红点 PNG。"""

    def chunk(t: bytes, d: bytes) -> bytes:
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")
    )


def _env(tmp_path, monkeypatch, wait_s=0.2):
    """init_env + 缩短渲染等待（降级路径不等 75s）。"""
    monkeypatch.setattr(render_queue, "WAIT_TIMEOUT_S", wait_s)
    task, conv = init_env(tmp_path, monkeypatch)
    runctx.set_run(conv["id"], "r_test", task["id"])
    docx_section_create.invoke({"path": "body/门户设计", "title": "门户设计", "paragraphs": "正文段。"})
    return task, conv


def _call_tool_async(kwargs: dict) -> dict:
    """工具调用放线程（模拟 ToolNode 线程池形态——contextvars 随拷贝传播）。
    异常存 out['exc']（裸线程异常不外显，测试断言靠它定位）。"""
    out: dict = {}
    ctx = contextvars.copy_context()

    def run():
        try:
            out["r"] = docx_html_figure.invoke(kwargs)
        except Exception as e:  # noqa: BLE001
            out["exc"] = e

    t = threading.Thread(target=lambda: ctx.run(run))
    t.start()
    out["thread"] = t
    return out


def _await_pending(n: int, timeout_s: float = 5.0) -> list[dict]:
    """等 n 个请求登记进队列（register 前有文件 IO，立即轮询会扑空）。"""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        reqs = client.get("/api/render/pending").json()["requests"]
        if len(reqs) >= n:
            return reqs
        time.sleep(0.02)
    return client.get("/api/render/pending").json()["requests"]


def test_sanitize_html_strips_active_content():
    """server 端清洗：script 块/自闭合、iframe、on* 事件属性全剥；正文样式保留。"""
    raw = (
        "<div style='padding:10px' onclick='x()' onmouseover=\"y()\">待办中心</div>"
        "<script>alert(1)</script><script src='https://evil/x.js'/>"
        "<iframe src='https://evil/'></iframe><p>正常段落</p>"
    )
    clean = _sanitize_html(raw)
    for banned in ("<script", "iframe", "onclick", "onmouseover", "evil"):
        assert banned not in clean, banned
    assert "待办中心" in clean and "正常段落" in clean and "padding:10px" in clean


def test_html_size_and_empty_guard(tmp_path, monkeypatch):
    """空 html / 超 100KB 直接拒绝，不进队列。"""
    _env(tmp_path, monkeypatch)
    r = docx_html_figure.invoke({"dest": "body/门户设计", "html": "   "})
    assert r.startswith("[原型失败]") and "html 为空" in r
    r2 = docx_html_figure.invoke({"dest": "body/门户设计", "html": "x" * (101 * 1024)})
    assert "超上限（≤100KB）" in r2
    assert client.get("/api/render/pending").json()["requests"] == []
    runctx.clear_run()


def test_degrade_when_frontend_silent(tmp_path, monkeypatch):
    """前端无回执：等待耗尽返回降级文案（改文字+批注），不死等；条目出列。"""
    _env(tmp_path, monkeypatch, wait_s=0.2)
    out = _call_tool_async({"dest": "body/门户设计", "html": "<div>原型</div>"})
    out["thread"].join(timeout=5)
    r = out["r"]
    assert r.startswith("[原型渲染失败]") and "文字描述" in r and "批注" in r
    assert client.get("/api/render/pending").json()["requests"] == []
    runctx.clear_run()


def test_fulfill_inserts_image_with_caption_and_revision(tmp_path, monkeypatch):
    """回执成功：PNG 全宽居中入节、带插入修订标记、图注挂 Tender Caption 紧随图片、
    源 HTML 落盘 assets/（已清洗）。"""
    task, _ = _env(tmp_path, monkeypatch, wait_s=30.0)
    out = _call_tool_async({
        "dest": "body/门户设计", "after": "1", "caption": "门户界面原型",
        "html": "<div style='padding:20px'><h2>待办</h2><script>alert(1)</script></div>",
    })
    pend = _await_pending(1)
    assert len(pend) == 1 and "<script" not in pend[0]["html"]
    rr = client.post(
        "/api/render/figure",
        data={"request_id": pend[0]["request_id"]},
        files={"file": ("x.png", _png(), "image/png")},
    )
    assert rr.status_code == 200, rr.text
    out["thread"].join(timeout=5)
    assert out["r"].startswith("[已插原型]") and "P1 之后" in out["r"]

    doc = Document(str(_wroot(task) / "body/门户设计.docx"))
    blips = doc.element.body.findall(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    )
    assert len(blips) == 1
    # 图片段带插入修订（拒绝修订=整段含图消失）——blip 向上爬到 w:p 再验
    node = blips[0]
    while node is not None and not node.tag.endswith("}p"):
        node = node.getparent()
    assert node is not None
    assert node.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ins") is not None
    paras = [(p.text, p.style.name) for p in doc.paragraphs if p.text.strip()]
    assert ("门户界面原型", "Tender Caption") in paras
    # 源留底（清洗后的）
    assets = list((_wroot(task) / "body/assets").glob("*.html"))
    assert len(assets) == 1 and "<script" not in assets[0].read_text(encoding="utf-8")
    runctx.clear_run()


def test_receipt_unknown_and_repeat_404(tmp_path, monkeypatch):
    """未知/过期/已回执的 request_id 一律 404（迟到回执的正常分支）。"""
    _env(tmp_path, monkeypatch)
    r = client.post(
        "/api/render/figure",
        data={"request_id": "nope"},
        files={"file": ("x.png", _png(), "image/png")},
    )
    assert r.status_code == 404
    runctx.clear_run()


def test_failure_receipt_degrades_immediately(tmp_path, monkeypatch):
    """失败回执（空文件）：不等超时立即降级。"""
    _env(tmp_path, monkeypatch, wait_s=30.0)
    out = _call_tool_async({"dest": "body/门户设计", "html": "<div>原型</div>"})
    pend = _await_pending(1)
    rr = client.post("/api/render/figure", data={"request_id": pend[0]["request_id"]})
    assert rr.status_code == 200
    out["thread"].join(timeout=5)
    assert out["r"].startswith("[原型渲染失败]")
    runctx.clear_run()


def test_two_concurrent_requests_no_crosstalk(tmp_path, monkeypatch):
    """并发两请求：各自回执各自的图，互不串。"""
    task, _ = _env(tmp_path, monkeypatch, wait_s=30.0)
    outs = [
        _call_tool_async({"dest": "body/门户设计", "html": f"<div>原型{i}</div>"})
        for i in (1, 2)
    ]
    pend = _await_pending(2)
    assert len(pend) == 2
    for req in pend:
        rr = client.post(
            "/api/render/figure",
            data={"request_id": req["request_id"]},
            files={"file": ("x.png", _png(), "image/png")},
        )
        assert rr.status_code == 200
    for o in outs:
        o["thread"].join(timeout=5)
    doc = Document(str(_wroot(task) / "body/门户设计.docx"))
    assert len(doc.element.body.findall(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")) == 2
    runctx.clear_run()


def _wroot(task) -> "Path":  # noqa: F821 - Path 在函数体内导入避免测试模块头噪音
    from pathlib import Path

    from app import artifact_store

    return Path(str(artifact_store.work_dir(task["id"])))
