"""写作素材库 API（v2 手工构建）：文件上传/解析、目录树、块 CRUD。

素材块 = 用户在目录树上勾选的章节区间集合 + 备注；与知识库彻底分离
（自己的文件、自己的解析、零 LLM）。块检索段复用 kb_segments（mt_ 前缀隔离）。
"""

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import db
from ..knowledge import materials_lib as mlib

router = APIRouter()

# 素材库只收 .docx：素材块的价值锚点是「原文可整体拷贝注入新标书」——只有 docx
# 解析才产出 element_map（元素级映射，图表/编号/格式可随块注入），其余格式只能
# 文字参考（图进不来、表格是碎的），属 silently 缩水路径；老 .doc 在 Word 里
# 「另存为 .docx」一步即可（2026-09-08 用户拍板）。
MT_ALLOWED_EXTENSIONS = {".docx"}
_MT_EXTENSION_HINT = "素材库只收 .docx（历史标书原文，支持图表整体拷贝）——PDF/老 .doc 范文请先用 Word 打开，另存为 .docx 再传"
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
        raise HTTPException(status_code=400, detail=_MT_EXTENSION_HINT)

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


@router.post("/materials/files/{fid}/reparse", status_code=202)
async def reparse_file(fid: str):
    """重新解析（失败重试；ready 也可重触发，解析幂等）。"""
    if not db.mt_get_file(fid):
        raise HTTPException(status_code=404, detail="素材文件不存在")
    if not mlib.schedule_parse(fid):
        raise HTTPException(status_code=409, detail="该文件正在解析中，请稍候")
    return {"ok": True}


@router.get("/materials/files/{fid}/raw")
async def get_file_raw(fid: str):
    """原件文件流（预览「原件」模式：docx/pdf 版式渲染，文件不出本机）。"""
    f = db.mt_get_file(fid)
    if not f:
        raise HTTPException(status_code=404, detail="素材文件不存在")
    src = mlib.mt_files_dir() / f["file_name"]
    if not src.is_file():
        raise HTTPException(status_code=404, detail="原件缺失")
    return FileResponse(src, filename=f["file_name"])


@router.get("/materials/blocks")
async def list_blocks(q: str | None = None):
    """全部素材块（跨文件；文件信息附带）。

    q 非空时过滤：正文 FTS 命中（标题+备注+正文都进了检索段）∪ 标题/备注
    本地子串匹配（FTS 分词漏的直给兜底）。
    """
    files = {f["id"]: f for f in db.mt_list_files()}
    lq = (q or "").strip().lower()
    matched = mlib.search_block_ids(q) if lq else None
    out = []
    for b in db.mt_list_blocks():
        f = files.get(b["file_id"])
        if not f:
            continue
        if matched is not None:
            hit = b["id"] in matched or lq in b["title"].lower() or lq in (b.get("note") or "").lower()
            if not hit:
                continue
        out.append({**b, "file_name": f["file_name"]})
    return {"blocks": out}


@router.get("/materials/blocks/{bid}/content")
async def get_block_content(bid: str, preview: int | None = None):
    """块内容预览：分节切片（区间标签 + 正文），卡片展开区数据源。

    preview（可选，2026-09-13 内存修复批）：行内预览预算（字符）——设定时
    sections 正文按累计预算截断（合计 ≤ preview、预算耗尽即停），chars 仍为
    真实总字数；供写作指引表等「每行只显示百来字」的消费方避免整块拉全文
    （几十个块的全量内容同时驻留内存）。不传行为不变。
    """
    content = mlib.block_content(bid)
    if not content:
        raise HTTPException(status_code=404, detail="素材块不存在")
    if preview is not None:
        if preview < 1:
            raise HTTPException(status_code=422, detail="preview 须为正整数")
        content = _truncate_preview(content, preview)
    return content


def _truncate_preview(content: dict, budget: int) -> dict:
    """按累计预算截断 sections 正文（chars 保留真实总字数），预算耗尽即停。"""
    out: list[dict] = []
    used = 0
    for sec in content.get("sections") or []:
        room = max(0, budget - used)
        out.append({**sec, "text": sec["text"][:room]})
        used += len(sec["text"])
        if used >= budget:
            break
    return {**content, "sections": out}


# 挑章节预览单次跨度上限（防误点根节点一次拉整本）
_PREVIEW_MAX_LINES = 2000


@router.get("/materials/files/{fid}/content")
async def get_file_content(fid: str, start: int, end: int):
    """文件片段内容（挑章节实时预览）：点目录树节点按行号取该节正文。"""
    f = db.mt_get_file(fid)
    if not f:
        raise HTTPException(status_code=404, detail="素材文件不存在")
    if f["parse_status"] != "ready":
        raise HTTPException(status_code=422, detail="文件尚未解析完成，稍候再试")
    if start < 1 or end < start:
        raise HTTPException(status_code=422, detail="行号区间无效")
    if end - start + 1 > _PREVIEW_MAX_LINES:
        raise HTTPException(status_code=422, detail="预览区间过大，请选择更小的章节")
    content = mlib.file_content(fid, start, end)
    if content is None:
        raise HTTPException(status_code=404, detail="解析产物缺失——请重新解析该文件")
    return content


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
