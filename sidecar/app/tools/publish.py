"""LLM 面向的发布工具：把任务 _meta/staging/ 下的结构化草稿发布为产物。

授权与校验全部在 publish 管线（服务端硬约束）；本工具只做草稿读取、containment
（必须落在当前任务的 _meta/staging/ 内，防文档内容注入诱导读取敏感文件）与
移动消费（发布后草稿从暂存区移除，不留残骸）。

2026-08-31 重构语义：产物归任务；2026-09-04 两态移除——产物即单一当前版本，
发布即当前内容（重跑覆盖前自动留恢复点），无草稿/正式成果之分。
未注册契约一律收拢为通用笔记 doc.note（任务记忆不因类型未登记而中断）。
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from .. import artifact_store, contracts, publish, runctx
from ..config import workspace_dir

_DRAFT_MAX_BYTES = 10 * 1024 * 1024

NOTE_CONTRACT = contracts.get_contract("doc.note/note-md@1")


def _resolve_draft(p: str) -> Path:
    """草稿路径 containment：解析（含符号链接）后必须落在当前任务的 _meta/staging/ 内。

    相对路径按 workspace 根解析（模型给完整任务前缀路径，如 <任务目录>/_meta/staging/x.json）；
    按根找不到时回退任务 staging/ 下按文件名找（模型可能只给文件名或漏前缀）。
    """
    ctx = runctx.current_run()
    task_id = ctx.task_id if ctx else None
    if not task_id:
        raise ValueError("缺少任务上下文：草稿目录在当前任务的 _meta/staging/ 下，请在任务会话中发布")
    root = workspace_dir().resolve()
    allowed = artifact_store.staging_dir(task_id).resolve()
    cand = Path(p).expanduser()
    if not cand.is_absolute():
        cand = root / cand
    resolved = cand.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"草稿路径越界：只允许 {allowed.relative_to(root)}/ 目录，收到 {p}")
    if not resolved.is_relative_to(allowed):
        # 模型可能只给裸文件名或漏任务前缀：收拢到任务 staging/ 下按文件名找
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
def publish_artifact(contract: str, draft_path: str, display_name: str = "") -> str:
    """把当前任务 _meta/staging/ 下的 JSON 草稿发布为产物（登记后即用户可见可打开的成果）。

    使用方法：
    1. 先用文件工具把符合契约的 JSON 写到当前任务的 _meta/staging/ 目录（任务目录见任务
       上下文，如 <任务目录>/_meta/staging/toc.json）；
    2. 再调用本工具登记发布（发布后草稿被移动消费）。发布前会做契约与内容结构校验，
       失败会返回原因。

    contract 为平台契约标识，当前可用：
    - tender.directory/tender-response-docs@1  投标目录
    - doc.note/note-md@1  通用笔记（title + body_md）
    其他未注册类型一律以 doc.note 笔记形态保存（body_md 为 markdown 正文）。

    产物是任务内该契约的当前版本：同契约已有成果时本次发布覆盖旧内容
    （旧内容自动留恢复点，用户可恢复上一版）。
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
        meta = publish.publish_artifact(
            contract,
            content,
            display_name=display_name or None,
            source={
                "skill": "direct",
                "thread_id": ctx.conversation_id if ctx else None,
                "run_id": ctx.run_id if ctx else None,
            },
            task_id=ctx.task_id if ctx else None,
            conversation_id=ctx.conversation_id if ctx else None,
        )
    except Exception as e:
        # PublishError/ValidationError 之外还有落盘 OSError 等：全捕返错误字符串
        # （对齐 parse_document/assemble_tender 先例——工具异常会打崩整个 run）
        return f"[发布失败] {e}"

    # 移动消费：发布成功后草稿从暂存区移除，防「两个产物」以 JSON 残骸形态复活
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

    suffix = "，已保存为当前成果。"
    if note_fallback:
        suffix = "（未注册类型，已按通用笔记保存）" + suffix
    return f"[发布成功] {meta['display_name']}（{meta['artifact_id']}）{suffix}"
