"""知识库检索工具：FTS5（jieba 两侧同源分词）→ 命中区段 + 行号定位。

返回每条命中的文件名/类型/章节路径/行号区间/原文摘录，并引导模型用 read_file
按行号精读（knowledge/ 在 workspace 内，agent 文件工具天然可读）。
空结果给换词建议；工具失败返回 "[检索失败]" 文案（不抛异常打崩 run）。
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from .. import db
from ..knowledge import fts, store
from ..knowledge.types import type_name

_SNIPPET_CHARS = 300
_MD_NAME_HINT_MAX = 12


def _excerpt(item: dict, line_start, line_end) -> str:
    md_path, _, _ = store.kb_parse_paths(item["file_name"])
    if not md_path.is_file():
        return ""
    try:
        lines = md_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    if line_start is None:
        chunk = lines[:20]
    else:
        s = max(1, line_start) - 1
        e = min(len(lines), line_end or line_start)
        chunk = lines[s:e]
    text = "\n".join(ln for ln in chunk if ln.strip() and not ln.strip().startswith("<!--"))
    return text[:_SNIPPET_CHARS] + ("…" if len(text) > _SNIPPET_CHARS else "")


@tool
def search_knowledge(query: str, doc_type: str | None = None) -> str:
    """检索公司知识库（跨任务共享的公司资料：资质证书、合同案例、人员证书、公司介绍等）。

    用途：写标书需要公司资质/案例/证书/介绍等内容时先检索本库定位资料。
    Args:
        query: 检索词（公司资料里的关键词，如「ISO27001」「教育行业 案例」「审计报告 2023」）
        doc_type: 可选，限定类型（business_license 营业执照 / qualification_certificate 资质证书 /
                  personnel_certificate 人员证书 / contract_case 合同案例 / acceptance_report 验收报告 /
                  financial_report 财务审计 / company_profile 公司介绍 / technical_doc 技术方案 /
                  honor_ip 荣誉知产 / other 其他）

    Returns:
        命中列表（文件名、类型、章节、行号区间、原文摘录）与精读指引；无命中给换词建议。
    """
    try:
        expr = fts.build_match_expr(query)
        if expr is None:
            return "[检索失败] 检索词为空或无有效关键词"
        hits = db.kb_search_segments(expr, limit=8)
        if doc_type:
            allowed = {it["id"] for it in db.kb_list_items(doc_type=doc_type)}
            typed = [h for h in hits if h["item_id"] in allowed]
            # 类型过滤后无命中但文本有命中：退回未过滤结果（误召回 > 漏召回），附提示
            if not typed and hits:
                type_note = f"（指定类型 {doc_type} 无命中，以下为不限类型的结果）"
            else:
                hits = typed
                type_note = ""
        else:
            type_note = ""
        if not hits:
            return (
                "[知识库无命中] 换更通用的关键词再试（如把产品简称换成全称、把长句拆成核心词）；"
                "或该资料尚未上传——提示用户在知识库页上传公司资料。"
            )

        items = {it["id"]: it for it in db.kb_list_items()}
        out = [f"[知识库命中 {len(hits)} 条]（检索词：{query}）{type_note}"]
        seen: set[str] = set()
        for h in hits:
            item = items.get(h["item_id"])
            if not item:
                continue
            key = f"{h['item_id']}:{h.get('line_start')}"
            if key in seen:
                continue
            seen.add(key)
            line_start, line_end = h.get("line_start"), h.get("line_end")
            loc = ""
            if line_start is not None:
                loc = f"，行号 L{line_start}" + (
                    f"-L{line_end}" if line_end and line_end != line_start else ""
                )
            if h.get("page_start") is not None:
                loc += f"，第 {h['page_start']} 页"
            section = f"，章节「{h['section_path']}」" if h.get("section_path") else ""
            review = "" if item["review_status"] == "confirmed" else "（信息待确认）"
            excerpt = _excerpt(item, line_start, line_end)
            out.append(
                f"- {item['file_name']}［{type_name(item.get('doc_type'))}{review}］{section}{loc}\n"
                f"  摘录：{excerpt}"
            )
        md_rel = Path("knowledge/parse") / Path(items[hits[0]["item_id"]]["file_name"]).stem
        out.append(
            f"精读指引：用 read_file 读 `knowledge/parse/<文件名去扩展名>/<原文件名>.md` 的对应行号区段"
            f"（如 {md_rel}/…），原件在 `knowledge/files/` 下。"
        )
        return "\n".join(out)
    except Exception as e:
        return f"[检索失败] {type(e).__name__}: {e}"
