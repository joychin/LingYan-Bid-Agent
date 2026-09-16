"""fetch_url：给主代理/子代理的最小联网抓取工具（调研类 skill 的数据来源）。

设计约束（artifact-system 之外的工具 plumbing，保持最小）：
- 仅 https 且**逐跳校验**：重定向手动跟随（上限 5 跳），每一跳都重新校验
  scheme 与解析 IP（拒绝 loopback/私网/链路本地等非公网地址）——外页 302 把
  内网服务/云 metadata 内容带进对话的 SSRF 路径被逐跳挡住；
- 流式读取、字节上限 2MB：先全量读进内存再截断会让超大响应先吃满内存；
- 总时长预算 30s：每操作 15s 超时挡不住慢滴流服务器拉长总时长；
- text/html 用 trafilatura 抽正文转 markdown（去导航/脚注噪音，省 token）；
  抽取失败/非文章页回退原始文本，其余白名单类型（RSS/JSON 等）原样返回；
- 响应体截断 1 万字符（省 token）；
- 失败一律返回 "[抓取失败] …" 字符串而不抛异常（与 read_artifact 同风格）：
  实测 deepagents 0.7.7 工具异常不会被 ToolNode 拦截成 error ToolMessage，
  会把整个 run 打成 error；返回字符串让模型看到错误后自行换源/降级。
"""

import ipaddress
import socket
import time

import httpx
import trafilatura
from langchain_core.tools import tool

MAX_BODY_CHARS = 10_000
_MAX_BODY_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_TIMEOUT = httpx.Timeout(15.0)
_TOTAL_BUDGET = 30.0

_ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "text/xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/json",
)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LingYanBidAgent/0.1 (research sidecar)"


class _FetchDenied(Exception):
    """目标被安全策略/协议限制拒绝（信息返回给模型，不抛出工具异常）。"""


def _host_allows(host: str) -> bool:
    """主机解析出的全部地址都必须是公网单播：loopback/私网/链路本地（云
    metadata）/保留段一律拒绝，解析失败视为拒绝。字面量 IP 不触发网络查询。"""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return False
    return True


def _read_body(resp: httpx.Response, deadline: float) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_bytes():
        if time.monotonic() > deadline:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= _MAX_BODY_BYTES:
            break
    raw = b"".join(chunks)[:_MAX_BODY_BYTES]
    enc = resp.charset_encoding or "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:  # 响应头声明了未知编码名
        return raw.decode("utf-8", errors="replace")


def _fetch(url: str, deadline: float) -> tuple[str, str]:
    """手动逐跳抓取：每跳重新校验 scheme + 目标 IP，返回 (文本, content-type)。"""
    headers = {"User-Agent": _UA}
    with httpx.Client(timeout=_TIMEOUT) as client:
        for _hop in range(_MAX_REDIRECTS + 1):
            if time.monotonic() > deadline:
                raise _FetchDenied("抓取总时长超出预算")
            host = httpx.URL(url).host or ""
            if not _host_allows(host):
                raise _FetchDenied(f"目标地址不允许（内网/本机地址或解析失败）：{host}")
            resp = client.get(url, headers=headers, follow_redirects=False)
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    raise _FetchDenied("重定向缺少目标地址")
                nxt = resp.url.join(loc)
                if nxt.scheme != "https":
                    raise _FetchDenied(f"重定向到非 https：{nxt}")
                url = str(nxt)
                continue
            if resp.status_code >= 400:
                raise _FetchDenied(f"HTTP {resp.status_code}（{resp.url.host}）")
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ctype and ctype not in _ALLOWED_CONTENT_TYPES:
                raise _FetchDenied(f"不支持的 content-type：{ctype}（{resp.url.host}）")
            return _read_body(resp, deadline), ctype
    raise _FetchDenied(f"重定向超过 {_MAX_REDIRECTS} 次")


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

    deadline = time.monotonic() + _TOTAL_BUDGET
    try:
        text, ctype = _fetch(url, deadline)
    except _FetchDenied as e:
        return f"[抓取失败] {e}（{url}）"
    except httpx.HTTPError as e:
        return f"[抓取失败] 网络错误：{e}（{url}）"

    if ctype == "text/html":
        markdown = _extract_markdown(text)
        if markdown:
            text = markdown
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + "\n…[内容过长，已截断]"
    return text
