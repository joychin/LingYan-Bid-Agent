"""内容角色（命中级，v3 章节块模型）：由「来源类型 + 命中形态」动态派生，不预存。

角色表（2026-09-04 章节块重构）：
- fact-verified      fact 类文件命中 → 可作公司事实（带确认状态/时效）
- fact-candidate     写法类文件中章节标题命中业绩词表的段（启发式，会漏会错；
                     漏的走 unknown+纪律兜底）
- writing-reference  章节块命中（写法参考/拷贝修订候选——章节块本身就是章）、
                     写法类普通段
- unknown            未判定（标注来源类型，可信度判断交 skill 纪律）
"""

from __future__ import annotations

import json

from .types import ROLE_FACT, get_type, type_name

# 章节标题启发式词表：标题链命中即视为业绩/事实性章节（fact-candidate）
PERFORMANCE_WORDS: tuple[str, ...] = (
    "业绩", "案例", "成功案例", "客户", "合同", "验收", "项目经验", "实施案例", "应用案例",
)

ROLE_LABELS: dict[str, str] = {
    "fact-verified": "公司事实",
    "fact-candidate": "业绩候选·须核对",
    "writing-reference": "写法参考",
    "unknown": "未判定",
}


def item_meta(item: dict, code: str) -> str | None:
    """business（优先）/suggested 元数据字段值。"""
    for key in ("business_metadata", "suggested_metadata"):
        raw = item.get(key)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = None
        v = (raw or {}).get("fields", {}).get(code) if isinstance(raw, dict) else None
        if isinstance(v, dict):
            v = v.get("value")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def statement_of(item: dict) -> str:
    for key in ("business_metadata", "suggested_metadata"):
        raw = item.get(key)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = None
        if isinstance(raw, dict) and isinstance(raw.get("statement"), str) and raw["statement"].strip():
            return raw["statement"].strip()
    return ""


def derive_role(item: dict, hit: dict) -> str:
    t = get_type(item.get("doc_type"))
    role = t.role if t else ROLE_FACT
    if role == ROLE_FACT:
        return "fact-verified"
    # 写法类普通段：标题命中业绩词表 → 事实候选（启发式）
    section = hit.get("section_path") or ""
    if any(w in section for w in PERFORMANCE_WORDS):
        return "fact-candidate"
    return "writing-reference"


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def hit_header(item: dict, hit: dict, role: str, *, review_note: str = "", freshness: list[str] | None = None) -> str:
    """统一命中头：角色｜类型｜确认状态｜时效。"""
    bits = [role_label(role), type_name(item.get("doc_type"))]
    if review_note:
        bits.append(review_note)
    if freshness:
        bits.append("·".join(freshness))
    return "｜".join(bits)
