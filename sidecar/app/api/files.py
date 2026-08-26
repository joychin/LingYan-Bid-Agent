"""任务文件区 API（PRD §2 / artifact-system-design.md §16）：上传 / 列表 / 删除。

文件落在当前任务的 files/ 子目录（workspace/<task_id>/files/，§16 任务分组布局）——
跨任务同名文件互不影响；task_id 必填（无任务上下文的前端禁止上传）。
扩展名白名单 + 100MB 上限 + 任务内同名覆盖。
解析支持 .docx/.pdf（parse_document）；.txt/.md 仅作参考文件上传，不参与解析。
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import artifact_store, db
from ..config import workspace_dir

router = APIRouter()

ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
MAX_SIZE_BYTES = 100 * 1024 * 1024
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
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext or '(无扩展名)'}（允许 .docx/.pdf/.txt/.md；.doc 请用 Word 另存为 .docx）",
        )

    # 先写临时文件，成功后再 os.replace 原子覆盖：中途失败（413/断连/IO 错）不破坏磁盘上已存在的同名旧文件
    target_dir = artifact_store.task_files_dir(task_id)
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
                if size > MAX_SIZE_BYTES:
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
    files_dir = artifact_store.task_files_dir(task_id)
    files = []
    if files_dir.is_dir():
        for p in sorted(files_dir.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                files.append(
                    {
                        "name": p.name,
                        "size": st.st_size,
                        "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                    }
                )
    return {"files": files}


@router.delete("/files/{name}")
async def delete_file(name: str, task_id: str):
    _require_task(task_id)
    clean = _clean_name(name)
    if clean is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    files_dir = artifact_store.task_files_dir(task_id).resolve()
    target = (files_dir / clean).resolve()
    if not target.is_relative_to(files_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    target.unlink()
    return {"ok": True}
