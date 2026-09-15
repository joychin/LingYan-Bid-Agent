"""webview 光栅化服务的渲染请求队列(2026-09-14 表格通道批二)。

界面原型/图示的渲染引擎=应用自带的前端 webview(WKWebView/WebView2,系统组件零
打包)。sidecar 工具线程把「待渲染的 HTML」登记进本队列后阻塞等待;前端 3s 轮询
GET /api/render/pending 拉走请求,在隐藏 iframe 里渲染成 PNG,再 POST
/api/render/figure 回执唤醒等待方。

轮询而非 SSE 推送:①零 SSE 契约改动;②SSE 断连窗口内渲染照常(与 sidebar 轮询
/runs/active 同先例);③本地回环空响应成本可忽略。代价=登记后最多 3s 才被拉走,
在 75s 等待预算内无感。

队列是全任务共享的模块级单例:前端渲染任意 pending(任务无关的光栅化,多会话并发
run 无串扰)。条目自带过期(前端崩溃/应用后台挂起后不堆积),过期即失败——等待方
拿降级文案,不阻塞 run。
"""

from __future__ import annotations

import threading
import time
import uuid

# 等待与过期预算(秒):等待 75s 留在工具默认超时 120s 档内;过期比等待宽 15s,
# 让「等待方已放弃」的条目还能接住迟到的回执走清理路径(404 之外的正常分支)
WAIT_TIMEOUT_S = 75.0
_EXPIRE_S = 90.0

_LOCK = threading.Lock()
# request_id -> 条目。done 分三态:None=未决 / bytes=成功 PNG / False=失败
_PENDING: dict[str, dict] = {}


def _purge_locked(now: float) -> None:
    for rid in [r for r, e in _PENDING.items() if now - e["created_at"] > _EXPIRE_S]:
        _PENDING.pop(rid, None)


def register(task_id: str, dest_rel: str, after: str, caption: str, payload: dict) -> str:
    """登记一个渲染请求,返回 request_id。payload 分流载荷:
    {"kind": "html", "html": …}（界面原型,已过工具侧清洗）/
    {"kind": "flow", "mermaid": …}（流程图,程序从 JSON 拓扑翻译的 mermaid 文本）。"""
    rid = uuid.uuid4().hex
    with _LOCK:
        _purge_locked(time.monotonic())
        _PENDING[rid] = {
            "task_id": task_id,
            "dest_rel": dest_rel,
            "after": after,
            "caption": caption,
            "payload": payload,
            "created_at": time.monotonic(),
            "event": threading.Event(),
            "done": None,
        }
    return rid


def pending() -> list[dict]:
    """前端轮询视图:未决请求的 (request_id, …payload)。"""
    with _LOCK:
        _purge_locked(time.monotonic())
        return [
            {"request_id": rid, **e["payload"]}
            for rid, e in _PENDING.items()
            if e["done"] is None and not e["event"].is_set()
        ]


def fulfill(request_id: str, png_bytes: bytes | None) -> bool:
    """前端回执:png_bytes=成功;None=失败(立即降级,不等超时)。
    返回是否命中(未知/过期/已回执=False,端点据此 404)。"""
    with _LOCK:
        e = _PENDING.get(request_id)
        if e is None or e["event"].is_set():
            return False
        e["done"] = png_bytes if png_bytes else False
        e["event"].set()
    return True


def wait(request_id: str) -> bytes | None:
    """等待方视角:阻塞至回执/超时。返回 PNG 字节;失败或超时返回 None。
    等待结束即出列(迟到回执走 fulfill 的未命中分支)。"""
    with _LOCK:
        e = _PENDING.get(request_id)
    if e is None:
        return None
    e["event"].wait(WAIT_TIMEOUT_S)
    with _LOCK:
        _PENDING.pop(request_id, None)
    done = e["done"]
    return done if isinstance(done, bytes) else None


def entry(request_id: str) -> dict | None:
    """等待前取条目(工具线程拿 dest/after/caption 用;命中即返回副本)。"""
    with _LOCK:
        e = _PENDING.get(request_id)
        return dict(e) if e else None
