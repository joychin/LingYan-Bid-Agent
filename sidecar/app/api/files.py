"""工作区文件 API（PRD §2）：上传 / 列表 / 删除。

上传只落 workspace 根目录（agent 文件后端 root），扩展名白名单 + 50MB 上限 + 同名覆盖。
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import workspace_dir

router = APIRouter()

ALLOWED_EXTENSIONS = {".docx", ".doc", ".pdf", ".txt", ".md"}
MAX_SIZE_BYTES = 50 * 1024 * 1024
_CHUNK = 1024 * 1024


def _clean_name(raw: str) -> str | None:
    """清洗文件名：去路径分隔符、拒绝空名/点开头隐藏文件（含 `..`，PRD 已知坑 #6）。"""
    name = Path(raw).name.strip()
    if not name or name.startswith("."):
        return None
    return name


@router.post("/files", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    raw = file.filename or ""
    name = _clean_name(raw)
    if name is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext or '(无扩展名)'}（允许 .docx/.doc/.pdf/.txt/.md）",
        )

    # 先写临时文件，成功后再 os.replace 原子覆盖：中途失败（413/断连/IO 错）不破坏磁盘上已存在的同名旧文件
    target = workspace_dir() / name
    existed = target.exists()
    tmp = workspace_dir() / f".{name}.{uuid.uuid4().hex[:8]}.part"
    size = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 50MB 上限")
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
async def list_files():
    ws = workspace_dir()
    files = []
    if ws.is_dir():
        for p in sorted(ws.iterdir()):
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
async def delete_file(name: str):
    clean = _clean_name(name)
    if clean is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    ws = workspace_dir().resolve()
    target = (ws / clean).resolve()
    if not target.is_relative_to(ws) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    target.unlink()
    return {"ok": True}
