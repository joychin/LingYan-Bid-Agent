"""按契约读取当前成果内容（后续阶段消费入口，artifact-system-design.md §9）。

2026-08-31 重构：产物归任务、单一真源（草稿/已确认两态），不再有「正式稿 → 过程稿」
两级读序——同契约在任务内唯一，读到的就是唯一当前内容（已确认或草稿）。用户手动
调整保存后，任何会话的后续阶段都应通过本工具按契约读取"当前内容"，而不是依赖文件
路径——这是"改完的成果成为后续 AI 输入"的闭环点。
"""

import json

from langchain_core.tools import tool

from .. import artifact_store, contracts, db, runctx


def _task_id() -> str | None:
    """当前 run 的 task_id。不在 run 中或会话未归属任务时为 None。"""
    ctx = runctx.current_run()
    if ctx is None:
        return None
    conv = db.get_conversation(ctx.conversation_id) if ctx.conversation_id else None
    return (conv or {}).get("task_id")


def _row_by_id(aid: str, kind: str) -> dict | None:
    row = db.get_artifact_index(aid)
    if row is None or row["kind"] != kind or not artifact_store.package_ready(aid, row):
        return None
    return row


def _list_in_task(kind: str, task_id: str | None) -> list[dict]:
    """当前任务内该 kind 的全部成果（task-multi 选择用）。"""
    if not task_id:
        return []
    rows = db.list_artifact_index(task_id=task_id)
    return [
        r for r in rows
        if r["kind"] == kind and artifact_store.package_ready(r["artifact_id"], r)
    ]


@tool
def read_artifact(contract: str, artifact_id: str = "") -> str:
    """按契约读取当前成果的完整 JSON 内容（用户调整后的最新版本）。

    后续分析/编写阶段需要引用结构化成果（如投标目录）时必须使用本工具，
    不要猜测文件路径。contract 如：tender.directory/tender-response-docs@1

    产物归任务：读到的即任务内该契约的唯一当前内容。同类成果有多份时
    （task-multi，如笔记），用 artifact_id 指定读取哪一份。
    """
    c = contracts.get_contract(contract)
    if c is None:
        keys = ", ".join(sorted(contracts.CONTRACTS))
        return f"[读取失败] 未注册的契约「{contract}」，可用：{keys}"

    task_id = _task_id()

    if artifact_id:
        row = _row_by_id(artifact_id.strip(), c.kind)
        if row is None:
            return f"[读取失败] 「{artifact_id}」不是可读取的「{c.default_display_name}」成果"
        # 归属校验：防文档内容注入诱导模型读其他任务的成果进当前上下文
        if row.get("task_id") != task_id:
            return f"[读取失败] 「{artifact_id}」不在当前任务的可读范围内"
        where = "已确认" if row.get("state") == "confirmed" else "草稿"
    elif c.cardinality != "task-single":
        # task-multi（如笔记）可能有多份：给出清单让模型用 artifact_id 选
        rows = _list_in_task(c.kind, task_id)
        if not rows:
            return f"[无成果] 当前还没有「{c.default_display_name}」（{contract}）；请先运行相应流程生成。"
        row = rows[0]
        where = "已确认" if row.get("state") == "confirmed" else "草稿"
        if len(rows) > 1:
            listing = "\n".join(f"- {r['artifact_id']}  {r['display_name']}" for r in rows)
            return f"[多份成果] 「{c.default_display_name}」有 {len(rows)} 份，请用 artifact_id 指定：\n{listing}"
    else:
        if not task_id:
            return f"[无成果] 当前还没有「{c.default_display_name}」（{contract}）；请先运行相应流程生成。"
        row = db.find_artifact_index(c.kind, c.schema_id, c.schema_version, task_id=task_id)
        if row is None or not artifact_store.package_ready(row["artifact_id"], row):
            return f"[无成果] 当前还没有「{c.default_display_name}」（{contract}）；请先运行相应流程生成。"
        where = "已确认" if row.get("state") == "confirmed" else "草稿"

    raw = artifact_store.read_content_resolved(row["artifact_id"], row)
    if raw is None:
        return "[读取失败] 成果文件读取失败，请稍后重试"
    # 校验可解析（正常必然可解析；防御磁盘内容被手工破坏）
    try:
        json.loads(raw)
    except ValueError:
        return "[读取失败] 成果内容不是合法 JSON，可能已被外部破坏"
    return f"[来源：{where}]\n{raw}"
