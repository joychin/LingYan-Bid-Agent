"""知识库入库管线（v3 事实层）：登记 → 解析（可检索底线）→ 三合一抽取 → 图片抽取。

写作素材在独立的素材库（materials_lib，用户手工勾选建块），知识库不做任何章节
拆分——历史标书在此只做事实检索（statement + 业绩候选段）。

fire-and-forget（上传 API bg.spawn_background + bg.run_in_ingest 专用线程池）；启动对账
db.recover_stale_kb 兜底（残留 parsing/running → failed + 清 progress，可重触发）。

每步完成即对外生效（收益逐层提交，无跨步事务）：
- 解析落盘+切段完成 → 可检索（②），慢工序不挡可用性；
- 抽取完成 → 类型/内容说明/时间字段（③），失败不挡检索；
- 图片抽取对所有类型执行（④，仅供内容页折叠区查看，与素材无关）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .. import baidu_ocr, bg, db, vlm
from .. import config as cfg
from ..parse import convert as parse_convert
from ..parse import count_nodes, outline_with_lines, write_atomic
from ..parse import image as parse_image
from ..parse import pdf as parse_pdf
from ..vlm import VlmUnavailable
from . import autocheck, fts, store
from . import extract as extract_mod
from . import images as images_mod
from .segmenter import segments_from
from .types import FIELD_LABELS, get_type

logger = logging.getLogger(__name__)

# 转写文本低于此值不做 LLM 抽取（信息量不足，人工填更靠谱）
_MIN_EXTRACT_CHARS = 50
# 在跑条目（单飞）：连点 retrigger / 重复触发时跳过
_inflight: set[str] = set()


def schedule_ingest(kid: str) -> bool:
    """上传/重触发入口：后台跑完整管线。同一条目单飞，返回是否真正调度。"""
    if kid in _inflight:
        logger.info("知识库入库在跑，跳过重复触发：%s", kid)
        return False
    _inflight.add(kid)
    bg.spawn_background(_run_safe(kid))
    return True


async def _run_safe(kid: str) -> None:
    try:
        await bg.run_in_ingest(run_ingest, kid)
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
    内容（hash 变了）→ 本轮管线作废，不再写盘/写库。"""
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

    db.kb_update_item(kid, parse_status="parsing", extract_status="pending", error=None, progress=None)

    # ---- ① 解析（文本管线 / 云端文档解析 / VL 转写 / 混合拼接）----
    ext = src.suffix.lower()
    warnings: list[str] = []
    unavailable_conversion = "vision-unavailable"  # result=None 时的 meta.conversion
    try:
        if ext in parse_image.IMAGE_EXTS:
            result = _transcribe_image(kid, src, warnings)
        elif ext in _CLOUD_ONLY_EXTS:
            if baidu_ocr.baidu_ocr_available():
                db.kb_update_item(kid, progress="云端识别中")
                result = baidu_ocr.parse_via_baidu(src)
            else:
                result = None
                unavailable_conversion = "parse-unavailable"
                warnings.append("文档解析未配置，该格式暂无法识别——可在设置中配置文档解析"
                                "（百度云）后重新识别，或直接在「信息」里手动填写")
        else:
            result = parse_convert(src)
            scanned = result.info.get("scanned_pages") or []
            if ext == ".pdf" and scanned:
                result = _fill_scanned_pages(kid, src, result, warnings)
    except Exception as e:
        db.kb_update_item(kid, parse_status="failed", error=f"解析失败：{e}", progress=None)
        return db.kb_get_item(kid) or {}

    # ---- ② 产物落盘 + 切段建索引（完成即可检索）----
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

    md_path, outline_path, meta_path, materials_path = store.kb_parse_paths(file_name)
    digest = item["file_hash"]
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
        "image_count": info.get("image_count"),
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if "pages" in info:
        meta["pages"] = info["pages"]
    if info.get("scanned_pages"):
        meta["scanned_pages"] = info["scanned_pages"]
    write_atomic(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))

    reindex_item(kid)
    db.kb_update_item(kid, parse_status="ready", progress=None)
    item = db.kb_get_item(kid) or {}

    # ---- ③ 三合一抽取（类型 + 内容说明 + 时间/身份锚点；失败不阻塞检索）----
    if _item_stale(item):
        logger.info("知识库入库中止（条目已删除或重传）：%s", kid)
        return db.kb_get_item(kid) or {}
    _extract(item, md_text)
    # 抽取产物（说明段/字段段）随③落库即进检索——收益逐层提交
    if not _item_stale(item):
        reindex_item(kid)
    item = db.kb_get_item(kid) or {}

    # ---- ④ 图片抽取（所有类型，仅供内容页折叠区查看）----
    if md_text and item.get("parse_status") == "ready":
        _extract_images_sync(item, src)
        item = db.kb_get_item(kid) or {}

    # 收敛探测（不加锁的最终一致）：确认若发生在管线上半场，②的段重建可能读到
    # 确认前的旧条目、晚到覆盖掉人工字段段——结束时发现「进来时未确认、现在已
    # 确认」就用最新状态补重建一次。
    final = db.kb_get_item(kid) or {}
    if final.get("review_status") == "confirmed" and item.get("review_status") != "confirmed":
        reindex_item(kid)
        final = db.kb_get_item(kid) or {}
    return final


def _extract_images_sync(item: dict, src: Path) -> None:
    """④ 图片抽取（确定性零 LLM，仅供内容页查看；失败不阻塞——可重触发自愈）。"""
    kid = item["id"]
    try:
        written, skipped = images_mod.extract_images(src, item["file_name"])
    except Exception:
        logger.exception("图片抽取失败（%s）", kid)
        return
    if _item_stale(item):
        return
    if written or skipped:
        # 抽取计数如实进解析概况（内容页折叠区的可见线索）
        _, _, meta_path, _ = store.kb_parse_paths(item["file_name"])
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            warns = meta.get("warnings") or []
            if skipped:
                warns.append(f"已抽取 {written} 张文档图片供查看（其余 {skipped} 张经附件区/装饰过滤或超限跳过）")
            meta["warnings"] = warns
            meta["extracted_images"] = written
            write_atomic(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        except (OSError, ValueError):
            pass


def _transcribe_image(kid: str, src: Path, warnings: list[str]):
    """图片识别路由：云端文档解析（已配置优先，失败回退）→ VLM → None（降级）。"""
    if baidu_ocr.baidu_ocr_available():
        try:
            db.kb_update_item(kid, progress="云端识别中")
            return baidu_ocr.parse_via_baidu(src)
        except Exception as e:
            warnings.append(f"云端文档解析失败（{e}），回退图片模型识别")
    try:
        db.kb_update_item(kid, progress="图片识别中 1/1 页")
        return parse_image.transcribe(src)
    except VlmUnavailable as e:
        if vlm.vlm_available():
            warnings.append(f"图片未识别：{e}")
        else:
            warnings.append("没有可用的图片识别模型（文档解析也未配置），图片未识别——可在设置中配置后重新识别，或直接在「信息」里手动填写")
        return None


def _fill_scanned_pages(kid: str, src: Path, result, warnings: list[str]) -> object:
    """扫描页处理：云端整本（文档级 API 无逐页接口，已配置优先）
    → 视觉模型逐页转写拼回页锚点（混合 PDF = pdf-mixed）→ 降级警示。"""
    if baidu_ocr.baidu_ocr_available():
        try:
            db.kb_update_item(kid, progress="云端识别中")
            cloud = baidu_ocr.parse_via_baidu(src)
            warnings.append("扫描版 PDF 已由云端文档解析（PaddleOCR-VL）整本识别，建议人工核对关键内容")
            return cloud
        except Exception as e:
            warnings.append(f"云端文档解析失败（{e}），回退图片模型逐页转写")

    tmp_dir = Path(tempfile.mkdtemp(prefix="kb-pages-"))
    try:
        from .. import vlm as vlm_mod

        pages = scanned(result)
        if len(pages) > _MAX_SCAN_PAGES:
            warnings.append(
                f"扫描页 {len(pages)} 页超出本地逐页转写预算（{_MAX_SCAN_PAGES}），"
                f"仅转写前 {_MAX_SCAN_PAGES} 页——建议在设置中配置云端文档解析整本识别"
            )
            pages = pages[:_MAX_SCAN_PAGES]
        md = result.md
        converted = 0
        for i, pno in enumerate(pages):
            png = tmp_dir / f"p{pno}.png"
            parse_pdf.render_page_png(src, pno, png)
            try:
                text = vlm_mod.vlm_read_image(png, _PAGE_PROMPT)
            except VlmUnavailable:
                raise
            db.kb_update_item(kid, progress=f"图片识别中 {i + 1}/{len(pages)} 页")
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
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def scanned(result) -> list[int]:
    return result.info.get("scanned_pages") or []


# 本地注册表不收、云端文档解析专属的格式（.docx/pdf/txt/md 恒走本地）
_CLOUD_ONLY_EXTS = {".doc"}

# 本地逐页 VL 转写的扫描页数预算
_MAX_SCAN_PAGES = 60

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


def statement_segment(statement: str) -> dict | None:
    """内容说明 → 检索段（§statement；语义密度最高的可检索单元）。"""
    text = (statement or "").strip()
    if len(text) < 20:
        return None
    return {
        "section_path": "§statement",
        "line_start": None, "line_end": None, "page_start": None,
        "raw": text,
    }


def questions_segment(questions) -> dict | None:
    """检索问题 → 检索段（§questions；「用户会怎么问」的字面检索入口）。"""
    qs = [q.strip() for q in (questions or []) if isinstance(q, str) and q.strip()]
    if not qs:
        return None
    return {
        "section_path": "§questions",
        "line_start": None, "line_end": None, "page_start": None,
        "raw": "\n".join(qs),
    }


def reindex_item(kid: str) -> None:
    """重建条目检索段（唯一重建入口）：outline 段 + 内容说明段（§statement）+
    检索问题段（§questions）+ 已确认元数据合成段。写作素材在独立素材库
    （materials_lib），知识库无章节块。"""
    item = db.kb_get_item(kid)
    if not item:
        return
    segs: list[dict] = []
    md_path, outline_path, _, _ = store.kb_parse_paths(item["file_name"])
    if md_path.is_file():
        md_text = md_path.read_text(encoding="utf-8")
        outline = json.loads(outline_path.read_text(encoding="utf-8")) if outline_path.is_file() else []
        segs = segments_from(md_text, outline)

    # 内容说明段 + 检索问题段（business 版优先）
    basis = _loads(item.get("business_metadata")) or _loads(item.get("suggested_metadata"))
    if basis:
        st = statement_segment(basis.get("statement"))
        if st:
            segs.append(st)
        qs = questions_segment(basis.get("questions"))
        if qs:
            segs.append(qs)

    # 确认版字段段（人工填的字段也要可检索）
    biz = _loads(item.get("business_metadata"))
    if biz:
        pairs = []
        for k, v in (biz.get("fields") or {}).items():
            pairs.append(f"{FIELD_LABELS.get(k, k)}：{v.get('value') if isinstance(v, dict) else v}")
        for k, v in (biz.get("extra") or {}).items():
            pairs.append(f"{FIELD_LABELS.get(k, k)}：{v.get('value') if isinstance(v, dict) else v}")
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
    """三合一抽取（类型/内容说明/锚点字段）→ suggested_metadata + 回文核对。

    两主人模型：机器守 suggested（每次抽取收尾跑锚点回文核对，全过自动确认、
    有败留待确认点名原因）；人守 business（人工确认/编辑过的条目核对只更新
    展示，永不改确认状态，doc_type 也不回写——既有语义）。自动确认的 business
    副本带 confirmed_by="auto" 标记，人工保存后标记消失即转为人工所有。
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
        suggested = extract_mod.run_extract(api_key, profile, item["file_name"], md_text)
    except Exception as e:
        db.kb_update_item(kid, extract_status="failed", error=f"信息抽取失败：{e}")
        return
    if not suggested:
        db.kb_update_item(kid, extract_status="failed", error="信息抽取返回无法解析")
        return

    cur = db.kb_get_item(kid) or {}
    check = autocheck.run_anchor_check(
        suggested, md_text, get_type(suggested.get("doc_type")),
    )
    check_json = json.dumps(check, ensure_ascii=False)
    human_owned = (
        cur.get("review_status") == "confirmed"
        and (autocheck.loads_business(cur.get("business_metadata")) or {}).get("confirmed_by") != "auto"
    )
    if human_owned:
        # 人工所有：维持现状（只更新 suggested），核对结果仅作展示
        db.kb_update_item(
            kid,
            extract_status="done",
            suggested_metadata=json.dumps(suggested, ensure_ascii=False),
            check_result=check_json,
            error=None,
        )
        return
    if check["status"] == "pass":
        db.kb_update_item(
            kid,
            extract_status="done",
            suggested_metadata=json.dumps(suggested, ensure_ascii=False),
            doc_type=suggested.get("doc_type") if get_type(suggested.get("doc_type")) else "other",
            review_status="confirmed",
            business_metadata=json.dumps(autocheck.auto_business(suggested), ensure_ascii=False),
            check_result=check_json,
            error=None,
        )
    else:
        # 有败：留待确认并清掉旧自动副本（防陈旧盖章；显示回落 suggested）
        db.kb_update_item(
            kid,
            extract_status="done",
            suggested_metadata=json.dumps(suggested, ensure_ascii=False),
            doc_type=suggested.get("doc_type") if get_type(suggested.get("doc_type")) else "other",
            review_status="pending_review",
            business_metadata=None,
            check_result=check_json,
            error=None,
        )


def rebuild_kb_index() -> int:
    """启动重建：全部条目重切索引（磁盘 md/materials.json 权威）。"""
    items = db.kb_list_items()
    for it in items:
        if it["parse_status"] == "ready":
            reindex_item(it["id"])
    return len(items)
