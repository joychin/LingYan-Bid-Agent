"""发布管线（artifact-system-design.md §5）：产物（Artifact）的唯一登记入口。

校验链（全部硬约束）：
  ① contract 在平台契约目录中存在
  ② 授权：当前上下文允许发布该 contract（P4 挂点，见 _allowed_contracts）
  ③ 内容通过该 contract 的 Pydantic schema 校验
  ④ 落盘（原子写 meta.json + content.json，索引 upsert）

归属：文件归任务——task_id 必填、恒为所属任务，产物落 work/artifacts/<aid>/；
conversation_id 只作 provenance（记录发布会话），不再决定作用域。LLM 发布工具
与用户编辑入口都能写入。**单一当前版本**（2026-09-04 两态移除）：无草稿/已确认
之分，发布即当前内容；重跑覆盖前留恢复点兜底。

task-single 语义：同契约同任务内已存在 → 复用 artifact_id 与 meta（稳定身份），
仅替换当前内容、content_seq+1；task-multi → 恒新建。
"""

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone

from . import artifact_store, contracts, db, deliverables

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
    单一当前版本：发布即当前内容，覆盖前留恢复点（用户可一键恢复上一版）。
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
    # 产生重复成果；编辑保存/恢复端点写同一包时也持同一把锁。不做任何
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
            # 内容未变短路（2026-09-12）：与当前发布内容逐字节一致且显示名未变 →
            # 不重复发布（seq/emitted/last_run_id/恢复点全不动，run 收尾 pending_emit
            # 捞不到 → 无 artifact.created → 聊天产物卡不挪位）。治「模型每轮重
            # 组装目录」把单例产物卡逐轮后推。_unchanged 仅是返回值标记，不落盘。
            prev = artifact_store.read_content_resolved(aid, existing)
            if prev == content_text and name == existing["display_name"]:
                logger.info("artifact 内容未变跳过发布 %s (%s)", aid, contract_key)
                return {**(artifact_store.read_meta(aid, existing) or {}), "_unchanged": True}
            # 发布即覆盖（文件夹语义）：被覆盖的当前内容先留恢复点，用户可一键恢复上一版
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
                    "emitted": 0,
                }
            )
            logger.info("artifact 更新 %s (%s) seq=%s", aid, contract_key, existing["content_seq"] + 1)
            # 呈现信号（产出即开）：内容有变的真实更新才声明——上面的短路分支
            # （内容未变）直接 return，不会走到这里，语义与 artifact.created 一致
            deliverables.note("artifact", artifact_id=aid, display_name=name)
            return artifact_store.read_meta(aid, existing) or {}

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
                "emitted": 0,
            }
        )
        logger.info("artifact 发布 %s (%s)", aid, contract_key)
        deliverables.note("artifact", artifact_id=aid, display_name=name)
        return meta


# ---------- 文件型产物（tender.volume：docx 本体进包，content.json 只存机器元信息） ----------


def _zip_content_equal(a, b) -> bool:
    """两个 zip（docx）内容级相等：部件名集合一致 + 每部件 CRC32 一致。

    忽略 zip 时间戳——python-docx 每次保存都会写新的条目时间，逐字节比对
    永不相等；CRC 是内容寻址，同内容重合册稳定相等（lxml 序列化确定性）。
    任一文件读不了（损坏/非 zip）返回 False=走完整覆盖路径，方向保守。
    """
    import zipfile
    from pathlib import Path

    a, b = Path(a), Path(b)
    try:
        with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
            if sorted(za.namelist()) != sorted(zb.namelist()):
                return False
            crc_a = {i.filename: i.CRC for i in za.infolist()}
            crc_b = {i.filename: i.CRC for i in zb.infolist()}
            return crc_a == crc_b
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


def publish_file_artifact(
    contract_key: str,
    file_path,
    content_meta: dict,
    display_name: str | None = None,
    source: dict | None = None,
    task_id: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """发布文件型产物（当前唯一契约 tender.volume=整本标书 docx），返回 meta。

    与 publish_artifact 的差异（JSON 路径零改动，两函数并行）：
    - 包内多一个二进制本体（file_path 拷入包，包内文件名=源文件名）；
      content.json 只存机器元信息（schema 校验对象）。
    - 身份复用键 = 任务 + kind + **display_name（册名）**——契约标 task-multi
      但不走「恒新建」：同册重合册覆盖同一条（多册各一条），不碰 doc.note 的
      task-multi 语义。册改名=另立新卡、旧卡保留（内容仍可打开）。
    - 内容未变短路按 docx 内容级比对（_zip_content_equal，忽略 zip 时间戳）。
    - **不设恢复点**：整本是派生交付物、非用户编辑内容，旧版随时可由节文件
      重新合册复原（恢复点的受益者是「用户手改被覆盖」场景，这里不存在）。
    """
    from pathlib import Path

    file_path = Path(file_path)
    if not task_id and conversation_id:
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
    if not file_path.is_file():
        raise PublishError(f"文件不存在：{file_path}")

    try:
        c.model.model_validate(content_meta)
    except Exception as e:
        raise PublishError(f"元信息不符合契约 {contract_key}：{str(e).replace(chr(10), ' ')[:500]}")

    name = (display_name or "").strip() or c.default_display_name
    filename = file_path.name
    source = source or {}
    content_text = json.dumps(content_meta, ensure_ascii=False, indent=2)

    with artifact_store.write_lock:
        existing = None
        for row in db.list_artifact_index(task_id=task_id):
            if (
                row["kind"] == c.kind
                and row["schema_id"] == c.schema_id
                and row["schema_version"] == c.schema_version
                and row["display_name"] == name
                and artifact_store.read_meta(row["artifact_id"], row) is not None
            ):
                existing = row
                break

        if existing is not None:
            aid = existing["artifact_id"]
            pkg_dir = artifact_store.artifact_dir(aid, existing)
            # 崩溃残留的暂存件清掉（正常路径 finally 已清，这里是兜底）
            for stale in pkg_dir.glob("incoming-*.part"):
                stale.unlink(missing_ok=True)
            pkg_files = artifact_store.package_files(aid, existing)
            # 内容未变短路：docx 内容级相等且显示名未变 → 不重复发布（seq/emitted/
            # last_run_id 全不动，run 收尾 pending_emit 捞不到 → 无 artifact.created，
            # 聊天产物卡不挪位）——与 JSON 路径的 2026-09-12 短路同款语义
            if pkg_files and _zip_content_equal(pkg_files[0], file_path):
                logger.info("artifact 文件内容未变跳过发布 %s (%s)", aid, contract_key)
                return {
                    **(artifact_store.read_meta(aid, existing) or {}),
                    "_unchanged": True,
                    "_seq": existing.get("content_seq"),
                }
            # 新 docx 先落包内暂存名，簿记全部完成后最后一步原子换装——中途任何
            # 一步失败，包内保持完整旧态（旧 docx + 旧 content.json），下次重跑
            # 比对不等自然走完整更新路径收敛。此前「先写正式名后簿记」的顺序一旦
            # 中途失败，重跑会命中内容短路把失败半态固化（content.json/seq 永不
            # 修正、artifact.created 永不发、文案误报「未重复发布」）。
            staging = pkg_dir / f"incoming-{uuid.uuid4().hex[:8]}.part"
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(file_path.read_bytes())
            try:
                artifact_store.replace_current_content(aid, existing, content_text)
                db.upsert_artifact_index(
                    {
                        **existing,
                        # content_path 恒指包内 content.json（机器元信息）——与 JSON 发布路径及
                        # 重启 rebuild_artifact_index 的重算口径一致（该列无读者；写 docx 路径
                        # 会在重启后被静默翻回，账目漂移）。
                        "content_path": str(artifact_store.content_path(aid, existing)),
                        "content_seq": existing["content_seq"] + 1,
                        "updated_at": _now(),
                        "last_run_id": source.get("run_id"),
                        "last_thread_id": source.get("thread_id"),
                        "emitted": 0,
                    }
                )
                staging.replace(pkg_dir / filename)
                # 单文件不变量：册名清洗后文件名变了的话，摘掉包内旧 docx（file 端点
                # 按「包内唯一 .docx」取文件）
                for p in artifact_store.package_files(aid, existing):
                    if p.name != filename:
                        p.unlink(missing_ok=True)
            finally:
                staging.unlink(missing_ok=True)
            logger.info("artifact 文件更新 %s (%s) seq=%s", aid, contract_key, existing["content_seq"] + 1)
            deliverables.note("artifact", artifact_id=aid, display_name=name)
            # _seq（与索引 content_seq 同源）：docx_ops 工具结果文案用——「第 N 版」
            # 把「真发了新版本」与「内容未变未重发」两种结局摆到模型眼前，防总结混写
            return {
                **(artifact_store.read_meta(aid, existing) or {}),
                "_seq": existing["content_seq"] + 1,
            }

        aid = artifact_store.new_artifact_id()
        meta = {
            "manifest_version": 1,
            "artifact_id": aid,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "display_name": name,
            "kind": c.kind,
            "schema": {"id": c.schema_id, "version": c.schema_version},
            "content_type": c.content_type,
            "cardinality": c.cardinality,
            "source": {
                "skill": source.get("skill", ""),
                "thread_id": source.get("thread_id"),
                "run_id": source.get("run_id"),
            },
            "created_at": _now(),
        }
        # 先文件后 content.json 再 meta.json（meta 落盘即发布完成，与 create_package 同序）；
        # 中途失败清掉刚开的半包目录——无 meta 的目录读侧本就当不存在（僵尸行防御），
        # 不清只会留磁盘孤儿
        try:
            artifact_store.write_package_file(aid, meta, filename, file_path.read_bytes())
            artifact_store.create_package(meta, content_text)
        except Exception:
            shutil.rmtree(artifact_store.artifact_dir(aid, meta), ignore_errors=True)
            raise
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
                # 同上：content_path 恒指 content.json（docx 本体经 /file 端点按包内唯一 .docx 取）
                "content_path": str(artifact_store.content_path(aid, meta)),
                "content_seq": 1,
                "updated_at": meta["created_at"],
                "last_run_id": source.get("run_id"),
                "last_thread_id": source.get("thread_id"),
                "emitted": 0,
            }
        )
        logger.info("artifact 文件发布 %s (%s)", aid, contract_key)
        deliverables.note("artifact", artifact_id=aid, display_name=name)
        return {**meta, "_seq": 1}
