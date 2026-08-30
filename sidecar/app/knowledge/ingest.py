"""知识库入库管线：上传 → 后台解析 → 切段建 FTS 索引 → LLM 元数据抽取。

fire-and-forget（上传 API asyncio.create_task + to_thread，titler 先例）；
启动对账由 db.recover_stale_kb 兜底（残留 parsing/running → failed，可重触发）。

视觉路由：图片与云端解析专属格式（.doc）按「云端文档解析（PaddleOCR-VL，已配置
才触发）→ VLM（图片）→ 降级」取用；PDF 按逐页文本量分类（meta.scanned_pages），
含扫描页时优先云端整本解析（文档级 API 无逐页接口），无云端配置则扫描页渲染成图
走 VLM 逐页转写后拼回锚点。均未配置一律降级（收原件+登记+人工填，不阻塞上传）；
元数据抽取统一走文本管线（视觉只是图→文本，与 docx 同路）。

状态语义：parse ready 即可检索（切段已完成）；extract 失败不影响检索，
仅 suggested_metadata 缺失（表单空着等人工填或重触发）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .. import baidu_ocr, db, vlm
from .. import config as cfg
from ..parse import convert as parse_convert
from ..parse import count_nodes, outline_with_lines, write_atomic
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

# 本地注册表不收、云端文档解析专属的格式（.docx/pdf/txt/md 恒走本地）
_CLOUD_ONLY_EXTS = {".doc"}

# 本地逐页 VL 转写的扫描页数预算：500 页扫描件串行转写要数小时且烧调用费，
# 超出封顶并提示配置云端整本解析（云端路径不受此限，服务端自行约束）
_MAX_SCAN_PAGES = 60

# 在跑条目（单飞）：连点 retrigger / 重复触发时跳过，防同一条目多条管线
# 并发跑互相覆盖产物、双跑 LLM 抽取（不加队列，跳过即反馈在状态轮询里）
_inflight: set[str] = set()


def schedule_ingest(kid: str) -> bool:
    """上传/重触发入口：后台跑完整管线，异常只落条目 error 字段。同一条目单飞，
    返回是否真正调度（False=已在跑，重复触发被跳过）。"""
    if kid in _inflight:
        logger.info("知识库入库在跑，跳过重复触发：%s", kid)
        return False
    _inflight.add(kid)
    asyncio.get_running_loop().create_task(_run_safe(kid))
    return True


async def _run_safe(kid: str) -> None:
    try:
        await asyncio.to_thread(run_ingest, kid)
    except Exception:
        logger.exception("知识库入库异常：%s", kid)
        try:
            db.kb_update_item(kid, parse_status="failed", error="入库异常，请重试或查看日志")
        except Exception:
            pass
    finally:
        _inflight.discard(kid)


def _item_stale(item: dict) -> bool:
    """写盘前的代际探测（探测+中止，不加锁）：条目已删除，或同路径重传了不同
    内容（hash 变了）→ 本轮管线作废，不再写盘/写库——旧管线晚到覆盖新结果的
    竞态从「分钟级解析窗口」收窄到「探测后毫秒级」。"""
    cur = db.kb_get_item(item["id"])
    return cur is None or cur["file_hash"] != item["file_hash"]


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
    _was_confirmed = item["review_status"] == "confirmed"

    db.kb_update_item(kid, parse_status="parsing", extract_status="pending", error=None)

    # ---- ① 解析（文本管线 / 云端文档解析 / VL 转写 / 混合拼接）----
    ext = src.suffix.lower()
    warnings: list[str] = []
    unavailable_conversion = "vision-unavailable"  # result=None 时的 meta.conversion
    try:
        if ext in parse_image.IMAGE_EXTS:
            result = _transcribe_image(src, warnings)
        elif ext in _CLOUD_ONLY_EXTS:
            if baidu_ocr.baidu_ocr_available():
                result = baidu_ocr.parse_via_baidu(src)
            else:
                # 降级与视觉同款：收原件+登记，不阻塞上传；人工填或配好后重新识别
                result = None
                unavailable_conversion = "parse-unavailable"
                warnings.append("文档解析未配置，该格式暂无法识别——可在设置中配置文档解析"
                                "（百度云）后重新识别，或直接在「信息」里手动填写")
        else:
            result = parse_convert(src)
            scanned = result.info.get("scanned_pages") or []
            if ext == ".pdf" and scanned:
                result = _fill_scanned_pages(src, result, warnings)
    except Exception as e:
        db.kb_update_item(kid, parse_status="failed", error=f"解析失败：{e}")
        return db.kb_get_item(kid) or {}

    # ---- ② 产物落盘 + 切段建索引 ----
    # 代际探测：解析（可能分钟级）期间条目被删/重传 → 本轮作废，不再写盘
    if _item_stale(item):
        logger.info("知识库入库中止（条目已删除或重传）：%s", kid)
        return db.kb_get_item(kid) or {}
    if result is None:
        md_text, info = "", {"conversion": unavailable_conversion, "tables": 0}
        outline: list[dict] = []
    else:
        md_text, info = result.md, result.info
        outline = outline_with_lines(md_text)
    n_headings = count_nodes(outline)
    if n_headings == 0 and md_text:
        warnings.append("未识别到标题结构，检索按固定窗口切段")
    if info.get("conversion") in ("docx-numbered", "pdf-numbered"):
        warnings.append("结构来自中文编号识别（标题印在原文，可验证），层级可能不完整")

    md_path, outline_path, meta_path = store.kb_parse_paths(file_name)
    digest = item["file_hash"]
    # 三件套原子写（md → outline → meta，meta 最后写=提交标记）：中断不留截断产物，
    # 内容预览不会读到半截 md。空文本不落 md：md_ready=false 让前端对图片降级条目走
    # 原件预览；unlink 同时清掉历史 0 字节 md（重新识别可自愈）
    if md_text:
        write_atomic(md_path, md_text)
    else:
        md_path.unlink(missing_ok=True)
    write_atomic(outline_path, json.dumps(outline, ensure_ascii=False, indent=2))
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
    write_atomic(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))

    reindex_item(kid)
    db.kb_update_item(kid, parse_status="ready")
    item = db.kb_get_item(kid) or {}

    # ---- ③ 元数据抽取（文本管线；失败不阻塞检索）----
    # 代际探测：切段建索引期间条目被删/重传 → 本轮作废
    if _item_stale(item):
        logger.info("知识库入库中止（条目已删除或重传）：%s", kid)
        return db.kb_get_item(kid) or {}
    _extract(item, md_text)
    final = db.kb_get_item(kid) or {}
    # 收敛探测（不加锁的最终一致）：确认若发生在管线上半场，②的段重建可能读到
    # 确认前的旧条目、晚到覆盖掉人工字段段——结束时发现「进来时未确认、现在已
    # 确认」就用最新状态补重建一次。残余窗口只剩本次重建自身的建段间隙，且
    # 任何后续确认保存/重新识别/重启（启动全量重建）都会自愈。
    if final.get("review_status") == "confirmed" and not _was_confirmed:
        reindex_item(kid)
        final = db.kb_get_item(kid) or {}
    return final


def _transcribe_image(src: Path, warnings: list[str]):
    """图片识别路由：云端文档解析（已配置优先，失败回退）→ VLM → None（降级）。"""
    if baidu_ocr.baidu_ocr_available():
        try:
            return baidu_ocr.parse_via_baidu(src)
        except Exception as e:
            warnings.append(f"云端文档解析失败（{e}），回退图片模型识别")
    try:
        return parse_image.transcribe(src)
    except VlmUnavailable as e:
        # 区分「模型没配」与「模型在但拒了这张图」（如超大小上限）——降级提示
        # 必须给出真实原因，否则用户对着大图一直以为没配模型
        if vlm.vlm_available():
            warnings.append(f"图片未识别：{e}")
        else:
            warnings.append("没有可用的图片识别模型（文档解析也未配置），图片未识别——可在设置中配置后重新识别，或直接在「信息」里手动填写")
        return None


def _fill_scanned_pages(src: Path, result, warnings: list[str]) -> object:
    """扫描页处理：云端文档解析整本识别（文档级 API 无逐页接口，已配置优先）
    → 视觉模型逐页转写拼回页码锚点（混合 PDF = pdf-mixed）→ 降级警示。"""
    if baidu_ocr.baidu_ocr_available():
        try:
            cloud = baidu_ocr.parse_via_baidu(src)
            warnings.append("扫描版 PDF 已由云端文档解析（PaddleOCR-VL）整本识别，建议人工核对关键内容")
            return cloud
        except Exception as e:
            warnings.append(f"云端文档解析失败（{e}），回退图片模型逐页转写")

    tmp_dir = Path(tempfile.mkdtemp(prefix="kb-pages-"))
    try:
        from .. import vlm

        pages = scanned(result)
        if len(pages) > _MAX_SCAN_PAGES:
            warnings.append(
                f"扫描页 {len(pages)} 页超出本地逐页转写预算（{_MAX_SCAN_PAGES}），"
                f"仅转写前 {_MAX_SCAN_PAGES} 页——建议在设置中配置云端文档解析整本识别"
            )
            pages = pages[:_MAX_SCAN_PAGES]
        md = result.md
        converted = 0
        for pno in pages:
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
            warnings.append(f"{converted} 个扫描页已由图片模型转写（识别结果建议人工核对）")
        return result
    except VlmUnavailable:
        warnings.append(
            f"{len(scanned(result))} 个扫描页未识别（无可用图片识别模型）——可在设置中配置后重新识别"
        )
        return result
    finally:
        # 渲染页图是临时产物（系统临时目录，不进产物目录），转写完成即清
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
    """LLM 元数据抽取 → suggested_metadata（doc_type 同步到条目；business 永不覆盖）。

    模型走 extract 角色（设置页「后台任务模型」，未指定回落 default）——抽取是
    后台轻任务，可与主对话用不同的（更便宜的）模型。
    """
    kid = item["id"]
    if len((md_text or "").strip()) < _MIN_EXTRACT_CHARS:
        db.kb_update_item(kid, extract_status="skipped", error=None)
        return
    profile = cfg.resolve_extract_profile()
    api_key = cfg.model_key(profile.id)
    if not api_key:
        db.kb_update_item(kid, extract_status="skipped", error=None)
        return
    db.kb_update_item(kid, extract_status="running")
    try:
        suggested = _call_extract(api_key, profile, item["file_name"], md_text)
    except Exception as e:
        db.kb_update_item(kid, extract_status="failed", error=f"元数据抽取失败：{e}")
        return
    if not suggested:
        db.kb_update_item(kid, extract_status="failed", error="元数据抽取返回无法解析")
        return
    if (db.kb_get_item(kid) or {}).get("review_status") == "confirmed":
        # 已确认条目：建议列照常更新，但 doc_type 不回写——人工确认的类型
        # 不被晚到的抽取覆盖（business_metadata 本就永不覆盖）
        db.kb_update_item(
            kid,
            extract_status="done",
            suggested_metadata=json.dumps(suggested, ensure_ascii=False),
            error=None,
        )
        return
    db.kb_update_item(
        kid,
        extract_status="done",
        suggested_metadata=json.dumps(suggested, ensure_ascii=False),
        doc_type=suggested.get("doc_type") if get_type(suggested.get("doc_type")) else "other",
        error=None,
    )


def _call_extract(api_key: str, profile, file_name: str, md_text: str) -> dict | None:
    from langchain_deepseek import ChatDeepSeek

    model = ChatDeepSeek(api_key=api_key, base_url=profile.base_url, model=profile.model, timeout=60)
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
