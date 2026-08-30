"""知识库 API：上传（后台解析+抽取）/ 条目列表与详情 / 元数据确认 / 红点计数 / 类型注册表。

知识库是跨任务的公司资料层（workspace/knowledge/，单库）。上传后 fire-and-forget
入库（解析 → FTS 切段 → LLM 抽取），条目状态轮询可见；元数据确认走本页面表单
（PUT metadata：business_metadata 落库 + review_status=confirmed + 重建检索段——
人工填的字段也要可检索）。确认是提示不是门禁：pending_review 条目照常可检索。
"""

import hashlib
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import db
from ..knowledge import store
from ..knowledge.ingest import reindex_item, schedule_ingest
from ..knowledge.types import FIELD_LABELS, TYPES, get_type, normalize_field_keys, types_payload
from ..parse.image import IMAGE_EXTS

router = APIRouter()

# 知识库白名单 = 解析注册表（docx/pdf/txt/md）+ 视觉/云端转写（图片 + .doc）
KB_ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md", ".doc"} | IMAGE_EXTS
MAX_SIZE_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024

# 解析档位 → 人话标签（与 tender 解析确认门同款措辞；单一真值在 sidecar）
CONVERSION_LABELS: dict[str, str] = {
    "docx-native": "样式标题（作者声明）",
    "docx-numbered": "中文编号识别（标题印在原文）",
    "pdf-toc": "书签目录（作者声明）",
    "pdf-link-toc": "目录页超链接（作者自报）",
    "pdf-printed-toc": "印刷目录页（作者自报）",
    "pdf-numbered": "中文编号识别（标题印在原文）",
    "pdf-plain": "未识别出结构",
    "pdf-fontsize": "启发式（字号判级，旧版）",  # 旧存量 meta 的兼容显示
    "pdf-mixed": "混合（扫描页已转写）",
    "paddleocr-vl": "云端文档解析（PaddleOCR-VL）",
    "vision": "视觉转写",
    "vision-unavailable": "未识别（VLM 未配置）",
    "parse-unavailable": "未识别（未配置文档解析）",
    "txt-passthrough": "纯文本",
    "md-passthrough": "纯文本",
}


def _clean_name(raw: str) -> str | None:
    name = Path(raw).name.strip()
    if not name or name.startswith("."):
        return None
    return name


@router.get("/kb/types")
async def list_types():
    return {"types": types_payload(), "field_labels": FIELD_LABELS}


@router.get("/kb/badge")
async def badge():
    """侧栏红点数据源：待确认条目数（纯计数，前端 60s 轮询）。"""
    return {"pending": db.kb_count_pending()}


@router.post("/kb/files", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    raw = file.filename or ""
    name = _clean_name(raw)
    if name is None:
        raise HTTPException(status_code=400, detail="文件名非法")
    ext = Path(name).suffix.lower()
    if ext not in KB_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{ext or '(无扩展名)'}（允许 .docx/.pdf/.txt/.md/.doc 及图片 .jpg/.png）",
        )

    # 先落临时文件算 hash：同内容文件已入库则直接提示（不重复解析/占用条目）
    store.ensure_dirs()
    tmp = store.kb_files_dir() / f".{name}.{uuid.uuid4().hex[:8]}.part"
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

    existing = db.kb_get_item_by_hash(digest)
    if existing:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=409,
            detail=f"内容相同的文件已在知识库中：{existing['file_name']}（每份资料只存一份）",
        )

    target = store.unique_file_path(name)
    os.replace(tmp, target)
    item = db.kb_insert_item(file_name=target.name, file_hash=digest, title=Path(target.name).stem, ext=ext)
    schedule_ingest(item["id"])
    return {"id": item["id"], "file_name": target.name, "size": size, "parse_status": "pending"}


def _parse_json_col(item: dict, key: str) -> dict | None:
    raw = item.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def _normalize_meta(meta: dict | None) -> dict | None:
    """存量 suggested/business 可能是中文标签键（早期 prompt 只给过标签）——
    输出时归一为 code，前端「模板 ∪ 已有值」合并才不会出现重复字段。"""
    if not meta:
        return meta
    out = dict(meta)
    for key in ("fields", "extra"):
        if isinstance(out.get(key), dict):
            out[key] = normalize_field_keys(out[key])
    return out


def _item_out(item: dict) -> dict:
    md_path, _, _ = store.kb_parse_paths(item["file_name"])
    return {
        **item,
        "suggested_metadata": _normalize_meta(_parse_json_col(item, "suggested_metadata")),
        "business_metadata": _normalize_meta(_parse_json_col(item, "business_metadata")),
        "doc_type_name": TYPES[item["doc_type"]].name if item.get("doc_type") in TYPES else (item.get("doc_type") or "其他"),
        "md_ready": md_path.is_file(),
    }


def _parse_summary(file_name: str) -> dict | None:
    """解析概况（内容页顶部展示）：meta.json 数字/警示 + outline 第一层章节。
    meta 缺失（未解析/降级条目）返回 None，前端不渲染概况条。"""
    _, outline_path, meta_path = store.kb_parse_paths(file_name)
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(meta, dict):
        return None
    conv = meta.get("conversion") or "?"
    out: dict = {
        "conversion": conv,
        "conversion_label": CONVERSION_LABELS.get(conv, conv),
        "chars": meta.get("chars"),
        "headings": meta.get("headings"),
        "tables": meta.get("tables"),
        "warnings": meta.get("warnings") or [],
    }
    if meta.get("pages") is not None:
        out["pages"] = meta["pages"]
    if meta.get("scanned_pages"):
        out["scanned_pages"] = meta["scanned_pages"]
    try:
        outline = json.loads(outline_path.read_text(encoding="utf-8")) if outline_path.is_file() else []
        out["top_sections"] = [n.get("标题") or "" for n in outline[:8] if isinstance(n, dict) and n.get("标题")]
    except ValueError:
        out["top_sections"] = []
    return out


@router.get("/kb/items")
async def list_items(
    review_status: str | None = None,
    doc_type: str | None = None,
    q: str | None = None,
):
    return {"items": [_item_out(it) for it in db.kb_list_items(review_status, doc_type, q)]}


@router.get("/kb/items/{kid}")
async def get_item(kid: str):
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    return _item_out(item)


@router.get("/kb/items/{kid}/content")
async def get_item_content(kid: str):
    """解析产物 markdown（内容预览用；图片等降级条目为空串）+ 解析概况 meta。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    md_path, _, _ = store.kb_parse_paths(item["file_name"])
    # 仅解析完成的条目吐正文：重新识别（parsing）期间盘上还是旧 md，直接返回会把
    # 旧内容当新内容渲染（前端落回「解析中」分支）；failed 同理不吐半截产物。
    # 降级条目（图片收原件）parse_status 也是 ready、只是 md 缺失返回空串走原件预览。
    text = (
        md_path.read_text(encoding="utf-8")
        if item["parse_status"] == "ready" and md_path.is_file()
        else ""
    )
    return {"id": kid, "content": text, "meta": _parse_summary(item["file_name"])}


@router.get("/kb/items/{kid}/raw")
async def get_item_raw(kid: str):
    """原件文件流（图片条目预览用）。"""
    from fastapi.responses import FileResponse

    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    src = store.kb_files_dir() / item["file_name"]
    if not src.is_file():
        raise HTTPException(status_code=404, detail="原件缺失")
    return FileResponse(src, filename=item["file_name"])


@router.put("/kb/items/{kid}/metadata")
async def confirm_metadata(kid: str, body: dict):
    """确认表单保存：body = {doc_type, fields: {code: value}, extra?} →
    business_metadata + review_status=confirmed；重算检索段（人工字段可检索）。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    doc_type = body.get("doc_type")
    if not get_type(doc_type):
        raise HTTPException(status_code=422, detail=f"未知类型：{doc_type}（须为预置类型 code）")
    fields_raw = body.get("fields") or {}
    if not isinstance(fields_raw, dict):
        raise HTTPException(status_code=422, detail="fields 须为对象")
    fields = {k: {"value": v} for k, v in fields_raw.items() if isinstance(v, str) and v.strip()}
    extra_raw = body.get("extra") or {}
    extra = {k: {"value": v} for k, v in extra_raw.items() if isinstance(v, str) and v.strip()} if isinstance(extra_raw, dict) else {}
    # 不落确认时间戳：模型写的时间戳不可信（confirmed_at 零点占位先例），审计靠 updated_at
    biz = {
        "doc_type": doc_type,
        "fields": fields,
        "extra": extra,
    }
    db.kb_update_item(
        kid,
        doc_type=doc_type,
        review_status="confirmed",
        business_metadata=json.dumps(biz, ensure_ascii=False),
    )
    reindex_item(kid)
    return _item_out(db.kb_get_item(kid) or {})


@router.post("/kb/items/{kid}/retrigger", status_code=202)
async def retrigger(kid: str):
    """重新解析+抽取（覆盖 suggested；business 已确认字段保留不被覆盖）。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    if not schedule_ingest(kid):
        # 单飞跳过：明确告知而非 202 静默（前端据此 toast「识别进行中」）
        raise HTTPException(status_code=409, detail="该条目正在识别中，请稍候")
    return {"ok": True}


@router.delete("/kb/items/{kid}")
async def delete_item(kid: str):
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    db.kb_delete_item(kid)
    store.delete_item_files(item["file_name"])
    return {"ok": True}
