"""写作素材库 API（v2 手工构建）：文件上传/解析、目录树、块 CRUD。

素材块 = 用户在目录树上勾选的章节区间集合 + 备注；与知识库彻底分离
（自己的文件、自己的解析、零 LLM）。块检索段复用 kb_segments（mt_ 前缀隔离）。
"""

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import db
from ..knowledge import materials_lib as mlib

router = APIRouter()

MT_ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md", ".doc"}
MAX_SIZE_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024


def _clean_name(raw: str) -> str | None:
    name = Path(raw).name.strip()
    if not name or name.startswith("."):
        return None
    return name


def _file_out(f: dict, block_count: int | None = None) -> dict:
    out = {**f}
    if block_count is not None:
        out["block_count"] = block_count
    return out


@router.post("/materials/files", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    raw = file.filename or ""
    name = _clean_name(raw)
    if name is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    ext = Path(name).suffix.lower()
    if ext not in MT_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext or '(无扩展名)'}（素材挑章节需要文档结构，允许 .docx/.pdf/.txt/.md）",
        )

    mlib.ensure_dirs()
    tmp = mlib.mt_files_dir() / f".{name}.{uuid.uuid4().hex[:8]}.part"
    size = 0
    h = hashlib.sha256()
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 100MB 上限")
                h.update(chunk)
                f.write(chunk)
        digest = h.hexdigest()
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    existing = db.mt_get_file_by_hash(digest)
    if existing:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=409,
            detail=f"内容相同的文件已在素材库中：{existing['file_name']}",
        )

    target = mlib.unique_file_path(name)
    os.replace(tmp, target)
    f = db.mt_insert_file(file_name=target.name, file_hash=digest)
    mlib.schedule_parse(f["id"])
    return {"id": f["id"], "file_name": target.name, "size": size}


@router.get("/materials/files")
async def list_files():
    counts = db.mt_block_counts()
    return {"files": [_file_out(f, counts.get(f["id"], 0)) for f in db.mt_list_files()]}


@router.get("/materials/files/{fid}/outline")
async def get_outline(fid: str):
    """目录树（勾选界面数据源：全层级带行号；无结构时空表）。"""
    f = db.mt_get_file(fid)
    if not f:
        raise HTTPException(status_code=404, detail="素材文件不存在")
    return {"id": fid, "outline": mlib.read_outline(fid), "parse_status": f["parse_status"], "error": f.get("error")}


@router.delete("/materials/files/{fid}")
async def delete_file(fid: str):
    if not db.mt_get_file(fid):
        raise HTTPException(status_code=404, detail="素材文件不存在")
    mlib.delete_file(fid)
    return {"ok": True}


@router.get("/materials/blocks")
async def list_blocks():
    """全部素材块（跨文件；文件信息附带）。"""
    files = {f["id"]: f for f in db.mt_list_files()}
    out = []
    for b in db.mt_list_blocks():
        f = files.get(b["file_id"])
        if not f:
            continue
        out.append({**b, "file_name": f["file_name"]})
    return {"blocks": out}


@router.post("/materials/files/{fid}/blocks", status_code=201)
async def create_block(fid: str, body: dict):
    """建块：{title, note, ranges: [[s,e],…]}——ranges 来自勾选节点的行号区间
    （可勾父子节点，服务端嵌套去重叠；区间须有效）。"""
    f = db.mt_get_file(fid)
    if not f:
        raise HTTPException(status_code=404, detail="素材文件不存在")
    if f["parse_status"] != "ready":
        raise HTTPException(status_code=422, detail="文件尚未解析完成，稍候再试")
    ranges = body.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        raise HTTPException(status_code=422, detail="ranges 须为非空的 [[起始行,结束行],…] 列表")
    block = mlib.create_block(fid, str(body.get("title") or ""), str(body.get("note") or ""), ranges)
    if not block:
        raise HTTPException(status_code=422, detail="区间全部无效（行号越界或为空）")
    return block


@router.put("/materials/blocks/{bid}")
async def update_block(bid: str, body: dict):
    """改标题/备注：{title?, note?}。"""
    block = mlib.update_block(bid, body.get("title"), body.get("note"))
    if not block:
        raise HTTPException(status_code=404, detail="素材块不存在")
    return block


@router.delete("/materials/blocks/{bid}")
async def delete_block(bid: str):
    if not mlib.delete_block(bid):
        raise HTTPException(status_code=404, detail="素材块不存在")
    return {"ok": True}
