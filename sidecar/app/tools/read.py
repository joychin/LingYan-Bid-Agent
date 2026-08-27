"""按契约读取当前成果内容（后续阶段消费入口，artifact-system-design.md §9）。

P4 作用域：优先读任务「正式稿」（用户转正+手动调整后的权威当前内容），
没有正式稿时读本会话「过程稿」。用户手动调整保存后，任何会话的后续阶段都应
通过本工具按契约读取"当前内容"，而不是依赖文件路径——这是"改完的成果成为
后续 AI 输入"的闭环点。
"""

import json

from langchain_core.tools import tool

from .. import artifact_store, contracts, db, runctx


def _scope() -> tuple[str | None, str | None]:
    """当前 run 的 (task_id, conversation_id)。不在 run 中时全为 None。"""
    ctx = runctx.current_run()
    if ctx is None:
        return None, None
    conv = db.get_conversation(ctx.conversation_id) if ctx.conversation_id else None
    return (conv or {}).get("task_id"), ctx.conversation_id


def _row_by_id(aid: str, kind: str) -> dict | None:
    row = db.get_artifact_index(aid)
    if row is None or row["kind"] != kind or not artifact_store.package_ready(aid, row):
        return None
    return row


def _row_in_scope(c, task_id: str | None, conversation_id: str | None) -> dict | None:
    """按 正式稿 → 本会话过程稿 的顺序找同契约成果（§16 移除全局作用域）。"""
    lookups: list[dict] = []
    if task_id:
        lookups.append({"task_id": task_id})
    if conversation_id:
        lookups.append({"conversation_id": conversation_id})
    for kwargs in lookups:
        row = db.find_artifact_index(c.kind, c.schema_id, c.schema_version, **kwargs)
        if row is not None and artifact_store.package_ready(row["artifact_id"], row):
            return row
    return None


def _list_in_scope(kind: str, task_id: str | None, conversation_id: str | None) -> list[dict]:
    """任务正式稿 + 本会话过程稿里该 kind 的全部成果（task-multi 选择用）。"""
    rows: list[dict] = []
    if task_id:
        rows.extend(db.list_artifact_index(task_id=task_id))
    if conversation_id:
        rows.extend(db.list_artifact_index(conversation_id=conversation_id))
    seen: set[str] = set()
    out = []
    for r in rows:
        if r["kind"] == kind and r["artifact_id"] not in seen and artifact_store.package_ready(r["artifact_id"], r):
            seen.add(r["artifact_id"])
            out.append(r)
    return out


@tool
def read_artifact(contract: str, artifact_id: str = "") -> str:
    """按契约读取当前成果的完整 JSON 内容（用户调整后的最新版本）。

    后续分析/编写阶段需要引用结构化成果（如投标目录）时必须使用本工具，
    不要猜测文件路径。contract 如：tender.directory/tender-response-docs@1

    读取顺序：任务正式稿（权威当前内容）→ 本会话过程稿。任务上下文清单里
    同类成果有多份时（如多篇笔记），用 artifact_id 指定读取哪一份。
    """
    c = contracts.get_contract(contract)
    if c is None:
        keys = ", ".join(sorted(contracts.CONTRACTS))
        return f"[读取失败] 未注册的契约「{contract}」，可用：{keys}"

    task_id, conversation_id = _scope()

    if artifact_id:
        row = _row_by_id(artifact_id.strip(), c.kind)
        if row is None:
            return f"[读取失败] 「{artifact_id}」不是可读取的「{c.default_display_name}」成果"
        # 归属校验：索引行恒带 task_id（两层皆然），与本 run 所属任务比对即可
        # 覆盖两级作用域——防文档内容注入诱导模型读其他任务的成果进当前上下文
        if row.get("task_id") != task_id:
            return f"[读取失败] 「{artifact_id}」不在当前任务的可读范围内"
        where = "会话过程稿" if row.get("conversation_id") else "任务正式稿"
    elif c.cardinality != "task-single":
        # task-multi（如笔记）可能有多份：给出清单让模型用 artifact_id 选
        rows = _list_in_scope(c.kind, task_id, conversation_id)
        if not rows:
            return f"[无成果] 当前还没有「{c.default_display_name}」（{contract}）；请先运行相应流程生成。"
        row = rows[0]
        where = "会话过程稿" if row.get("conversation_id") else "任务正式稿"
        if len(rows) > 1:
            listing = "\n".join(f"- {r['artifact_id']}  {r['display_name']}" for r in rows)
            return f"[多份成果] 「{c.default_display_name}」有 {len(rows)} 份，请用 artifact_id 指定：\n{listing}"
    else:
        row = _row_in_scope(c, task_id, conversation_id)
        if row is None:
            return f"[无成果] 当前还没有「{c.default_display_name}」（{contract}）；请先运行相应流程生成。"
        where = "会话过程稿" if row.get("conversation_id") else "任务正式稿"

    raw = artifact_store.read_content(row["artifact_id"], row)
    if raw is None:
        return "[读取失败] 成果文件读取失败，请稍后重试"
    # 校验可解析（正常必然可解析；防御磁盘内容被手工破坏）
    try:
        json.loads(raw)
    except ValueError:
        return "[读取失败] 成果内容不是合法 JSON，可能已被外部破坏"
    return f"[来源：{where}]\n{raw}"
