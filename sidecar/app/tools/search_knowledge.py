"""知识库检索工具 ×2（素材分离模型：事实查知识库、写法查素材库）。

- search_company_assets（问事实：我们有什么/做过什么）：查知识库（kb_items），
  fact 类命中排前、写法类文件中章节标题命中业绩词表的段降级附带并标
  「业绩候选·须核对」。附关联证明材料（项目名匹配 fact 类条目）。
- search_references（问写法/拷贝）：查**写作素材库**（用户在目录树手工勾选
  建的块：内容+用户备注都进检索——备注是用户亲手写的语义索引）。命中带块
  信息+多区间行号+拷贝修订指引；骨架=命中文件的块清单（用户自建的能力清单）。

共同契约：统一命中头 + 稳定引用键 + 末尾 [evidence] JSON 行（含 role）。
工具失败返回 "[检索失败]" 文案不抛异常打崩 run。
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from .. import db
from ..knowledge import fts, store
from ..knowledge.freshness import freshness_warnings
from ..knowledge.roles import derive_role, hit_header, item_meta, statement_of
from ..knowledge.types import role_of

_SNIPPET_CHARS = 300


def _excerpt(item: dict, line_start, line_end, *, section_path=None) -> str:
    # 说明段行号为空——摘录直接取 statement 原文（AI 整理语义入口）
    if section_path == "§statement":
        return statement_of(item)[:_SNIPPET_CHARS]
    md_path, _, _, _ = store.kb_parse_paths(item["file_name"])
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


def _mt_block_excerpt(file_name: str, ranges: list, limit: int = _SNIPPET_CHARS) -> str:
    """素材块摘录：按区间从素材文件 md 拼接。"""
    from ..knowledge import materials_lib as mlib

    md_path, _, _ = mlib.mt_parse_paths(file_name)
    if not md_path.is_file():
        return ""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    parts = []
    for r in ranges or []:
        if not (isinstance(r, (list, tuple)) and len(r) == 2):
            continue
        s, e = max(1, int(r[0])), min(len(lines), int(r[1]))
        chunk = [ln for ln in lines[s - 1 : e] if ln.strip() and not ln.strip().startswith("<!--")]
        text = "\n".join(chunk)
        if text:
            parts.append(text)
    out = "\n".join(parts)
    return out[:limit] + ("…" if len(out) > limit else "")


def _mt_ranges_str(ranges: list) -> str:
    bits = []
    for r in ranges or []:
        if isinstance(r, (list, tuple)) and len(r) == 2:
            s, e = int(r[0]), int(r[1])
            bits.append(f"L{s}-L{e}" if e != s else f"L{s}")
    return "、".join(bits)


def _loc(h: dict) -> str:
    line_start, line_end = h.get("line_start"), h.get("line_end")
    loc = ""
    if line_start is not None:
        loc = f"，行号 L{line_start}" + (f"-L{line_end}" if line_end and line_end != line_start else "")
    if h.get("page_start") is not None:
        loc += f"，第 {h['page_start']} 页"
    return loc


def _fresh(item: dict) -> list[str]:
    return [w["label"] for w in freshness_warnings(item)]


def _search_all(query: str, limit: int) -> list[dict]:
    expr = fts.build_match_expr(query)
    if expr is None:
        raise ValueError("检索词为空或无有效关键词")
    return db.kb_search_segments(expr, limit=limit)


def _dedupe(hits: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for h in hits:
        key = f"{h['item_id']}:{h.get('material_id') or ''}:{h.get('line_start')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def _evidence_line(ev: list[dict]) -> str:
    return "[evidence] " + json.dumps({"items": ev}, ensure_ascii=False)


def _linked_evidence(candidate_item: dict, fact_items: dict[str, dict]) -> str:
    """业绩候选 → 按项目名匹配同库 fact 类条目（关联证明材料附注）。"""
    proj = item_meta(candidate_item, "project_name")
    if not proj or len(proj) < 4:
        return ""
    for it in fact_items.values():
        if role_of(it.get("doc_type")) != "writing" and item_meta(it, "project_name") == proj and it["id"] != candidate_item["id"]:
            return f"（关联证明材料：{it['file_name']}）"
    return ""


@tool
def search_company_assets(query: str, doc_type: str | None = None) -> str:
    """检索公司资料，回答"我们有什么/做过什么"（公司事实：资质证书、合同案例、人员证书、
    财务、业绩、公司介绍；以及历史标书中的业绩描述）。

    用途：写标书需要陈述公司资质、业绩、人员、财务等公司事实时先检索本库。
    Args:
        query: 检索词（如「ISO27001」「智慧园区 项目」「净资产」）
        doc_type: 可选，限定类型（qualification_certificate 资质证书 / contract_case 合同案例 /
                  personnel_certificate 人员证书 / acceptance_report 验收报告 / financial_report 财务 /
                  business_license 营业执照 / company_profile 公司介绍 / honor_ip 荣誉知产 / other 其他）

    Returns:
        命中列表（统一命中头：角色｜类型｜确认状态｜时效；行号区间、摘录、引用键）与
        精读指引。纪律：**来自历史标书的业绩描述可引用但须与合同/验收核对**；「拟投入
        N 人」「承诺 7×24」类是当年投标承诺，**不是公司现状事实**；数字一律重核；
        过期证书不得写为有效；标注「AI 整理」的说明段引用数字须回原文核对。
    """
    try:
        hits = _dedupe(_search_all(query, limit=32))
        items = {it["id"]: it for it in db.kb_list_items()}
        # 素材库段（item_id=mt_ 前缀）不属于知识库——items 过滤天然隔离
        hits = [h for h in hits if h["item_id"] in items]
        if doc_type:
            allowed = {kid for kid, it in items.items() if it.get("doc_type") == doc_type}
            typed = [h for h in hits if h["item_id"] in allowed]
            if typed:
                hits = typed
        if not hits:
            return (
                "[公司资料无命中] 换更通用的关键词再试（如把产品简称换成全称、把长句拆成核心词）；"
                "或该资料尚未上传——提示用户在知识库上传公司资料。"
            )

        # 角色派生 + 分层：fact-verified 排前 → fact-candidate → unknown；纯写法段排除
        ranked: list[tuple[int, dict, dict, str]] = []
        for h in hits:
            item = items[h["item_id"]]
            role = derive_role(item, h)
            if role == "writing-reference":
                continue  # 写法段对事实查询无意义
            order = {"fact-verified": 0, "fact-candidate": 1}.get(role, 2)
            ranked.append((order, h, item, role))
        ranked.sort(key=lambda x: x[0])
        hits_out = ranked[:8]
        if not hits_out:
            return "[公司资料无命中] 换更通用的关键词再试，或提示用户上传相关资料。"

        out = [f"[公司资料命中 {len(hits_out)} 条]（检索词：{query}）"]
        ev = []
        for _, h, item, role in hits_out:
            review = "" if item["review_status"] == "confirmed" else "（信息待确认）"
            header = hit_header(item, h, role, review_note=review.strip("（）") or "", freshness=_fresh(item))
            section = f"，章节「{h['section_path']}」" if h.get("section_path") and h["section_path"] != "§statement" else (
                "，内容说明" if h.get("section_path") == "§statement" else ""
            )
            ai_note = "（AI 整理·数字须回原文核对）" if h.get("section_path") == "§statement" else ""
            linked = _linked_evidence(item, items) if role == "fact-candidate" else ""
            key = f"kb:{item['id']}:s" if h.get("section_path") == "§statement" else f"kb:{item['id']}:L{h.get('line_start')}"
            out.append(
                f"- {item['file_name']}［{header}］{ai_note}{linked}{section}{_loc(h)}\n"
                f"  摘录：{_excerpt(item, h.get('line_start'), h.get('line_end'), section_path=h.get('section_path'))}\n"
                f"  引用键：{key}"
            )
            ev.append({
                "key": key, "file": item["file_name"], "hash": item["file_hash"], "role": role,
                "type": item.get("doc_type"),
                "lines": [h.get("line_start"), h.get("line_end")],
                "page": h.get("page_start"), "review": item["review_status"], "freshness": _fresh(item),
            })
        md_rel = Path("knowledge/parse") / Path(hits_out[0][2]["file_name"]).stem
        out.append(
            "精读指引：用 read_file 读 `knowledge/parse/<文件名去扩展名>/<原文件名>.md` 的对应行号区段"
            f"（如 {md_rel}/…），原件在 `knowledge/files/` 下。"
        )
        out.append(_evidence_line(ev))
        return "\n".join(out)
    except ValueError as e:
        return f"[检索失败] {e}"
    except Exception as e:
        return f"[检索失败] {type(e).__name__}: {e}"


def _mt_skeleton(fid: str, max_lines: int = 40) -> list[str]:
    """素材文件的块清单（用户自建的能力清单导航；骨架每项=可拷贝块）。"""
    f = db.mt_get_file(fid)
    if not f:
        return []
    blocks = db.mt_list_blocks(fid)
    out = []
    for b in blocks:
        out.append(f"- {b['title']}（{_mt_ranges_str(b.get('ranges'))}，约{b.get('chars') or 0:,}字）")
        if b.get("note"):
            out.append(f"  备注：{b['note']}")
        if len(out) >= max_lines:
            out.append(f"…（共 {len(blocks)} 个素材块，已截断）")
            break
    return out


@tool
def search_references(query: str) -> str:
    """检索写作素材，回答"这类内容怎么写/怎么组织"（用户从历史标书/范文中手工挑选的
    章节素材块，带用户备注——备注常含适用场景提示，是最可靠的挑选依据）。

    用途：写某类章节不知道怎么组织/怎么措辞时检索；本次需求与历史项目相似时，
    取章节块作为拷贝修订的初稿。**素材不是公司事实**——其中数字、工期、人数、
    承诺都是历史项目的，禁止直接沿用。
    Args:
        query: 检索词（如「运维服务方案」「表单设计器」「培训计划」——也会命中用户备注）

    Returns:
        素材块命中（标题+备注+来源文件+多区间行号+真实字数）与精读指引；命中文件
        附全部块清单（该来源文件的能力全景）。**拷贝素材后必须调用 check_name_residue
        扫描旧项目名/客户名残留（old_names 传来源文件名中的机构名）**。写正文节时
        docx 原件的块优先 docx_material_inject 按块 id 整体保真注入（元素级拷贝），
        纯文本参考才自行改写。
    """
    try:
        hits = _dedupe(_search_all(query, limit=24))
        # 只留素材库段（item_id=mt_ 前缀）——写法检索只查用户手工挑选的素材块
        hits = [h for h in hits if h["item_id"].startswith("mt_") and h.get("material_id")]
        if not hits:
            n_files = len(db.mt_list_files())
            return (
                "[写作素材无命中] 换更通用的关键词再试（也会命中素材备注）；"
                + (
                    f"素材库现有 {n_files} 份文件 {db.mt_count_blocks()} 个块。"
                    if n_files else "素材库还是空的——提示用户在「写作素材库」上传历史标书/范文并勾选章节。"
                )
            )
        files = {f["id"]: f for f in db.mt_list_files()}
        selected = hits[:8]
        blocks_by_id = {b["id"]: b for b in db.mt_list_blocks()}

        out = [
            f"[写作素材命中 {len(selected)} 条]（检索词：{query}）",
            "⚠ 素材仅供写法参考——其中数字、工期、承诺均须按本次招标重新核对，禁止直接沿用。",
        ]
        ev = []
        for h in selected:
            f = files.get(h["item_id"])
            b = blocks_by_id.get(h.get("material_id"))
            if not f or not b:
                continue
            key = f"mt:{f['id']}:b:{b['id']}"
            note = f"\n  备注：{b['note']}" if b.get("note") else ""
            out.append(
                f"- 《{b['title']}》［素材块·拷贝修订候选，约 {b.get('chars') or 0:,} 字，"
                f"区间 {_mt_ranges_str(b.get('ranges'))}］｜来源文件：{f['file_name']}{note}\n"
                f"  摘录：{_mt_block_excerpt(f['file_name'], b.get('ranges'))}\n"
                f"  引用键：{key}（拷贝后必须用 check_name_residue 扫旧名残留）"
            )
            ev.append({
                "key": key, "file": f["file_name"], "role": "writing-reference",
                "material": b["id"], "title": b["title"],
                "ranges": b.get("ranges"), "review": "user_curated",
            })
        # 块清单（该来源文件的能力全景——用户自建的挑选结果）
        seen_fids: dict[str, dict] = {}
        for h in selected:
            seen_fids.setdefault(h["item_id"], files[h["item_id"]])
        skel_blocks: list[str] = []
        for fid, f in list(seen_fids.items())[:3]:
            lines = _mt_skeleton(fid)
            if lines:
                skel_blocks.append(f"《{f['file_name']}》\n" + "\n".join(lines))
        if skel_blocks:
            out.append(
                "📋 该来源文件的素材块全景（用户手工挑选的能力清单；需要哪块按区间精读）：\n"
                + "\n".join(skel_blocks)
            )
        out.append(
            "精读指引：用 read_file 读 `materials/parse/<文件名去扩展名>/<原文件名>.md` 的对应行号区间"
            "（拷贝修订取块的全部区间）。写正文节时，docx 原件的块优先 docx_material_inject"
            " 按块 id 整体保真注入再定向修订（表格/图片/格式零转写）；非 docx 原件才按文本参考改写。"
        )
        out.append(_evidence_line(ev))
        return "\n".join(out)
    except ValueError as e:
        return f"[检索失败] {e}"
    except Exception as e:
        return f"[检索失败] {type(e).__name__}: {e}"
