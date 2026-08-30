"""百度智能云 PaddleOCR-VL 文档解析客户端（扫描 PDF / .doc / 图片的云端解析）。

平移自老系统 document_helpler（baidu_token.py + paddleocr_vl_service.py），协议不变：
异步任务模式 = 换 access_token → base64 提交文件得 task_id → 轮询至 success →
下载 parse_result JSON（pages[].layouts 版面分类）→ 自拼 markdown。

配置：BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY（env-only，Tauri 钥匙串 spawn 注入）；
未配置抛 BaiduOcrUnavailable，调用方走降级链（不阻塞上传、不当错误展示）。
服务为文档级解析（无逐页接口）：混合 PDF 也整本提交，调用方自行决定路由时机。
服务限制：PDF ≤500 页、版式文档 ≤100M、图片 <10M（超限按解析失败返回文案）。
"""

from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from . import config as cfg
from . import parse
from .parse import image as parse_image

_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_SUBMIT_URL = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task"
_QUERY_URL = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task/query"
_POLL_INTERVAL = 5.0  # 秒
_POLL_TIMEOUT = 300.0  # 秒
# 提前刷新缓冲，避免 token 在使用中刚好过期
_TOKEN_REFRESH_BUFFER = 300.0

# 服务端限制的本地前置检查（提前拒绝，省掉整包 base64 的内存与上传等待）：
# 版式文档 ≤100M、图片 <10M（模块 docstring）
_MAX_DOC_SUBMIT_BYTES = 100 * 1024 * 1024
_MAX_IMAGE_SUBMIT_BYTES = 10 * 1024 * 1024
# 下载结果硬上限：无上限的 resp.text 会把异常/超大响应整体读进内存
_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

_LAYOUT_SKIP = {"header", "footer"}


class BaiduOcrUnavailable(RuntimeError):
    """未配置或服务不可用；调用方捕获后走降级链（同 VlmUnavailable 先例）。"""


def baidu_ocr_available() -> bool:
    return bool(cfg.baidu_ocr_api_key() and cfg.baidu_ocr_secret_key())


# ===== access_token 管理（模块级缓存 + 线程锁；平移自老系统 BaiduTokenManager） =====

_token_lock = threading.Lock()
_cached_token: str | None = None
_token_expires_at = 0.0


def _reset_token_cache() -> None:
    """测试用：清空 token 缓存。"""
    global _cached_token, _token_expires_at
    _cached_token = None
    _token_expires_at = 0.0


def exchange_access_token(force_refresh: bool = False) -> str:
    """用 AK/SK 换 access_token（OAuth2 client_credentials），带缓存与提前刷新。

    线程安全：并发首调只发一次 HTTP。失败抛 BaiduOcrUnavailable（测试端点直接透给用户）。
    """
    global _cached_token, _token_expires_at
    if not force_refresh:
        if _cached_token and time.time() < _token_expires_at:
            return _cached_token
    with _token_lock:
        if not force_refresh:
            if _cached_token and time.time() < _token_expires_at:
                return _cached_token
        api_key = cfg.baidu_ocr_api_key()
        secret_key = cfg.baidu_ocr_secret_key()
        if not (api_key and secret_key):
            raise BaiduOcrUnavailable("BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY 未配置")
        try:
            resp = httpx.post(
                _TOKEN_URL,
                params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
                timeout=15.0,
            )
            result = resp.json()
        except Exception as e:
            raise BaiduOcrUnavailable(f"获取 access_token 失败：{e}") from e
        if "error" in result:
            raise BaiduOcrUnavailable(
                f"获取 access_token 失败：{result.get('error')} - {result.get('error_description', '')}"
            )
        token = result.get("access_token")
        if not token:
            raise BaiduOcrUnavailable("百度云返回的 access_token 为空")
        expires_in = float(result.get("expires_in", 2592000))
        _cached_token = str(token)
        _token_expires_at = time.time() + expires_in - _TOKEN_REFRESH_BUFFER
        return _cached_token


@retry(
    retry=retry_if_exception_type((httpx.TransportError,)),
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    reraise=True,
)
def _post_form(url: str, data: dict, params: dict | None = None) -> dict:
    resp = httpx.post(url, data=data, params=params, timeout=60.0)
    return resp.json()


def _download(url: str) -> str:
    """流式下载并硬性大小上限（超出抛 RuntimeError 走「解析失败」路径）。"""
    with httpx.stream("GET", url, timeout=60.0) as resp:
        resp.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise RuntimeError(
                    f"解析结果超出大小上限（{_MAX_DOWNLOAD_BYTES // (1024 * 1024)}MB）"
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
    enc = resp.charset_encoding or "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:  # 响应头声明了未知编码名
        return raw.decode("utf-8", errors="replace")


# ===== 文档解析（提交 → 轮询 → 下载 → 拼 markdown） =====

def _submit(path: Path, access_token: str) -> str:
    # 服务端限制的本地前置检查：超限整包读入+base64（峰值 ≈ 文件大小 ×2.3）
    # 既浪费内存也必然被服务端拒绝，提前给可读文案
    limit = (
        _MAX_IMAGE_SUBMIT_BYTES
        if path.suffix.lower() in parse_image.IMAGE_EXTS
        else _MAX_DOC_SUBMIT_BYTES
    )
    size = path.stat().st_size
    if size >= limit:
        raise RuntimeError(
            f"文件超出云端解析大小限制（约 {size // (1024 * 1024)}MB，上限 "
            f"{limit // (1024 * 1024)}MB）：图片请压缩后重试，大文档建议拆分"
        )
    file_data = base64.b64encode(path.read_bytes()).decode("ascii")
    result = _post_form(
        _SUBMIT_URL,
        data={"file_data": file_data, "file_name": path.name},
        params={"access_token": access_token},
    )
    if result.get("error_code", 0) != 0:
        raise RuntimeError(f"提交解析任务失败：code={result.get('error_code')}, msg={result.get('error_msg')}")
    task_id = (result.get("result") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("提交解析任务未返回 task_id")
    return str(task_id)


def _poll(task_id: str, access_token: str) -> dict:
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        result = _post_form(_QUERY_URL, data={"task_id": task_id}, params={"access_token": access_token})
        if result.get("error_code", 0) != 0:
            raise RuntimeError(f"查询解析任务失败：code={result.get('error_code')}, msg={result.get('error_msg')}")
        task_result = result.get("result") or {}
        status = task_result.get("status", "")
        if status == "success":
            return task_result
        if status == "failed":
            raise RuntimeError(f"解析失败：{task_result.get('task_error') or '未知错误'}")
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError(f"解析超时（{_POLL_TIMEOUT:.0f}s），task_id={task_id}")


def _md_line_for_layout(layout_type: str, text: str) -> str | None:
    """版面块 → markdown 行；header/footer 返回 None 剔除。"""
    text = (text or "").strip()
    if not text:
        return "（图片）" if layout_type in ("image", "figure") else None
    if layout_type == "title":
        return f"## {text}"
    if layout_type in ("image", "figure"):
        return f"（图片：{text}）"
    if layout_type in ("seal", "stamp"):
        return f"[印章：{text}]"
    if layout_type == "formula":
        return f"$${text}$$"
    # text / paragraph / table / list / code 等一律原样（表格文本云侧已为 markdown）
    return text


def _build_markdown(raw: dict, markdown_url: str | None) -> str:
    """pages[].layouts → 带页码锚点的 markdown；无 layouts 时回退云侧 markdown/页文本。"""
    pages = raw.get("pages") or []
    if not pages:
        if markdown_url:
            return _download(markdown_url)
        return ""
    parts: list[str] = []
    for page in pages:
        pno = int(page.get("page_num") or (len(parts) + 1))
        parts.append(f"<!-- p:{pno} -->")
        emitted = 0
        for layout in page.get("layouts") or []:
            ltype = str(layout.get("type") or "text").lower()
            if ltype in _LAYOUT_SKIP:
                continue
            line = _md_line_for_layout(ltype, str(layout.get("text") or ""))
            if line:
                parts.append(line)
                emitted += 1
        # 版面为空但页有整体文本时保底
        if not emitted and page.get("text"):
            parts.append(str(page["text"]).strip())
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def parse_via_baidu(path: Path) -> parse.ParseResult:
    """整本文件走百度云 PaddleOCR-VL 解析 → ParseResult（md + info）。

    outline 由拼好的 markdown 直接生成（title 块已是 ATX 标题，行号天然对齐）；
    OCR 标题非作者声明，下游出处署名按 pdf-plain 纪律（只给行号+页码）。
    """
    if not baidu_ocr_available():
        raise BaiduOcrUnavailable("文档解析未配置（设置中填写百度云 API Key / Secret Key）")
    token = exchange_access_token()
    try:
        task_id = _submit(path, token)
        task_result = _poll(task_id, token)
    except httpx.TransportError as e:
        raise RuntimeError(f"网络错误：{e}") from e

    parse_result_url = task_result.get("parse_result_url")
    markdown_url = task_result.get("markdown_url")
    if not parse_result_url:
        raise RuntimeError("百度云返回缺少 parse_result_url")
    try:
        raw = json.loads(_download(parse_result_url))
    except Exception as e:
        raise RuntimeError(f"下载解析结果失败：{e}") from e
    md = _build_markdown(raw, markdown_url)
    if not md.strip():
        raise RuntimeError("解析结果为空")

    from .parse import count_nodes, outline_with_lines

    outline = outline_with_lines(md)
    tables = sum(
        1
        for page in raw.get("pages") or []
        for layout in page.get("layouts") or []
        if str(layout.get("type") or "").lower() == "table"
    )
    top_level = [n["标题"] for n in outline[:12]] if outline else []
    return parse.ParseResult(
        md=md,
        info={
            "conversion": "paddleocr-vl",
            "pages": len(raw.get("pages") or []),
            "tables": tables,
            "headings": count_nodes(outline),
            "top_level": top_level,
            "warnings": ["内容经云端 OCR 识别，建议人工核对关键数字与条款"],
        },
    )
