"""fetch_url：给主代理/子代理的最小联网抓取工具（调研类 skill 的数据来源）。

设计约束（artifact-system 之外的工具 plumbing，保持最小）：
- 仅 https；15s 超时；跟随重定向（httpx 默认上限）；
- text/html 用 trafilatura 抽正文转 markdown（去导航/脚注噪音，省 token）；
  抽取失败/非文章页回退原始文本，其余白名单类型（RSS/JSON 等）原样返回；
- 响应体截断 1 万字符（省 token，防超大页面）；
- 失败一律返回 "[抓取失败] …" 字符串而不抛异常（与 read_artifact 同风格）：
  实测 deepagents 0.7.7 工具异常不会被 ToolNode 拦截成 error ToolMessage，
  会把整个 run 打成 error；返回字符串让模型看到错误后自行换源/降级。
"""

import httpx
import trafilatura
from langchain_core.tools import tool

MAX_BODY_CHARS = 10_000
_TIMEOUT = httpx.Timeout(15.0)

_ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "text/xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/json",
)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) TenderAgent/0.1 (research sidecar)"


def _extract_markdown(text: str) -> str | None:
    """trafilatura 抽正文转 markdown；非文章页（返回 None）或解析异常一律回退原文。"""
    try:
        out = trafilatura.extract(text, output_format="markdown")
    except Exception:
        return None
    return out.strip() if out else None


@tool
def fetch_url(url: str) -> str:
    """抓取一个 https 网页/RSS 的文本内容（截断到 1 万字符）。

    用于联网调研（如新闻、公开资料）。只支持 https；text/html 返回抽取后的
    markdown 正文（去导航/页脚噪音），RSS/JSON 等类型原样返回。
    失败时返回以 [抓取失败] 开头的说明。
    """
    if not isinstance(url, str) or not url.strip():
        return "[抓取失败] url 必须是非空字符串"
    url = url.strip()
    if not url.startswith("https://"):
        return f"[抓取失败] 仅支持 https URL，收到：{url}"

    try:
        with httpx.Client(
            timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError as e:
        return f"[抓取失败] 网络错误：{e}（{url}）"

    if resp.status_code >= 400:
        return f"[抓取失败] HTTP {resp.status_code}（{url}）"

    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype and ctype not in _ALLOWED_CONTENT_TYPES:
        return f"[抓取失败] 不支持的 content-type：{ctype}（{url}）"

    text = resp.text
    if ctype == "text/html":
        markdown = _extract_markdown(text)
        if markdown:
            text = markdown
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + "\n…[内容过长，已截断]"
    return text
