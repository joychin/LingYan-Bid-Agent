"""类型化 Artifact 端点（artifact-system-design.md §6/§7，2026-09-04 两态移除）。

- GET  /api/contracts                     平台契约目录元数据（客户端启动对账用）
- GET  /api/artifacts                     索引列表（?task_id= 任务全部 / ?conversation_id= 按来源筛选）
- GET  /api/artifacts/{aid}/meta          轻量探测（版本号，编辑器轮询用）
- GET  /api/artifacts/{aid}/content       当前内容（application/json）
- GET  /api/artifacts/{aid}/file          文件型产物原始字节（tender.volume docx）
- PUT  /api/artifacts/{aid}/content       编辑保存（content_seq 探测 + force 用户裁决覆盖）
- POST  /api/artifacts/{aid}/restore      恢复上一版（恢复点安全网）

并发策略遵循文件夹语义：发布即覆盖（覆盖前留恢复点），无编辑租约；
编辑器轮询探测外部更新，冲突由用户在客户端二选一裁决。
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .. import artifact_store, contracts, db

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ContentUpdate(BaseModel):
    content: object
    base_content_seq: int
    # 用户裁决「保留我的版本」：无条件覆盖（被顶掉的外部新内容会留恢复点）
    force: bool = False


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
        "content_type": contract.content_type if contract else "application/json",
        "updated_at": row["updated_at"],
        "content_seq": row["content_seq"],
        "restore_available": artifact_store.has_restore_point(row["artifact_id"], row),
        "source": {"thread_id": row["last_thread_id"], "run_id": row["last_run_id"]},
        # conversation_id 是 provenance（发布会话），非作用域
        "task_id": task_id,
        "conversation_id": conversation_id,
        # 工作区内绝对路径，供 Tauri reveal_in_folder 使用
        "path": str(artifact_store.content_path(row["artifact_id"], row)),
    }


@router.get("/artifacts")
async def list_artifacts(task_id: str | None = None, conversation_id: str | None = None):
    rows = db.list_artifact_index(task_id=task_id, conversation_id=conversation_id)
    arts = [_to_api(r) for r in rows if artifact_store.package_ready(r["artifact_id"], r)]
    return {"artifacts": arts}


@router.get("/artifacts/{aid}/meta")
async def get_artifact_meta(aid: str):
    """轻量探测：编辑器轮询外部更新只比版本号，不拉全量列表/全文。"""
    row = db.get_artifact_index(aid)
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    return {
        "artifact_id": aid,
        "content_seq": row["content_seq"],
    }


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


@router.get("/artifacts/{aid}/file")
async def get_artifact_file(aid: str):
    """文件型产物的原始字节（tender.volume=整本标书 docx）：包内唯一 .docx 流式下发。

    前端预览（docx-preview 渲染 Blob）与下载共用；containment 与 content 端点
    同标准（resolve 后必须仍在 workspace 内）。
    """
    row = db.get_artifact_index(aid)
    if not row:
        raise HTTPException(status_code=404, detail="产物不存在")
    files = artifact_store.package_files(aid, row)
    if not files:
        raise HTTPException(status_code=410, detail="产物包内没有文件（或路径越界）")
    # 历史污染包可能残留多个 docx（旧版清理只在覆盖路径、短路分支不清理）：
    # 优先取 content.json 登记的本体文件名，盲取字典序第一个会把旧册发给用户
    target = files[0]
    try:
        meta = json.loads(artifact_store.read_content_resolved(aid, row) or "{}")
    except ValueError:
        meta = None
    want = meta.get("filename") if isinstance(meta, dict) else None
    if isinstance(want, str) and want:
        target = next((f for f in files if f.name == want), files[0])
    contract = contracts.get_contract(f"{row['kind']}/{row['schema_id']}@{row['schema_version']}")
    media = contract.content_type if contract else "application/octet-stream"
    return FileResponse(
        target,
        media_type=media,
        filename=f"{row['display_name']}.docx",
        headers={"X-Content-Type-Options": "nosniff"},
    )


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
    if not contract.editable:
        # 交付物型契约（tender.volume）：机器元信息由发布管线维护，不接受编辑
        raise HTTPException(status_code=409, detail=f"「{row['display_name']}」是交付物，内容不可编辑")
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
        if row is None:
            raise HTTPException(status_code=404, detail="产物不存在")
        if not artifact_store.package_ready(aid, row):
            raise HTTPException(status_code=410, detail="产物包已不存在")
        if not body.force and body.base_content_seq != row["content_seq"]:
            raise HTTPException(
                status_code=409,
                detail=f"内容已被其他修改更新（当前版本号 {row['content_seq']}），请选择拉取最新或保留你的版本",
            )
        # 覆盖前一律留恢复点（2026-09-23 A4）：此前仅 force 覆盖留底——正常编辑保存
        # 从不留底，restore_available 恒 false、「恢复上一版」永不出现。滚动上限由
        # artifact_store 维持（3 个），正常编辑也不会撑爆磁盘。
        prev = artifact_store.read_content_resolved(aid, row)
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
        if not contract.editable:
            # 交付物型契约无编辑语义，恢复也无从谈起（纵深：文件型产物本就不留恢复点）
            raise HTTPException(status_code=409, detail=f"「{row['display_name']}」是交付物，不支持恢复")
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
        if not artifact_store.package_ready(aid, row):
            # 包已缺（manifest 或 current 被外部删）：不复活——否则恢复写回的
            # content.json 会把残缺包顶回列表（manifest 缺失时更是幽灵数据）
            raise HTTPException(status_code=410, detail="产物包已不存在")
        current = artifact_store.read_content_resolved(aid, row)
        if current is not None:
            artifact_store.save_restore_point(aid, row, row["content_seq"], current)  # 恢复可再撤销
        artifact_store.replace_current_content(aid, row, content_text)
        new_seq = row["content_seq"] + 1
        updated_at = _now()
        db.upsert_artifact_index({**row, "content_seq": new_seq, "updated_at": updated_at})
    return {"ok": True, "content_seq": new_seq, "updated_at": updated_at}
