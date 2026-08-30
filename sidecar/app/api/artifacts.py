"""类型化 Artifact 端点（artifact-system-design.md §6/§7）。

- GET  /api/contracts                     平台契约目录元数据（客户端启动对账用）
- GET  /api/artifacts                     索引列表（?task_id= 正式稿 / ?conversation_id= 过程稿）
- GET  /api/artifacts/{aid}/content       当前内容（application/json）
- PUT  /api/artifacts/{aid}/content       编辑保存（content_seq 探测 + force 用户裁决覆盖）
- POST  /api/artifacts/{aid}/restore      恢复上一版（恢复点安全网）
- POST  /api/artifacts/{aid}/promote      过程稿转正到任务正式稿（用户点头的那一下）

并发策略遵循文件夹语义：发布即覆盖（覆盖前留恢复点），无编辑租约；
编辑器轮询探测外部更新，冲突由用户在客户端二选一裁决。
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import artifact_store, contracts, db, publish

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ContentUpdate(BaseModel):
    content: object
    base_content_seq: int
    # 用户裁决「保留我的版本」：无条件覆盖（被顶掉的外部新内容会留恢复点）
    force: bool = False


class PromoteRequest(BaseModel):
    # 用户确认转正时所见的内容版本号：不符返回 409（内容在你查看后已被更新），
    # 防「看到的是 v3、点下按钮复制走的却是 v5」。None = 旧客户端跳过校验。
    source_content_seq: int | None = None


@router.get("/contracts")
async def list_contracts():
    return {
        "contracts": [
            {
                "key": c.key,
                "kind": c.kind,
                "schema_id": c.schema_id,
                "schema_version": c.schema_version,
                "cardinality": c.cardinality,
                "llm_write_mode": c.llm_write_mode,
                "editable": c.editable,
                "default_display_name": c.default_display_name,
            }
            for c in contracts.list_contracts()
        ]
    }


def _to_api(row: dict) -> dict:
    contract = contracts.get_contract(f"{row['kind']}/{row['schema_id']}@{row['schema_version']}")
    task_id = row.get("task_id")
    conversation_id = row.get("conversation_id")
    return {
        "artifact_id": row["artifact_id"],
        "display_name": row["display_name"],
        "kind": row["kind"],
        "schema_id": row["schema_id"],
        "schema_version": row["schema_version"],
        "cardinality": row["cardinality"],
        "editable": contract.editable if contract else False,
        "content_type": "application/json",
        "updated_at": row["updated_at"],
        "content_seq": row["content_seq"],
        "restore_available": artifact_store.has_restore_point(row["artifact_id"], row),
        "source": {"thread_id": row["last_thread_id"], "run_id": row["last_run_id"]},
        # 作用域（§16）：conversation=会话过程稿；task=任务正式稿（过程稿行也带 task_id，以 conversation_id 区分）
        "scope": "conversation" if row.get("conversation_id") else "task",
        "task_id": task_id,
        "conversation_id": conversation_id,
        "promotion_proposed": bool(row.get("promotion_proposed")),
        # 工作区内绝对路径，供 Tauri reveal_in_folder 使用
        "path": str(artifact_store.content_path(row["artifact_id"], row)),
    }


@router.get("/artifacts")
async def list_artifacts(task_id: str | None = None, conversation_id: str | None = None):
    rows = db.list_artifact_index(task_id=task_id, conversation_id=conversation_id)
    arts = [_to_api(r) for r in rows if artifact_store.package_ready(r["artifact_id"], r)]
    return {"artifacts": arts}


@router.get("/artifacts/{aid}/content")
async def get_artifact_content(aid: str):
    row = db.get_artifact_index(aid)
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    p = artifact_store.resolved_content_path(aid, row)
    if p is None:
        raise HTTPException(status_code=410, detail="产物路径越界，已拒绝读取")
    if not p.is_file():
        raise HTTPException(status_code=410, detail="产物文件已不存在")
    return Response(content=p.read_bytes(), media_type="application/json; charset=utf-8")


@router.put("/artifacts/{aid}/content")
async def update_artifact_content(aid: str, body: ContentUpdate):
    """编辑保存：非 force 时 content_seq 不匹配返回 409（探测信号，客户端弹「拉取最新/保留我的」）；
    force 时无条件覆盖（被顶掉的内容留恢复点）。schema 校验始终执行。"""
    row = db.get_artifact_index(aid)
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    if not artifact_store.package_ready(aid, row):
        raise HTTPException(status_code=410, detail="产物包已不存在")
    if not body.force and body.base_content_seq != row["content_seq"]:
        raise HTTPException(
            status_code=409,
            detail=f"内容已被其他修改更新（当前版本号 {row['content_seq']}），请选择拉取最新或保留你的版本",
        )
    contract = contracts.get_contract(f"{row['kind']}/{row['schema_id']}@{row['schema_version']}")
    if contract is None:
        raise HTTPException(status_code=422, detail=f"契约 {row['kind']} 已不可用，无法保存")
    try:
        contract.model.model_validate(body.content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"内容不符合契约：{str(e).replace(chr(10), ' ')[:300]}")

    content_text = json.dumps(body.content, ensure_ascii=False, indent=2)
    # 发布工具跑在 worker 线程，与本端点真并行：与 publish 共用进程内写锁，
    # 持锁重读索引行再写——用读行时刻的陈旧整行回写会把 publish 刚置位的
    # emitted/last_run_id 抹掉，导致该次发布的 artifact.created 永不发出。
    # 作用域（task_id/conversation_id）随 manifest 固定不可变，重读行仅用于
    # 终态字段（content_seq/emitted 等）。
    with artifact_store.write_lock:
        row = db.get_artifact_index(aid)
        if row is None or not artifact_store.package_ready(aid, row):
            raise HTTPException(status_code=410, detail="产物包已不存在")
        if not body.force and body.base_content_seq != row["content_seq"]:
            raise HTTPException(
                status_code=409,
                detail=f"内容已被其他修改更新（当前版本号 {row['content_seq']}），请选择拉取最新或保留你的版本",
            )
        if body.force:
            # 顶掉的是外部写入的新版本 → 留恢复点（用户可反悔）
            prev = artifact_store.read_content(aid, row)
            if prev is not None:
                artifact_store.save_restore_point(aid, row, row["content_seq"], prev)
        artifact_store.replace_current_content(aid, row, content_text)
        new_seq = row["content_seq"] + 1
        updated_at = _now()
        db.upsert_artifact_index({**row, "content_seq": new_seq, "updated_at": updated_at})
    return {"ok": True, "content_seq": new_seq, "updated_at": updated_at}


@router.post("/artifacts/{aid}/restore")
async def restore_artifact(aid: str):
    """恢复上一版：用最近恢复点覆盖当前内容（恢复本身也留底，可再次撤销）。"""
    row = db.get_artifact_index(aid)
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    rp = artifact_store.latest_restore_point(aid, row)
    if rp is None:
        raise HTTPException(status_code=409, detail="没有可恢复的历史版本")
    try:
        content = json.loads(rp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=410, detail="恢复点内容已损坏")

    contract = contracts.get_contract(f"{row['kind']}/{row['schema_id']}@{row['schema_version']}")
    if contract is not None:
        try:
            contract.model.model_validate(content)
        except Exception:
            raise HTTPException(status_code=422, detail="恢复点内容不符合当前契约，已拒绝恢复")

    content_text = json.dumps(content, ensure_ascii=False, indent=2)
    # 与 PUT/publish 同一把写锁 + 持锁重读（见 PUT 内注释）
    with artifact_store.write_lock:
        row = db.get_artifact_index(aid)
        if row is None:
            raise HTTPException(status_code=404, detail="产物不存在")
        current = artifact_store.read_content(aid, row)
        if current is not None:
            artifact_store.save_restore_point(aid, row, row["content_seq"], current)  # 恢复可再撤销
        artifact_store.replace_current_content(aid, row, content_text)
        new_seq = row["content_seq"] + 1
        updated_at = _now()
        db.upsert_artifact_index({**row, "content_seq": new_seq, "updated_at": updated_at})
    return {"ok": True, "content_seq": new_seq, "updated_at": updated_at}


@router.post("/artifacts/{aid}/promote")
async def promote_artifact(aid: str, body: PromoteRequest = PromoteRequest()):
    """过程稿转正：复制到所属任务的正式稿（用户点头的那一下）。

    - source_content_seq 版本绑定：不符返回 409——用户确认的是他看到的那一份内容，
      不是「点击当下的 current」（同会话后续 run 可能已重新发布覆盖过程稿）
    - 过程稿原件保留（转正=复制）；task-single 正式稿已有同类 → 覆盖 + 恢复点
    - 新正式稿记 derived_from + derived_from_seq（最薄谱系）；来源过程稿清除「建议转正」标记
    - 不发 SSE（不在 run 内，seq 契约无宿主）——前端 promote 成功后自行刷新产物列表
    """
    row = db.get_artifact_index(aid)
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    if not artifact_store.package_ready(aid, row):
        raise HTTPException(status_code=410, detail="产物包已不存在")
    cid = row.get("conversation_id")
    if not cid:
        raise HTTPException(status_code=422, detail="该产物不是会话过程稿，无需转正")
    if body.source_content_seq is not None and body.source_content_seq != row["content_seq"]:
        raise HTTPException(
            status_code=409,
            detail=f"产物内容在你查看后已被更新（当前版本号 {row['content_seq']}），请查看最新版后再转正",
        )
    conv = db.get_conversation(cid)
    task_id = (conv or {}).get("task_id")
    if not task_id:
        raise HTTPException(status_code=422, detail="产物所属会话没有关联任务，无法转正")

    raw = artifact_store.read_content(aid, row)
    if raw is None:
        raise HTTPException(status_code=410, detail="产物内容读取失败")
    try:
        content = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=410, detail="产物内容已损坏（非合法 JSON）")

    contract_key = f"{row['kind']}/{row['schema_id']}@{row['schema_version']}"
    try:
        manifest = publish.publish_artifact(
            contract_key,
            content,
            display_name=row["display_name"],
            source={"skill": "promote", "thread_id": cid, "run_id": None},
            task_id=task_id,
            derived_from=aid,
            derived_from_seq=row["content_seq"],
        )
    except publish.PublishError as e:
        raise HTTPException(status_code=422, detail=str(e))

    new_aid = manifest["artifact_id"]
    db.mark_emitted(new_aid)  # 不经 run 边界事件，账本直接落已发
    if row.get("promotion_proposed"):
        db.set_promotion_proposed(aid, False)
        row = db.get_artifact_index(aid) or row
    new_row = db.get_artifact_index(new_aid)
    return {"ok": True, "artifact": _to_api(new_row) if new_row else {"artifact_id": new_aid}}
