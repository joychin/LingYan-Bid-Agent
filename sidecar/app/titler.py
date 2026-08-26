"""会话自动命名：首条用户消息后用一次独立轻量 LLM 调用生成标题。

不走主 agent（不污染会话记忆/checkpoint、不占 run 状态）；仅当标题仍是默认
「新对话」时经 db.set_title_if_default 原子写入（用户手动改名后不覆盖），
成功后发 conversation.renamed（无 seq，连接级推送，同 run.state）。
"""

import asyncio
import logging

from langchain_deepseek import ChatDeepSeek

from . import config as cfg
from . import db
from .bus import publish
from .events import EVENT_CONVERSATION_RENAMED

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "新对话"
MAX_INPUT_CHARS = 500
MAX_TITLE_LEN = 30

_TITLE_PROMPT = (
    "为下面这条用户消息所在的对话起一个简短的中文标题（6~16 个字），"
    "概括用户的意图或主题。只输出标题本身，不要引号、序号或任何解释。\n\n"
    "用户消息：\n{excerpt}"
)


async def maybe_generate_title(cid: str, user_text: str) -> None:
    """fire-and-forget：无 key/已改名/LLM 失败一律静默返回（标题保持默认，
    用户可手动改名兜底）。"""
    api_key = cfg.llm_api_key()
    if not api_key:
        return
    conv = db.get_conversation(cid)
    if not conv or conv["title"] != DEFAULT_TITLE:
        return
    try:
        title = await asyncio.to_thread(_generate, api_key, user_text)
    except Exception:
        logger.exception("会话自动命名失败：%s", cid)
        return
    if title and db.set_title_if_default(cid, title):
        await publish(
            cid,
            {"event": EVENT_CONVERSATION_RENAMED, "data": {"conversation_id": cid, "title": title}},
        )


def _generate(api_key: str, user_text: str) -> str | None:
    model = ChatDeepSeek(
        api_key=api_key,
        base_url=cfg.llm_base_url(),
        model=cfg.llm_model(),
        timeout=15,
    )
    excerpt = (user_text or "").strip()[:MAX_INPUT_CHARS]
    resp = model.invoke([("user", _TITLE_PROMPT.format(excerpt=excerpt))])
    return _clean(getattr(resp, "content", ""))


def _clean(raw) -> str | None:
    """LLM 输出清洗：剥引号与「标题：」前缀、压掉换行、限长。"""
    if isinstance(raw, list):  # 内容块列表（与 events._chunk_text 同款兼容）
        raw = "".join(
            b.get("text", "") or "" for b in raw if isinstance(b, dict) and b.get("type") == "text"
        )
    t = (raw if isinstance(raw, str) else "").strip()
    t = t.strip("\"“”「」『』").strip()
    for prefix in ("标题：", "标题:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    t = " ".join(t.split())
    return t[:MAX_TITLE_LEN] or None
