"""webview 光栅化服务的 HTTP 面(2026-09-14 批二)。

前端渲染服务与本模块的对话协议:
  GET  /api/render/pending  → 未决渲染请求 [{request_id, html}](3s 轮询,空列表
                              常态——本地回环成本可忽略)
  POST /api/render/figure   → 回执:multipart(request_id + file);file 有内容=成功
                              PNG,file 空=失败(立即降级);request_id 未知/过期/已
                              回执 → 404

不走 SSE(零契约改动、断连窗口内照常轮询——sidebar /runs/active 同先例)。鉴权
由 main.py 的全局 Bearer 中间件覆盖(同全部 /api/*)。任务无关:前端渲染任意
pending(多会话并发 run 无串扰)。
"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import render_queue

router = APIRouter()


@router.get("/render/pending")
async def render_pending() -> dict:
    return {"requests": render_queue.pending()}


@router.post("/render/figure")
async def render_figure(
    request_id: str = Form(...),
    file: UploadFile | None = File(None),
) -> dict:
    data = await file.read() if file is not None else b""
    if not render_queue.fulfill(request_id, data or None):
        raise HTTPException(status_code=404, detail="渲染请求不存在或已回执(过期即失效)")
    return {"ok": True}
