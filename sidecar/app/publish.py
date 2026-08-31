"""发布管线（artifact-system-design.md §5）：产物（Artifact）的唯一登记入口。

校验链（全部硬约束）：
  ① contract 在平台契约目录中存在
  ② 授权：当前上下文允许发布该 contract（P4 挂点，见 _allowed_contracts）
  ③ 内容通过该 contract 的 Pydantic schema 校验
  ④ 落盘（原子写 meta.json + content.json，索引 upsert）

归属（2026-08-31 重构定稿）：文件归任务——task_id 必填、恒为所属任务，产物落
work/artifacts/<aid>/；conversation_id 只作 provenance（记录发布会话），不再决定
作用域。LLM 发布工具与用户编辑入口都能写入，但**每次发布产出的都是草稿
（state=draft）**；已确认产物被重新发布（AI 重跑覆盖）时自动降级回草稿，
用户须重新确认（信任边界）。

task-single 语义：同契约同任务内已存在 → 复用 artifact_id 与 meta（稳定身份），
仅替换当前内容、content_seq+1、state 降回 draft；task-multi → 恒新建。
"""

import json
import logging
from datetime import datetime, timezone

from . import artifact_store, contracts, db

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """发布被拒（信息直接返回给工具/LLM，中文可读）。"""


def _allowed_contracts(source: dict | None) -> set[str]:
    """授权集合。

    P4 挂点：任务模板落地后改为 task → template → 契约集合的服务端事实校验。
    当前模板实体未引入（单场景），stub 为「允许全部已注册契约」——
    契约存在性 + schema 校验仍然不可绕过。
    """
    return {c.key for c in contracts.list_contracts()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def publish_artifact(
    contract_key: str,
    content: object,
    display_name: str | None = None,
    source: dict | None = None,
    task_id: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """发布（或按 task-single 语义更新）一个产物，返回 meta。

    source: {"skill": str, "thread_id": str, "run_id": str}，记录发布来源。
    conversation_id: provenance（发布会话），非作用域——只给 conversation_id 时反查任务。
    每次发布产出 state=draft；覆盖已确认产物自动降级回草稿（用户须重新确认）。
    """
    if not task_id and conversation_id:
        # 兼容旧调用路径（只传 conversation_id）：反查所属任务
        conv = db.get_conversation(conversation_id)
        task_id = (conv or {}).get("task_id")
    if not task_id:
        raise PublishError("发布必须指定所属任务（task_id）")
    if db.get_task(task_id) is None:
        raise PublishError(f"任务 {task_id} 不存在")

    c = contracts.get_contract(contract_key)
    if c is None:
        raise PublishError(
            f"未注册的 Artifact 契约「{contract_key}」，可用：{', '.join(sorted(contracts.CONTRACTS))}"
        )
    if contract_key not in _allowed_contracts(source):
        raise PublishError(f"当前上下文无权发布契约「{contract_key}」")

    try:
        c.model.model_validate(content)
    except Exception as e:  # pydantic ValidationError
        msg = str(e).replace("\n", " ")
        raise PublishError(f"内容不符合契约 {contract_key}：{msg[:500]}")

    name = (display_name or "").strip() or c.default_display_name
    source = source or {}
    content_text = json.dumps(content, ensure_ascii=False, indent=2)

    # 写锁（不可见 plumbing，宿主在 artifact_store）：串行化发布落盘，防并发首建
    # 产生重复成果；编辑保存/恢复/确认端点写同一包时也持同一把锁。不做任何
    # 用户可见的互斥——覆盖策略遵循文件夹语义。
    with artifact_store.write_lock:
        existing = None
        if c.cardinality == "task-single":
            found = db.find_artifact_index(
                c.kind, c.schema_id, c.schema_version, task_id=task_id
            )
            # 索引行在但包已删（僵尸行，如任务目录被手工清理且未重启重建）：
            # 视为不存在走新建，避免把内容写进无 meta 的目录。
            if found is not None and artifact_store.read_meta(found["artifact_id"], found) is not None:
                existing = found

        if existing is not None:
            aid = existing["artifact_id"]
            # 发布即覆盖（文件夹语义）：被覆盖的当前内容先留恢复点，用户可一键恢复上一版
            prev = artifact_store.read_content_resolved(aid, existing)
            if prev is not None:
                artifact_store.save_restore_point(aid, existing, existing["content_seq"], prev)
            # 覆盖已确认产物 → 降级回草稿（信任边界承重点：用户须重新确认）。
            # **先降级 meta 再写内容**（2026-08-31 review 修复顺序）：两步之间崩溃时
            # fail-safe=「草稿+旧内容」；反过来会留下「已确认戳+用户没看过的 AI 新内容」，
            # 重启后索引重建以 meta 为准，确认戳会盖到未经审阅的内容上
            meta = artifact_store.read_meta(aid, existing) or {}
            meta["state"] = "draft"
            meta["confirmed_at"] = None
            artifact_store.write_meta(meta)
            artifact_store.replace_current_content(aid, existing, content_text)
            db.upsert_artifact_index(
                {
                    **existing,
                    "content_seq": existing["content_seq"] + 1,
                    "updated_at": _now(),
                    "last_run_id": source.get("run_id"),
                    "last_thread_id": source.get("thread_id"),
                    "state": "draft",
                    "emitted": 0,
                }
            )
            logger.info("artifact 更新 %s (%s) seq=%s", aid, contract_key, existing["content_seq"] + 1)
            return meta

        aid = artifact_store.new_artifact_id()
        meta = {
            "manifest_version": 1,
            "artifact_id": aid,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "display_name": name,
            "kind": c.kind,
            "schema": {"id": c.schema_id, "version": c.schema_version},
            "content_type": "application/json",
            "cardinality": c.cardinality,
            "source": {
                "skill": source.get("skill", ""),
                "thread_id": source.get("thread_id"),
                "run_id": source.get("run_id"),
            },
            "created_at": _now(),
            "state": "draft",
            "confirmed_at": None,
        }
        artifact_store.create_package(meta, content_text)
        db.upsert_artifact_index(
            {
                "artifact_id": aid,
                "task_id": task_id,
                "conversation_id": conversation_id,
                "kind": c.kind,
                "schema_id": c.schema_id,
                "schema_version": c.schema_version,
                "cardinality": c.cardinality,
                "display_name": name,
                "content_path": str(artifact_store.content_path(aid, meta)),
                "content_seq": 1,
                "updated_at": meta["created_at"],
                "last_run_id": source.get("run_id"),
                "last_thread_id": source.get("thread_id"),
                "state": "draft",
                "emitted": 0,
            }
        )
        logger.info("artifact 发布 %s (%s)", aid, contract_key)
        return meta
