"""时间边界（治理内部化）：从元数据字段计算资料新鲜度警示，替代人工审核周期。

行业靠 owner/审核周期维持库不过时（约 15% 内容每季度过时）；本产品用户零维护，
改为系统算——入库时 LLM 抽时间字段（valid_until/sign_date/doc_date/period 已在
字段模板），本模块动态计算过期/临期/陈旧警示，检索返回与前端展示共用。

口径宁缺毋滥：日期解析失败（含「长期/永久」）不产生警示。
"""

from __future__ import annotations

import json
import re
from datetime import date

# 距到期多少天内提示「即将到期」
_EXPIRING_DAYS = 90
# 落款/签订距今超过多少年提示「资料较旧」
_STALE_YEARS = 3

_PERMANENT = ("长期", "永久", "无期", "长期有效")
# 2023-05-01 / 2023/5/1 / 2023年5月1日（月日可单位数）
_DATE_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})[日号]?")
_YEAR_RE = re.compile(r"(\d{4})")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if any(p in text for p in _PERMANENT):
        return None
    m = _DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    m = _YEAR_RE.search(str(value))
    return int(m.group(1)) if m else None


def _field(basis: dict | None, code: str) -> str | None:
    if not basis:
        return None
    fields = basis.get("fields") or {}
    v = fields.get(code)
    if isinstance(v, dict):
        v = v.get("value")
    return str(v).strip() if isinstance(v, str) and v.strip() else None


def freshness_warnings(item: dict, *, today: date | None = None) -> list[dict]:
    """条目 → 警示列表 [{kind: expired|expiring|stale, label}]。

    优先 business_metadata（人工确认真值），无则 suggested_metadata；两列兼容
    已反序列化 dict（_item_out 路径）与原始 JSON 字符串（db 行路径）。
    """
    basis = None
    for key in ("business_metadata", "suggested_metadata"):
        v = item.get(key)
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                v = None
        if isinstance(v, dict) and (v.get("fields") or v.get("extra")):
            basis = v
            break
    if basis is None:
        return []

    today = today or date.today()
    out: list[dict] = []

    valid_until = _parse_date(_field(basis, "valid_until"))
    if valid_until is not None:
        if valid_until < today:
            out.append({"kind": "expired", "label": f"已过期（{valid_until.isoformat()}）"})
        elif (valid_until - today).days <= _EXPIRING_DAYS:
            out.append({"kind": "expiring", "label": f"即将到期（{valid_until.isoformat()}）"})

    stale_year: int | None = None
    for code in ("sign_date", "doc_date"):
        d = _parse_date(_field(basis, code))
        if d is not None:
            stale_year = d.year
            break
    if stale_year is None:
        stale_year = _parse_year(_field(basis, "period"))
    if stale_year is not None and stale_year <= today.year - _STALE_YEARS:
        out.append({"kind": "stale", "label": f"资料较旧（{stale_year} 年）"})

    return out
