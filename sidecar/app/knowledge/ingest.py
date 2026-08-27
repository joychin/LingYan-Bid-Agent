"""知识库入库管线：上传 → 后台解析 → 切段建 FTS 索引 → LLM 元数据抽取。

fire-and-forget（上传 API asyncio.create_task + to_thread，titler 先例）；
启动对账由 db.recover_stale_kb 兜底（残留 parsing/running → failed，可重触发）。

视觉路由：图片整体走 VL 转写；PDF 按逐页文本量分类（meta.scanned_pages），
扫描页渲染成图走 VL 转写后拼回锚点。VLM 未配置一律降级（收原件+登记+人工填，
不阻塞上传）；元数据抽取统一走文本管线（VL 只是图→文本，与 docx 同路）。

状态语义：parse ready 即可检索（切段已完成）；extract 失败不影响检索，
仅 suggested_metadata 缺失（表单空着等人工填或重触发）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import config as cfg
from .. import db
from ..parse import convert as parse_convert
from ..parse import count_nodes, outline_with_lines, sha256_file
from ..parse import image as parse_image
from ..parse import pdf as parse_pdf
from ..vlm import VlmUnavailable
from . import fts, store
from .segmenter import segments_from
from .types import EXTRACT_SYSTEM, FIELD_LABELS, build_extract_prompt, get_type, normalize_field_keys

logger = logging.getLogger(__name__)

# 转写文本低于此值不做 LLM 抽取（信息量不足，人工填更靠谱）
_MIN_EXTRACT_CHARS = 50
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_JSON_RE = re.compile(r"\{.*\}", re.S)


def schedule_ingest(kid: str) -> None:
    """上传/重触发入口：后台跑完整管线，异常只落条目 error 字段。"""
    asyncio.get_running_loop().create_task(_run_safe(kid))


async def _run_safe(kid: str) -> None:
    try:
        await asyncio.to_thread(run_ingest, kid)
    except Exception:
        logger.exception("知识库入库异常：%s", kid)
        try:
            db.kb_update_item(kid, parse_status="failed", error="入库异常，请重试或查看日志")
        except Exception:
            pass


def run_ingest(kid: str) -> dict:
    """同步管线主体（供后台任务与重建索引复用）。返回最终条目。"""
    item = db.kb_get_item(kid)
    if not item:
        raise ValueError(f"条目不存在：{kid}")
    file_name = item["file_name"]
    src = store.kb_files_dir() / file_name
    if not src.is_file():
        db.kb_update_item(kid, parse_status="failed", error="原件缺失")
        return db.kb_get_item(kid) or {}

    db.kb_update_item(kid, parse_status="parsing", extract_status="pending", error=None)

    # ---- ① 解析（文本管线 / VL 转写 / 混合拼接）----
    ext = src.suffix.lower()
    warnings: list[str] = []
    try:
        if ext in parse_image.IMAGE_EXTS:
            try:
                result = parse_image.transcribe(src)
            except VlmUnavailable:
                # 降级：收原件+登记，无文本可检索；确认表单人工填（元数据段在确认时建索引）
                result = None
                warnings.append("视觉模型未配置，图片未识别——可在设置中配置 VLM 后重新识别，或直接在「信息」里手动填写")
        else:
            result = parse_convert(src)
            scanned = result.info.get("scanned_pages") or []
            if ext == ".pdf" and scanned:
                result = _fill_scanned_pages(src, result, warnings)
    except Exception as e:
        db.kb_update_item(kid, parse_status="failed", error=f"解析失败：{e}")
        return db.kb_get_item(kid) or {}

    # ---- ② 产物落盘 + 切段建索引 ----
    if result is None:
        md_text, info = "", {"conversion": "vision-unavailable", "tables": 0}
        outline: list[dict] = []
    else:
        md_text, info = result.md, result.info
        outline = outline_with_lines(md_text)
    n_headings = count_nodes(outline)
    if n_headings == 0 and md_text:
        warnings.append("未识别到标题结构，检索按固定窗口切段")
    if info.get("conversion") in ("docx-numbered", "pdf-fontsize"):
        warnings.append("结构来自启发式识别（无样式/无书签），层级可能不完整或有误")

    md_path, outline_path, meta_path = store.kb_parse_paths(file_name)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    digest = item["file_hash"]
    if md_text:
        md_path.write_text(md_text, encoding="utf-8")
    else:
        # 空文本不落 md：md_ready=false 让前端对图片降级条目走原件预览；
        # unlink 同时清掉历史 0 字节 md（重新识别可自愈）
        md_path.unlink(missing_ok=True)
    outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "source": file_name,
        "sha256": digest,
        "bytes": src.stat().st_size,
        "conversion": info.get("conversion", "?"),
        "chars": len(md_text),
        "headings": n_headings,
        "tables": info.get("tables", 0),
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if "pages" in info:
        meta["pages"] = info["pages"]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    reindex_item(kid)
    db.kb_update_item(kid, parse_status="ready")
    item = db.kb_get_item(kid) or {}

    # ---- ③ 元数据抽取（文本管线；失败不阻塞检索）----
    _extract(item, md_text)
    return db.kb_get_item(kid) or {}


def _fill_scanned_pages(src: Path, result, warnings: list[str]) -> object:
    """扫描页渲染成图走 VL 转写，拼回页码锚点（混合 PDF = pdf-mixed）。"""
    tmp_dir = store.kb_parse_dir(src.name) / "_pages"
    try:
        from .. import vlm

        md = result.md
        converted = 0
        for pno in scanned(result):
            png = tmp_dir / f"p{pno}.png"
            parse_pdf.render_page_png(src, pno, png)
            try:
                text = vlm.vlm_read_image(png, _PAGE_PROMPT)
            except VlmUnavailable:
                raise
            if text.strip():
                md = parse_pdf.insert_page_text(md, pno, text)
                converted += 1
        result.md = md
        result.info = {**result.info, "conversion": "pdf-mixed"}
        if converted:
            warnings.append(f"{converted} 个扫描页已由视觉模型转写（识别结果建议人工核对）")
        return result
    except VlmUnavailable:
        warnings.append(
            f"{len(scanned(result))} 个扫描页未识别（视觉模型未配置）——可在设置中配置 VLM 后重新识别"
        )
        return result
    finally:
        # 渲染页图是临时产物，转写完成即清
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def scanned(result) -> list[int]:
    return result.info.get("scanned_pages") or []


_PAGE_PROMPT = (
    "完整转写这页扫描件中的所有可见文字，按阅读顺序输出纯文本（表格保留结构、"
    "印章/签名用「[印章：xxx]」「[签名]」标注）；无法辨认的字用「□」占位，不要编造。"
    "只输出转写内容。"
)


def _loads(raw) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def reindex_item(kid: str) -> None:
    """重建条目检索段：md 切段 + 已确认元数据合成一段（人工填的字段也要可检索）。"""
    item = db.kb_get_item(kid)
    if not item:
        return
    segs: list[dict] = []
    md_path, outline_path, _ = store.kb_parse_paths(item["file_name"])
    if md_path.is_file():
        md_text = md_path.read_text(encoding="utf-8")
        outline = json.loads(outline_path.read_text(encoding="utf-8")) if outline_path.is_file() else []
        segs = segments_from(md_text, outline)
    biz = _loads(item.get("business_metadata"))
    if biz:
        fields = biz.get("fields") or {}
        pairs = [
            f"{FIELD_LABELS.get(k, k)}：{v.get('value') if isinstance(v, dict) else v}"
            for k, v in fields.items()
        ]
        extra = biz.get("extra") or {}
        pairs += [
            f"{FIELD_LABELS.get(k, k)}：{v.get('value') if isinstance(v, dict) else v}"
            for k, v in extra.items()
        ]
        if pairs:
            segs.append({
                "section_path": "条目信息（人工确认）",
                "line_start": None, "line_end": None, "page_start": None,
                "raw": "\n".join(pairs),
            })
    db.kb_replace_segments(
        kid,
        [{**s, "body": fts.segment_for_fts(s.pop("raw"))} for s in segs],
    )


def _extract(item: dict, md_text: str) -> None:
    """LLM 元数据抽取 → suggested_metadata（doc_type 同步到条目；business 永不覆盖）。"""
    kid = item["id"]
    if len((md_text or "").strip()) < _MIN_EXTRACT_CHARS:
        db.kb_update_item(kid, extract_status="skipped", error=None)
        return
    api_key = cfg.llm_api_key()
    if not api_key:
        db.kb_update_item(kid, extract_status="skipped", error=None)
        return
    db.kb_update_item(kid, extract_status="running")
    try:
        suggested = _call_extract(api_key, item["file_name"], md_text)
    except Exception as e:
        db.kb_update_item(kid, extract_status="failed", error=f"元数据抽取失败：{e}")
        return
    if not suggested:
        db.kb_update_item(kid, extract_status="failed", error="元数据抽取返回无法解析")
        return
    db.kb_update_item(
        kid,
        extract_status="done",
        suggested_metadata=json.dumps(suggested, ensure_ascii=False),
        doc_type=suggested.get("doc_type") if get_type(suggested.get("doc_type")) else "other",
        error=None,
    )


def _call_extract(api_key: str, file_name: str, md_text: str) -> dict | None:
    from langchain_deepseek import ChatDeepSeek

    model = ChatDeepSeek(api_key=api_key, base_url=cfg.llm_base_url(), model=cfg.llm_model(), timeout=60)
    prompt = build_extract_prompt(file_name, md_text)
    resp = model.invoke([("system", EXTRACT_SYSTEM), ("user", prompt)])
    raw = getattr(resp, "content", "")
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") or "" for b in raw if isinstance(b, dict))
    data = _parse_json(raw)
    if data is not None:
        # LLM 偶发用中文标签做键——落库前归一为注册 code
        for key in ("fields", "extra"):
            if isinstance(data.get(key), dict):
                data[key] = normalize_field_keys(data[key])
    return data


def _parse_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or "doc_type" not in data:
        return None
    return data


def rebuild_kb_index() -> int:
    """启动重建：全部条目重切索引（磁盘 md 权威，对齐 rebuild_artifact_index 语义）。"""
    items = db.kb_list_items()
    for it in items:
        if it["parse_status"] == "ready":
            reindex_item(it["id"])
    return len(items)
