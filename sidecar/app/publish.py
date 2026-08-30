"""发布管线（artifact-system-design.md §5）：Artifact 的唯一登记入口。

校验链（全部硬约束）：
  ① contract 在平台契约目录中存在
  ② 授权：当前上下文允许发布该 contract（P4 挂点，见 _allowed_contracts）
  ③ 内容通过该 contract 的 Pydantic schema 校验
  ④ 落盘（原子写 manifest + current，索引 upsert）

作用域（P4 任务层，§16）：task_id 非空 = 任务「正式稿」（仅 promote 端点内部使用，
LLM 工具不可直写）；conversation_id 非空 = 会话「过程稿」（LLM 发布工具唯一可写的
作用域）。两者互斥且必须恰传一个。无论哪个作用域，manifest 与索引行的 task_id
恒为所属任务（过程稿经会话反查）——包的磁盘位置据此派生（见 artifact_store）。

task-single 语义：同契约同作用域已存在 → 复用 artifact_id 与 manifest（稳定身份），
仅替换当前内容、content_seq+1；task-multi → 恒新建。
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
    propose_promotion: bool = False,
    derived_from: str | None = None,
    derived_from_seq: int | None = None,
) -> dict:
    """发布（或按 task-single 语义更新）一个 Artifact，返回 manifest。

    source: {"skill": str, "thread_id": str, "run_id": str}，记录首次发布来源。
    propose_promotion: 会话过程稿挂「建议转正」标记（正式稿每次写入都由用户
    点头——AI 只能建议，转正走 POST /artifacts/{aid}/promote）。
    derived_from: 转正复制品的来源产物 id（最薄谱系）。
    derived_from_seq: 转正时来源产物的内容版本号（与 derived_from 同批写入；
    仅首次建包落 manifest——manifest write-once，覆盖路径靠恢复点兜底）。
    """
    if task_id and conversation_id:
        raise PublishError("task_id 与 conversation_id 互斥，发布作用域只能二选一")
    if not task_id and not conversation_id:
        raise PublishError("发布必须指定作用域：任务正式稿（task_id）或会话过程稿（conversation_id）")
    if conversation_id:
        # 过程稿：经会话反查所属任务——manifest/索引的 task_id 恒为所属任务（包位置派生依据）
        conv = db.get_conversation(conversation_id)
        task_id = (conv or {}).get("task_id")
        if not task_id:
            raise PublishError(f"会话 {conversation_id} 不存在或未归属任务，无法发布过程稿")
    elif db.get_task(task_id) is None:
        raise PublishError(f"任务 {task_id} 不存在，无法发布正式稿")

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
    # 产生重复成果；编辑保存/恢复端点写同一包时也持同一把锁（事件循环线程 vs
    # worker 线程真并行）。不做任何用户可见的互斥——覆盖策略遵循文件夹语义。
    with artifact_store.write_lock:
        existing = None
        if c.cardinality == "task-single":
            found = db.find_artifact_index(
                c.kind, c.schema_id, c.schema_version,
                task_id=task_id, conversation_id=conversation_id,
            )
            # 索引行在但包已删（僵尸行，如任务目录被手工清理且未重启重建）：
            # 视为不存在走新建，避免把内容写进无 manifest 的目录。旧行被 API 的
            # package_ready() 过滤隐藏，下次启动 manifest 重建索引时自然清除。
            if found is not None and artifact_store.read_manifest(found["artifact_id"], found) is not None:
                existing = found

        if existing is not None:
            aid = existing["artifact_id"]
            # 发布即覆盖（文件夹语义）：被覆盖的当前内容先留恢复点，用户可一键恢复上一版
            prev = artifact_store.read_content(aid, existing)
            if prev is not None:
                artifact_store.save_restore_point(aid, existing, existing["content_seq"], prev)
            artifact_store.replace_current_content(aid, existing, content_text)
            db.upsert_artifact_index(
                {
                    **existing,
                    "content_seq": existing["content_seq"] + 1,
                    "updated_at": _now(),
                    "last_run_id": source.get("run_id"),
                    "last_thread_id": source.get("thread_id"),
                    # 转正建议跟随最新一次发布状态（重复布不带建议即清除）
                    "promotion_proposed": propose_promotion,
                    "emitted": 0,
                }
            )
            manifest = artifact_store.read_manifest(aid, existing)
            logger.info("artifact 更新 %s (%s) seq=%s", aid, contract_key, existing["content_seq"] + 1)
            return manifest or {"artifact_id": aid}

        aid = artifact_store.new_artifact_id()
        manifest = {
            "manifest_version": 1,
            "artifact_id": aid,
            # task_id 恒为所属任务（过程稿反查所得）；conversation_id 为空 = 正式稿
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
            "derived_from": derived_from,
            "derived_from_seq": derived_from_seq,
            "created_at": _now(),
        }
        artifact_store.create_package(manifest, content_text)
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
                "content_path": str(artifact_store.content_path(aid, manifest)),
                "content_seq": 1,
                "updated_at": manifest["created_at"],
                "last_run_id": source.get("run_id"),
                "last_thread_id": source.get("thread_id"),
                "promotion_proposed": propose_promotion,
                "emitted": 0,
            }
        )
        logger.info("artifact 发布 %s (%s)", aid, contract_key)
        return manifest
