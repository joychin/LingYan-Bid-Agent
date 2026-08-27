"""LLM 面向的发布工具：把任务 drafts/ 下的结构化草稿发布为会话「过程稿」Artifact。

授权与校验全部在 publish 管线（服务端硬约束）；本工具只做草稿读取与
containment（必须落在当前任务的 drafts/ 内，防文档内容注入诱导读取敏感文件）。

P4 语义：LLM 只能写会话过程稿（正式稿的每次写入都由用户点头——转正走
用户点击）；propose_promotion 只是把「建议转正」标记挂到过程稿上，等用户确认。
未注册契约一律收拢为通用笔记 doc.note（任务记忆不因类型未登记而中断）。
"""

import json
from pathlib import Path

from langchain_core.tools import tool
from pydantic import ValidationError

from .. import artifact_store, contracts, publish, runctx
from ..config import workspace_dir

_DRAFT_MAX_BYTES = 10 * 1024 * 1024

NOTE_CONTRACT = contracts.get_contract("doc.note/note-md@1")


def _resolve_draft(p: str) -> Path:
    """草稿路径 containment：解析（含符号链接）后必须落在当前任务的 drafts/ 内。

    相对路径按 workspace 根解析（模型给完整任务前缀路径，如 <任务目录>/drafts/x.json）；
    按根找不到时回退任务 drafts/ 下按文件名找（模型可能只给 drafts/x.json 或 x.json）。
    """
    ctx = runctx.current_run()
    task_id = ctx.task_id if ctx else None
    if not task_id:
        raise ValueError("缺少任务上下文：草稿目录在当前任务的 drafts/ 下，请在任务会话中发布")
    root = workspace_dir().resolve()
    allowed = artifact_store.task_drafts_dir(task_id).resolve()
    cand = Path(p).expanduser()
    if not cand.is_absolute():
        cand = root / cand
    resolved = cand.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"草稿路径越界：只允许 {allowed.relative_to(root)}/ 目录，收到 {p}")
    if not resolved.is_relative_to(allowed):
        # 模型可能只给裸文件名或漏任务前缀：收拢到任务 drafts/ 下按文件名找
        alt = (allowed / Path(p).name).resolve()
        if not alt.is_relative_to(allowed):
            raise ValueError(f"草稿路径越界：只允许 {allowed.relative_to(root)}/ 目录，收到 {p}")
        resolved = alt
    return resolved


def _as_note_content(content: object, display_name: str | None) -> object:
    """把未注册契约的草稿内容收拢为笔记文档形态（title + markdown 正文）。"""
    if isinstance(content, str):
        return {"title": display_name or "笔记", "body_md": content}
    if isinstance(content, dict) and isinstance(content.get("body_md"), str):
        out = {"body_md": content["body_md"]}
        title = content.get("title") or display_name
        if title:
            out["title"] = str(title)
        return out
    raise ValueError(
        "未注册契约的内容必须以通用笔记形态保存：JSON 对象含 body_md（markdown 正文）"
        "与可选 title，或直接写纯文本草稿"
    )


@tool
def publish_artifact(
    contract: str, draft_path: str, display_name: str = "", propose_promotion: bool = False
) -> str:
    """把当前任务 drafts/ 下的 JSON 草稿发布为 Artifact（保存到当前会话的过程稿，用户可见可打开）。

    使用方法：
    1. 先用文件工具把符合契约的 JSON 写到当前任务的 drafts/ 目录（任务目录见任务上下文，
       如 <任务目录>/drafts/toc.json）；
    2. 再调用本工具登记发布。发布前会做契约与内容结构校验，失败会返回原因。

    contract 为平台契约标识，当前可用：
    - tender.directory/tender-response-docs@1  投标目录
    - doc.note/note-md@1  通用笔记（title + body_md）
    其他未注册类型一律以 doc.note 笔记形态保存（body_md 为 markdown 正文）。

    propose_promotion=True 表示建议把该成果转正到任务正式稿（用户确认后才生效）；
    标准交付物（如投标目录）完成后应置 True。
    """
    try:
        path = _resolve_draft(draft_path)
    except ValueError as e:
        return f"[发布失败] {e}"
    if not path.is_file():
        return f"[发布失败] 草稿不存在：{draft_path}"
    try:
        size = path.stat().st_size
    except OSError as e:  # 磁盘异常不能逃逸：工具抛异常会打崩整个 run（仓内铁则）
        return f"[发布失败] 草稿读取失败：{e}"
    if size > _DRAFT_MAX_BYTES:
        return "[发布失败] 草稿超过 10MB 上限"

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return f"[发布失败] 草稿不是合法 JSON：{e}"
    except OSError as e:
        return f"[发布失败] 草稿读取失败：{e}"

    # 未注册契约收拢为通用笔记（类型系统封闭：LLM 不能发明新类型，笔记兜底不中断记忆）
    note_fallback = False
    if contracts.get_contract(contract) is None:
        try:
            content = _as_note_content(content, display_name or None)
        except ValueError as e:
            return f"[发布失败] {e}"
        contract = NOTE_CONTRACT.key
        note_fallback = True

    ctx = runctx.current_run()
    try:
        manifest = publish.publish_artifact(
            contract,
            content,
            display_name=display_name or None,
            source={
                "skill": "direct",
                "thread_id": ctx.conversation_id if ctx else None,
                "run_id": ctx.run_id if ctx else None,
            },
            conversation_id=ctx.conversation_id if ctx else None,
            propose_promotion=propose_promotion,
        )
    except Exception as e:
        # PublishError/ValidationError 之外还有落盘 OSError 等：全捕返错误字符串
        # （对齐 parse_document/assemble_tender 先例——工具异常会打崩整个 run）
        return f"[发布失败] {e}"

    suffix = "，已标记「建议转正」（等待用户在界面确认）" if propose_promotion else "，已保存为当前版本。"
    if note_fallback:
        suffix = "（未注册类型，已按通用笔记保存）" + suffix
    return f"[发布成功] {manifest['display_name']}（{manifest['artifact_id']}）{suffix}"
