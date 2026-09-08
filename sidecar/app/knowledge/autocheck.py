"""锚点回文核对（程序机械层，2026-09-08 设计拍板）。

LLM 抽出的锚点字段回解析原文验证——两主人模型：
- 机器守 suggested：每次抽取收尾跑核对，全过自动确认（business 副本带
  confirmed_by="auto" 标记）、有败留待确认并点名原因；
- 人守 business：人工确认/编辑过的条目（business 无 auto 标记）核对只更新
  展示，永不改确认状态。
不做 LLM 自报置信度（无机制数字）；核对过 ≠ 语义对（日期语义错位抓不住），
语义正确性归检索纪律层（数字须回原文核对）。
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata

from .. import db
from . import store
from .types import FIELD_LABELS, ROLE_FACT, get_type

logger = logging.getLogger(__name__)

_TEXT_FIELDS = ("project_name", "client")
_TIME_FIELDS = ("valid_from", "valid_until", "sign_date", "doc_date")

# 值侧日期解析：年[-/.年]月([-/.月]日?)，日可缺（落款常只到月）
_DATE_RE = re.compile(r"((?:19|20)\d{2})[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?")


def _norm(s: str) -> str:
    """归一化：NFKC（全角→半角）+ 去全部空白。值与 md 同口径比对。"""
    return "".join(unicodedata.normalize("NFKC", s or "").split())


def _parse_date(value: str) -> tuple[int, int, int | None] | None:
    m = _DATE_RE.search(_norm(value))
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    day = int(m.group(3)) if m.group(3) else None
    if not 1 <= mo <= 12 or (day is not None and not 1 <= day <= 31):
        return None
    return (y, mo, day)


def _date_variants(d: tuple[int, int, int | None]) -> list[str]:
    """同一日期在原文里的常见印法（归一化后子串命中任一即算找到）。"""
    y, mo, day = d
    out: list[str] = []
    if day is not None:
        for dd in ({str(day), f"{day:02d}"} if day < 10 else {str(day)}):
            for mm in (str(mo), f"{mo:02d}"):
                out += [f"{y}-{mm}-{dd}", f"{y}.{mm}.{dd}", f"{y}/{mm}/{dd}"]
            out.append(f"{y}年{mo}月{day}日")
    for mm in (str(mo), f"{mo:02d}"):
        out += [f"{y}-{mm}", f"{y}.{mm}", f"{y}/{mm}"]
    out.append(f"{y}年{mo}月")
    return out


def _item(field: str, label: str, ok: bool, detail: str) -> dict:
    return {"field": field, "label": label, "ok": ok, "detail": detail}


def run_anchor_check(suggested: dict, md_text: str, tdef) -> dict:
    """锚点回文核对（纯函数）：身份/时间锚点回原文命中 + 日期一致性 + 事实类零锚点。"""
    results: list[dict] = []
    norm_md = _norm(md_text or "")
    fields = suggested.get("fields") if isinstance(suggested.get("fields"), dict) else {}

    def value_of(code: str) -> str:
        v = fields.get(code)
        val = v.get("value") if isinstance(v, dict) else None
        return val.strip() if isinstance(val, str) else ""

    parsed: dict[str, tuple[int, int, int | None]] = {}
    for code in _TIME_FIELDS:
        val = value_of(code)
        if not val:
            continue
        label = FIELD_LABELS.get(code, code)
        d = _parse_date(val)
        if d is None:
            results.append(_item(code, label, False, "日期格式无法解析，请核对"))
            continue
        parsed[code] = d
        if any(v in norm_md for v in _date_variants(d)):
            results.append(_item(code, label, True, "原文命中"))
        else:
            results.append(_item(code, label, False, "未在原文找到该日期——疑似抽取有误，请核对"))

    val = value_of("period")
    if val:
        m = re.search(r"(?:19|20)\d{2}", val)
        if not m:
            results.append(_item("period", FIELD_LABELS["period"], False, "年度格式无法解析，请核对"))
        elif m.group(0) in norm_md:
            results.append(_item("period", FIELD_LABELS["period"], True, "原文命中"))
        else:
            results.append(_item("period", FIELD_LABELS["period"], False, "未在原文找到该年份——疑似抽取有误，请核对"))

    for code in _TEXT_FIELDS:
        val = _norm(value_of(code))
        if not val:
            continue
        label = FIELD_LABELS.get(code, code)
        if val in norm_md:
            results.append(_item(code, label, True, "原文命中"))
        else:
            results.append(_item(code, label, False, "未在原文找到该名称——疑似抽取编造，请核对"))

    vf, vu = parsed.get("valid_from"), parsed.get("valid_until")
    if vf and vu and vf[2] is not None and vu[2] is not None and vu < vf:
        results.append(_item("_consistency", "有效期自 / 至", False, "有效期至早于有效期自，请核对"))

    has_time = bool(parsed) or value_of("period")
    if tdef and tdef.role == ROLE_FACT and tdef.time_fields and not has_time:
        labels = "、".join(FIELD_LABELS.get(c, c) for c in tdef.time_fields)
        results.append(_item(
            "_anchors", "时间锚点", False,
            f"未识别到时间锚点（该类型应含 {labels}）——时效计算将不可用，请补填",
        ))

    ok = all(r["ok"] for r in results) if results else True
    return {"status": "pass" if ok else "fail", "results": results}


def auto_business(suggested: dict) -> dict:
    """自动确认的 business 副本：suggested 整体 + 来源标记（人工编辑/确认后标记消失）。"""
    biz = dict(suggested)
    biz["confirmed_by"] = "auto"
    return biz


def loads_business(raw) -> dict | None:
    """business_metadata 列 → dict（None/坏 JSON 安全；人工/自动所有判定共用）。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def autocheck_sweep() -> tuple[int, int, int]:
    """启动回扫（main.py lifespan，rebuild_kb_index 之前调用）：存量待确认且
    无人工 business、抽取已完成的条目补跑核对——欠账清单当场收敛为可疑清单。
    幂等（确认后不再命中范围）、无 LLM；检索段由随后的全量重建统一收口。"""
    checked = confirmed = failed = 0
    for item in db.kb_list_items():
        if item["review_status"] != "pending_review" or item["extract_status"] != "done":
            continue
        if item.get("check_result"):
            continue  # 已核对过（败者留人工/重触发，不反复扫）
        if item.get("business_metadata"):
            continue  # 人工确认过，不碰
        suggested = loads_business(item.get("suggested_metadata"))
        if not suggested:
            continue
        md_path, _, _, _ = store.kb_parse_paths(item["file_name"])
        if not md_path.is_file():
            continue
        check = run_anchor_check(
            suggested, md_path.read_text(encoding="utf-8"),
            get_type(suggested.get("doc_type")) or get_type(item.get("doc_type")),
        )
        checked += 1
        if check["status"] == "pass":
            db.kb_update_item(
                item["id"],
                review_status="confirmed",
                business_metadata=json.dumps(auto_business(suggested), ensure_ascii=False),
                check_result=json.dumps(check, ensure_ascii=False),
            )
            confirmed += 1
        else:
            db.kb_update_item(item["id"], check_result=json.dumps(check, ensure_ascii=False))
            failed += 1
    logger.info("知识库回扫：%d 条核对，%d 条自动确认，%d 条留待确认", checked, confirmed, failed)
    return checked, confirmed, failed
