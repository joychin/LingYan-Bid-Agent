"""产物端点（PRD §2）：列表 + 原始内容。

列表按创建时间倒序，过滤掉磁盘上已不存在的记录；所有读路径都过 containment 校验。
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from .. import artifacts, db

router = APIRouter()


_MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "other": "text/plain; charset=utf-8",
}


@router.get("/artifacts")
async def list_artifacts():
    arts = []
    for a in db.list_artifacts():
        p = artifacts.resolve_artifact_path(a["path"])
        if p is not None and p.is_file():
            arts.append(a)
    return {"artifacts": arts}


@router.get("/artifacts/{aid}/content")
async def get_artifact_content(aid: str):
    a = db.get_artifact(aid)
    if not a:
        raise HTTPException(status_code=404, detail="产物不存在")
    p = artifacts.resolve_artifact_path(a["path"])
    if p is None:
        # 脏数据/历史记录指向工作区外：拒绝读取（与工具侧 containment 同标准）
        raise HTTPException(status_code=410, detail="产物路径越界，已拒绝读取")
    if not p.exists():
        raise HTTPException(status_code=410, detail="产物文件已不存在")
    with open(p, "rb") as f:
        content = f.read()
    media = _MEDIA_TYPES.get(a["type"], _MEDIA_TYPES["other"])
    return Response(content=content, media_type=media)
