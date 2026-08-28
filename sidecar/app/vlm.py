"""视觉模型客户端：OpenAI-compatible chat.completions + image_url。

2026-08-29 起不再独立配置——视觉能力来自模型 profile：resolve_vision() 取
「default 若支持图片，否则第一个 image_support 的 profile」，其 API Key 走
MODEL_KEYS（default 回退 LLM_API_KEY）。无可用视觉 profile 即未配置
（vlm_available()=False），知识库图片/扫描件走降级链（收原件+登记资产+人工
填表，不阻塞上传）。
- 同步实现（agent worker 线程之外的后台任务用 asyncio.to_thread 包裹，titler 先例）。
- provider 无关：qwen-vl（DashScope compatible-mode）/ glm-4v / gpt-4o 等均走 OpenAI 兼容端点。
"""

import base64
import mimetypes
from pathlib import Path

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from . import config as cfg


class VlmUnavailable(Exception):
    """无可用视觉模型 profile。调用方捕获后走降级链，不当错误展示。"""


# 瞬时错误（连接/超时/5xx/429）在客户端内两连试（1s 间隔）；其余（鉴权/参数/配额）原样抛。
# agent.py 的主 LLM 流式断点重试是另一套定制语义（checkpoint 续跑），互不相干。
_TRANSIENT_ERRORS = (APIConnectionError, InternalServerError, RateLimitError)


def vlm_available() -> bool:
    p = cfg.resolve_vision()
    return bool(p and p.base_url and p.model and cfg.model_key(p.id))


def _client():
    p = cfg.resolve_vision()
    return OpenAI(
        api_key=cfg.model_key(p.id),
        base_url=p.base_url,
        timeout=120.0,
        max_retries=0,
    )


@retry(
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=True,
)
def vlm_read_image(image_path: Path, prompt: str) -> str:
    """读图返回纯文本回复（同步；调用方 asyncio.to_thread 包裹）。

    未配置时抛 VlmUnavailable；瞬时网络/API 错误在此两连试，仍失败原样抛由调用方降级。
    """
    if not vlm_available():
        raise VlmUnavailable("未配置支持图片输入的模型")
    p = cfg.resolve_vision()
    data = base64.b64encode(Path(image_path).read_bytes()).decode()
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    resp = _client().chat.completions.create(
        model=p.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()
