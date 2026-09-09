"""知识库 API（v3 事实层）：上传/列表详情/确认/删除/图片查看。

上传不选分类——类型由管线③判定，角色由类型派生。列表的 role 过滤是分组视图
（事实类/写法类），不是检索边界（检索边界在工具层按角色加权）。写作素材在
独立的素材库（/api/materials，用户手工勾选建块），知识库不做任何章节拆分。
"""

import hashlib
import json
import os
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from .. import db
from ..knowledge import images, store
from ..knowledge.freshness import freshness_warnings
from ..knowledge.ingest import reindex_item, schedule_ingest
from ..knowledge.types import (
    FIELD_LABELS,
    get_type,
    role_of,
    type_name,
    types_payload,
)
from ..parse.image import IMAGE_EXTS

router = APIRouter()

KB_ALLOWED_EXTENSIONS = {".docx", ".pdf", ".txt", ".md", ".doc"} | IMAGE_EXTS
MAX_SIZE_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024

CONVERSION_LABELS: dict[str, str] = {
    "docx-native": "样式标题（作者声明）",
    "docx-numbered": "中文编号识别（标题印在原文）",
    "pdf-toc": "书签目录（作者声明）",
    "pdf-link-toc": "目录页超链接（作者自报）",
    "pdf-printed-toc": "印刷目录页（作者自报）",
    "pdf-numbered": "中文编号识别（标题印在原文）",
    "pdf-plain": "未识别出结构",
    "pdf-fontsize": "启发式（字号判级，旧版）",
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
    return {"id": item["id"], "file_name": target.name, "size": size}


def _parse_meta_col(item: dict, key: str) -> dict | None:
    raw = item.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def _capability(item: dict) -> str:
    """能力档位（派生不落库）：stored→searchable→typed（素材分离后无 enriched）。"""
    if item["parse_status"] != "ready":
        return "stored"
    if item["extract_status"] != "done" and not item.get("doc_type"):
        return "searchable"
    return "typed"


def _item_out(item: dict) -> dict:
    md_path, _, _, _ = store.kb_parse_paths(item["file_name"])
    suggested = _parse_meta_col(item, "suggested_metadata")
    business = _parse_meta_col(item, "business_metadata")
    doc_type = business.get("doc_type") if business and business.get("doc_type") else item.get("doc_type")
    return {
        **{k: v for k, v in item.items() if k not in ("suggested_metadata", "business_metadata")},
        "doc_type": doc_type,
        "doc_type_name": type_name(doc_type),
        "role": role_of(doc_type),
        "capability": _capability(item),
        "suggested": suggested,
        "business": business,
        "check_result": _parse_meta_col(item, "check_result"),
        "freshness": freshness_warnings({"business_metadata": business, "suggested_metadata": suggested}),
        "md_ready": md_path.is_file(),
    }


def _parse_summary(file_name: str) -> dict | None:
    _, outline_path, meta_path, _ = store.kb_parse_paths(file_name)
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
    if meta.get("image_count") is not None:
        out["image_count"] = meta["image_count"]
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
    role: str | None = None,
):
    items = db.kb_list_items(review_status, doc_type, q)
    if role in ("fact", "writing"):
        items = [it for it in items if role_of(
            (_parse_meta_col(it, "business_metadata") or {}).get("doc_type") or it.get("doc_type")
        ) == role]
    return {"items": [_item_out(it) for it in items]}


@router.get("/kb/items/{kid}")
async def get_item(kid: str):
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    return _item_out(item)


@router.get("/kb/items/{kid}/content")
async def get_item_content(kid: str):
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    md_path, _, _, _ = store.kb_parse_paths(item["file_name"])
    text = (
        md_path.read_text(encoding="utf-8")
        if item["parse_status"] == "ready" and md_path.is_file()
        else ""
    )
    return {"id": kid, "content": text, "meta": _parse_summary(item["file_name"])}


@router.get("/kb/items/{kid}/raw")
async def get_item_raw(kid: str):
    """原件文件流（图片条目预览用）。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    src = store.kb_files_dir() / item["file_name"]
    if not src.is_file():
        raise HTTPException(status_code=404, detail="原件缺失")
    return FileResponse(src, filename=item["file_name"])


@router.get("/kb/items/{kid}/images")
async def list_item_images(kid: str):
    """本文档图片清单（内容页「本文档图片 N 张」折叠区；图片仅供查看，与素材无关）。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    return {"id": kid, "images": images.list_images(item["file_name"])}


@router.get("/kb/items/{kid}/images/{name}")
async def get_material_image(kid: str, name: str):
    """图片素材文件流（路径限制在 parse/<stem>/images/ 内，防穿越）。

    存量 TIFF/BMP 服务端转 PNG（浏览器不解 TIFF；转码按 mtime 入缓存，
    重抽取同名覆盖后自动失效）。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    img_dir = store.kb_images_dir(item["file_name"])
    path = (img_dir / name).resolve()
    if not str(path).startswith(str(img_dir.resolve()) + os.sep) or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    if path.suffix.lower() in images._BROWSER_UNFRIENDLY:
        return Response(
            content=_convert_unfriendly_image(str(path), path.stat().st_mtime_ns),
            media_type="image/png",
        )
    return FileResponse(path)


@lru_cache(maxsize=8)
def _convert_unfriendly_image(path_str: str, mtime_ns: int) -> bytes:
    # 缓存的是整图 PNG 字节（扫描件单张可达数 MB），容量必须小：满载常驻控制在
    # ~20MB 量级；源头文件在盘上，miss 重转一次的代价远小于大缓存常驻
    from ..knowledge import images

    data, _ = images.as_browser_friendly(Path(path_str).read_bytes(), Path(path_str).suffix)
    return data


@router.put("/kb/items/{kid}/metadata")
async def confirm_metadata(kid: str, body: dict):
    """确认保存：body = {doc_type, statement?, questions?, fields?, extra?} → business_metadata +
    confirmed + 重建检索段（人工字段与说明可检索）。改到 auto 类且就绪且无素材
    时自动补拆。"""
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
    statement = body.get("statement")
    # 检索问题：可选字符串数组；去空去重，≤10 条、单条 ≤40 字（留空/缺省=沿用建议版）
    questions_raw = body.get("questions")
    if questions_raw is not None and not isinstance(questions_raw, list):
        raise HTTPException(status_code=422, detail="questions 须为字符串数组")
    questions: list[str] = []
    if isinstance(questions_raw, list):
        for q in questions_raw:
            if not isinstance(q, str):
                raise HTTPException(status_code=422, detail="questions 须为字符串数组")
            q = q.strip()
            if not q:
                continue
            if len(q) > 40:
                raise HTTPException(status_code=422, detail=f"检索问题过长（≤40 字）：{q[:20]}…")
            if q not in questions:
                questions.append(q)
        if len(questions) > 10:
            raise HTTPException(status_code=422, detail="检索问题最多 10 条")
    biz = {"doc_type": doc_type, "fields": fields, "extra": extra}
    if isinstance(statement, str) and statement.strip():
        biz["statement"] = statement.strip()
    if questions:
        biz["questions"] = questions
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
    """重新解析+抽取（覆盖 suggested；business 保留不被覆盖）。"""
    item = db.kb_get_item(kid)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    if not schedule_ingest(kid):
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
