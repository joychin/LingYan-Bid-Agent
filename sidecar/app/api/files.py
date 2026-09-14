"""任务文件区 API（PRD §2 / artifact-system-design.md §16）：上传 / 列表 / 删除。

文件落在当前任务的 sources/ 子目录（workspace/<task_id>/sources/，2026-08-31 产物
模型重构：只读来源区）——跨任务同名文件互不影响；task_id 必填（无任务上下文的前端
禁止上传）。100MB 上限 + 任务内同名覆盖。上传不设扩展名白名单（2026-08-28 放开：
类型是否可解析由 parse_document 工具层裁决并报人话）。
"""

import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import artifact_store, db
from ..config import MAX_UPLOAD_BYTES

router = APIRouter()

_CHUNK = 1024 * 1024


def _clean_name(raw: str) -> str | None:
    """清洗文件名：去路径分隔符、拒绝空名/点开头隐藏文件（含 `..`，PRD 已知坑 #6）。"""
    name = Path(raw).name.strip()
    if not name or name.startswith("."):
        return None
    return name


def _require_task(task_id: str) -> None:
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")


@router.post("/files", status_code=201)
async def upload_file(task_id: str, file: UploadFile = File(...)):
    _require_task(task_id)
    raw = file.filename or ""
    name = _clean_name(raw)
    if name is None:
        raise HTTPException(status_code=400, detail="文件名非法")

    # 先写临时文件，成功后再 os.replace 原子覆盖：中途失败（413/断连/IO 错）不破坏磁盘上已存在的同名旧文件
    target_dir = artifact_store.sources_dir(task_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    existed = target.exists()
    tmp = target_dir / f".{name}.{uuid.uuid4().hex[:8]}.part"
    size = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 100MB 上限")
                f.write(chunk)
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return {"name": name, "size": size, "overwritten": existed}


@router.get("/files")
async def list_files(task_id: str):
    _require_task(task_id)
    files_dir = artifact_store.sources_dir(task_id)
    files = []
    if files_dir.is_dir():
        for p in sorted(files_dir.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                files.append(
                    {
                        "name": p.name,
                        # abs_path：面板右键「打开文件夹」直取（来源原件常需取去外部处理）
                        "abs_path": str(p),
                        "size": st.st_size,
                        "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
    return {"files": files}


@router.get("/files/{name}/raw")
async def read_file_raw(name: str, task_id: str):
    """来源原件原始字节：面板预览用（pdf/docx 在浏览器本地渲染，文件不出本机）。
    containment 与 delete_file 同款；不设扩展白名单——但**恒 attachment 下发**
    （前端 fetch+blob 预览不受影响；inline 会把上传的 html/svg 在浏览器模式下
    于 sidecar 同源渲染，构成存储型 XSS——kb raw 端点同先例）。"""
    _require_task(task_id)
    clean = _clean_name(name)
    if clean is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    files_dir = artifact_store.sources_dir(task_id).resolve()
    target = (files_dir / clean).resolve()
    if not target.is_relative_to(files_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(
        target,
        filename=target.name,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/files/{name}")
async def delete_file(name: str, task_id: str):
    _require_task(task_id)
    clean = _clean_name(name)
    if clean is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    files_dir = artifact_store.sources_dir(task_id).resolve()
    target = (files_dir / clean).resolve()
    if not target.is_relative_to(files_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    target.unlink()
    return {"ok": True}
