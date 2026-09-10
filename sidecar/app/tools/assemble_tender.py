"""确定性组装工具：把目录中间产物组装为投标目录 Artifact（tender.directory）。

registry 构建 / 目录树与标注解析 / lineage 核对回收自 tender-toc skill 的
parse_toc.py（build 路径）；输入位置为技能产物布局（work/analysis + work/outline），
产物经 publish 管线发布（单一当前版本，重跑覆盖前自动留恢复点）。

机器输入的格式契约（tender-analysis / tender-outline 的产物必须遵守）：
- work/analysis/requirements-format.md：`## 二、必须有的章节` 与 `## 三、模板` 两张表
  （MAND/TPL registry，行序=编号）
- work/analysis/requirements-business.md：`| 需求 | 出处 |` 表（REQ registry，行序=编号）
- work/analysis/evaluation.md：`| 评分项 | 分值 | 评分要点 | 出处 |` 表（SCORE registry）
- work/outline/tender-response-docs.md：`# 响应文件：X` + scope + `## 目录` /
  `## 来源标注` / `## 目录说明`（可选顶部 `## 项目信息`）
各 analysis 文件在登记表之后的可选段（待澄清登记/coverage 声明/评标办法概述）
不参与行序编号；目录段中不符合列表格式的行会被静默跳过（探测警告见返回文案）。
"""

from __future__ import annotations

import json
import re
from typing import get_args

from langchain_core.tools import tool
from pydantic import ValidationError

from .. import publish, runctx
from ..artifact_store import work_dir
from ..config import workspace_dir
from ..contracts.tender_directory import NumberingScheme
from . import body_contract

CONTRACT_KEY = "tender.directory/tender-response-docs@1"

ID_RE = re.compile(r"^(MAND|REQ|SCORE|TPL)-\d+$")

_TREE_LINE_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")

# 登记表之后的可选段（允许表格/散文，不参与「行序=编号」的机器输入）；
# 各节 SKILL/references 的待澄清登记按 clarifications.md 是五列表格，不截掉会
# 被全文件扫描的 registry 构建器当成 REQ/SCORE/TPL 行收进登记表。
_OPTIONAL_SECTION_RE = re.compile(r"^##\s*(待澄清登记|coverage\s*声明|评标办法概述)\s*$")

DIR_NOTE_RE = re.compile(
    r"^(?P<title>.+?)\s*::\s*交付形态=(?P<mode>[^|]+?)\s*"
    r"\|\s*归位理由=(?P<reason>[^|]*?)\s*"
    r"\|\s*理由来源=(?P<rids>[^|]*?)\s*"
    r"\|\s*概述=(?P<summary>.*)$"
)


def _norm_id(i: str) -> str:
    """来源ID数字部分补零到两位（MAND-1 -> MAND-01），与 registry 键保持一致。"""
    return re.sub(r"(\d+)$", lambda m: m.group(1).zfill(2), i)


# ---------------------------------------------------------------------------
# registry 构建（回收自 parse_toc.py）
# ---------------------------------------------------------------------------
def _cut_optional_sections(md: str) -> str:
    """截掉登记表之后的可选段（待澄清登记/coverage 声明/评标办法概述）。

    这些段允许表格与散文，混进 registry 行序会产生幻影编号。
    """
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if _OPTIONAL_SECTION_RE.match(line.strip()):
            return "\n".join(lines[:i])
    return md


def _split_format_sections(md: str) -> dict[str, str]:
    sections = {"structure": "", "mandatory": "", "templates": ""}
    cur = None
    for line in md.splitlines():
        if line.startswith("## 一、"):
            cur = "structure"
        elif line.startswith("## 二、"):
            cur = "mandatory"
        elif line.startswith("## 三、"):
            cur = "templates"
        if cur is not None:
            sections[cur] += line + "\n"
    return sections


def _build_mand_tpl_registry(fmt_md: str) -> tuple[dict, dict]:
    sec = _split_format_sections(_cut_optional_sections(fmt_md))
    mand, nm = {}, 0
    for line in sec["mandatory"].splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or "---" in cells[0] or cells[0] in ("序号", "章节名称"):
            continue
        nm += 1
        src = cells[3] if len(cells) > 3 else (cells[-1] if len(cells) > 2 else "")
        mand[f"MAND-{nm:02d}"] = {"type": "招标文件规定", "text": cells[1], "出处": src}
    tpl, nt = {}, 0
    for line in sec["templates"].splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or "---" in cells[0] or cells[0] in ("序号", "模板名称"):
            continue
        nt += 1
        tpl[f"TPL-{nt:02d}"] = {"type": "模板", "text": cells[1], "出处": cells[-1] if len(cells) > 2 else ""}
    return mand, tpl


def _build_req_registry(biz_md: str) -> dict:
    reg, n = {}, 0
    for line in _cut_optional_sections(biz_md).splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("<!--") or "|" not in s:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        text = cells[0] if cells else ""
        rest = cells[1] if len(cells) > 1 else ""
        if not text or "---" in text or text in ("需求", "要求", "项目背景") or "出处" in text or "原文" in text:
            continue
        n += 1
        reg[f"REQ-{n:02d}"] = {"type": "需求", "text": text, "出处": rest}
    return reg


def _build_score_registry(eval_md: str) -> dict:
    reg, n = {}, 0
    for line in _cut_optional_sections(eval_md).splitlines():
        s = line.strip()
        if not s or "|" not in s or s.startswith("#") or s.startswith("<!--"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if not parts or not parts[0] or parts[0] in ("评分项", "评分标准") or "---" in parts[0]:
            continue
        n += 1
        reg[f"SCORE-{n:02d}"] = {
            "type": "评分点",
            "text": parts[0],
            "出处": parts[-1] if len(parts) > 1 else "",
        }
    return reg


# ---------------------------------------------------------------------------
# 目录树 / 标注 / 说明 解析（回收自 parse_toc.py）
# ---------------------------------------------------------------------------
def _parse_trailer(md: str) -> dict[str, list[str]]:
    """`## 来源标注` 段：`- 标题 :: ID[, ID]` → {标题: [ID]}"""
    result: dict[str, list[str]] = {}
    in_block = False
    for line in md.splitlines():
        if re.match(r"^#+\s*来源标注", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", line.strip()):
                break
            s = line.strip()
            if s.startswith(("-", "*")) and "::" in s:
                body = s.lstrip("-*").strip()
                title, _, ids = body.partition("::")
                title = title.strip()
                idlist = [_norm_id(x.strip()) for x in ids.split(",") if ID_RE.match(x.strip())]
                if title and idlist:
                    result.setdefault(title, [])
                    for i in idlist:
                        if i not in result[title]:
                            result[title].append(i)
    return result


def _parse_dir_notes(md: str) -> dict[str, dict]:
    """`## 目录说明` 段：交付形态/归位理由/理由来源/概述 → {标题: {...}}"""
    result: dict[str, dict] = {}
    in_block = False
    for line in md.splitlines():
        if re.match(r"^#+\s*目录说明", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", line.strip()):
                break
            s = line.strip()
            if s.startswith(("-", "*")):
                m = DIR_NOTE_RE.match(s.lstrip("-*").strip())
                if m:
                    title = m.group("title").strip()
                    rids = [_norm_id(x.strip()) for x in m.group("rids").split(",") if ID_RE.match(x.strip())]
                    if title:
                        result[title] = {
                            "delivery_mode": m.group("mode").strip(),
                            "placement_reason": m.group("reason").strip(),
                            "reason_source_ids": rids,
                            "brief_summary": m.group("summary").strip(),
                        }
    return result


def _md_to_tree(md: str) -> list[dict]:
    """无编号缩进列表 → 嵌套树；level 按树深度重赋（不依赖缩进宽度）。

    不匹配列表格式的行会被**静默跳过**（丢节点）——探测交给 _tree_skipped_lines。
    """
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(-1, root)]
    for line in md.splitlines():
        if not line.strip():
            continue
        m = _TREE_LINE_RE.match(line.rstrip())
        if not m:
            continue
        indent = len(m.group(1).replace("\t", "  "))
        level = indent // 2 + 1
        node = {"目录名称": m.group(2).strip(), "level": level, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((level, node["children"]))
    _assign_levels(root, 1)
    return root


def _assign_levels(nodes: list[dict], base: int) -> list[dict]:
    for n in nodes:
        n["level"] = base
        _assign_levels(n.get("children", []), base + 1)
    return nodes


def _tree_skipped_lines(dir_md: str) -> list[str]:
    """## 目录 段中非空但不符合 `- ` 列表格式的行（编号前缀/代码块围栏等）。

    这些行会被 _md_to_tree 静默跳过——即树格式红线违反的实际表现是丢节点，
    这里把它显式探测出来供组装警告。
    """
    return [
        s.strip()
        for s in (line.rstrip() for line in dir_md.splitlines())
        if s.strip() and not _TREE_LINE_RE.match(s)
    ]


def _source_type(rid: str) -> str:
    if rid.startswith("MAND"):
        return "招标文件规定"
    if rid.startswith("REQ"):
        return "需求"
    if rid.startswith("SCORE"):
        return "评分点"
    if rid.startswith("TPL"):
        return "模板"
    return "其他"


def _match_lineage(title: str, lineage_map: dict[str, list[str]]) -> tuple[list[str], str | None]:
    """返回（来源 ID 列表, 命中的标注标题）——标题用于孤儿标注探测。"""
    if title in lineage_map:
        return lineage_map[title], title
    for k, v in lineage_map.items():
        if k and (k in title or title in k):
            return v, k
    return [], None


def _attach_lineage(
    tree: list[dict],
    lineage_map: dict[str, list[str]],
    dir_notes: dict[str, dict] | None = None,
    consumed: set[str] | None = None,
) -> None:
    for node in tree:
        ids, key = _match_lineage(node["目录名称"], lineage_map)
        if key is not None and consumed is not None:
            consumed.add(key)
        node["来源"] = sorted({_source_type(i) for i in ids}) if ids else []
        node["来源位置"] = ids if ids else []
        if dir_notes:
            note = dir_notes.get(node["目录名称"]) or {}
            if note and consumed is not None:
                consumed.add(node["目录名称"])
            node["交付形态"] = note.get("delivery_mode", "")
            node["归位理由"] = note.get("placement_reason", "")
            node["理由来源"] = note.get("reason_source_ids", [])
            node["节点概述"] = note.get("brief_summary", "")
        _attach_lineage(node["children"], lineage_map, dir_notes, consumed)


def _fold_lineage(tree: list[dict]) -> tuple[list[dict], int]:
    """唯一承载折叠：同一条来源 ID 在祖先-后代链上只留最深节点（post-order，deepest-wins）。

    目录是正文生成的写作计划、按节点血缘分配任务，父子重复挂载=同一要求两级各写
    一遍（重复成文）。确定性结构规范化（与 _md_to_tree 重赋 level 同类）：
    三层链只留最深、兄弟同深全保留（真实需求）、仅浅层无更深保留；只动
    来源位置/来源，不碰目录说明的自辩字段。浅拷贝节点、不改入参（幂等）。

    Returns: (折叠后的新树, 移除总数)
    """
    removed_total = 0

    def _fold(nodes: list[dict]) -> tuple[list[dict], set[str]]:
        nonlocal removed_total
        out: list[dict] = []
        carried: set[str] = set()
        for node in nodes:
            children, child_carried = _fold(node.get("children") or [])
            own = set(node.get("来源位置") or [])
            overlap = own & child_carried
            if overlap:
                removed_total += len(overlap)
            kept = sorted(own - overlap)
            new_node = dict(node)
            new_node["children"] = children
            new_node["来源位置"] = kept
            new_node["来源"] = sorted({_source_type(i) for i in kept})
            out.append(new_node)
            carried |= child_carried | set(kept)
        return out, carried

    folded, _ = _fold(tree)
    return folded, removed_total


def _extract_section(body: str, name: str) -> str:
    out, in_block = [], False
    for line in body.splitlines():
        if re.match(rf"^##\s*{re.escape(name)}\s*$", line.strip()):
            in_block = True
            continue
        if in_block:
            if re.match(r"^##\s", line.strip()):
                break
            out.append(line)
    return "\n".join(out)


def _before_section(body: str, name: str) -> str:
    out = []
    for line in body.splitlines():
        if re.match(rf"^##\s*{re.escape(name)}\s*$", line.strip()):
            break
        out.append(line)
    return "\n".join(out)


def _parse_response_docs(md: str, warnings: list[str] | None = None) -> list[dict]:
    """每个顶层 `# 响应文件：XXX` 为一个响应文件，内含 ## 目录/## 来源标注/## 目录说明。

    warnings 传入列表时，收集两类探测结果（不拦停发布）：
    树格式违反被跳过的行、没挂到任何目录节点的孤儿标注。
    """
    segments: list[dict] = []
    cur: dict | None = None
    for line in md.splitlines():
        if re.match(r"^#\s(?![#])\s*(.+)$", line):
            if cur is not None:
                segments.append(cur)
            cur = {"header": line.strip(), "body": []}
        elif cur is not None:
            cur["body"].append(line)
    if cur is not None:
        segments.append(cur)
    docs = []
    for seg in segments:
        m = re.match(r"^#\s(?![#])\s*(?:响应文件[：:]\s*)?(.+?)\s*$", seg["header"])
        name = m.group(1).strip() if m else seg["header"].lstrip("#").strip()
        body = "\n".join(seg["body"])
        dir_sec = _extract_section(body, "目录")
        lineage = _parse_trailer(body)
        notes = _parse_dir_notes(body)
        tree = _md_to_tree(dir_sec) if dir_sec.strip() else []
        consumed: set[str] = set()
        _attach_lineage(tree, lineage, notes, consumed)
        if warnings is not None:
            skipped = _tree_skipped_lines(dir_sec)
            if skipped:
                warnings.append(
                    f"响应文件「{name}」目录树中有不符合 `- ` 列表格式的行（已被跳过=丢节点）："
                    + "；".join(skipped) + "；建议修复后重新组装"
                )
            orphan = [k for k in {*lineage, *notes} if k not in consumed]
            if orphan:
                warnings.append(
                    f"响应文件「{name}」的来源标注/目录说明未挂到任何目录节点"
                    f"（标题与目录树对不上，或对应树行被跳过）：" + "；".join(orphan)
                    + "；建议修复后重新组装"
                )
        scope = _before_section(body, "目录").strip()
        for prefix in ("scope：", "scope:", "Scope："):
            if scope.startswith(prefix):
                scope = scope[len(prefix):].strip()
                break
        docs.append({"name": name, "scope": scope, "directory": tree})
    return docs


def _parse_meta(md: str) -> dict[str, str]:
    """可选 `## 项目信息` 段（文件顶部二级标题）：`- 键：值` 或 `| 键 | 值 |`。"""
    meta: dict[str, str] = {}
    in_block = False
    for line in md.splitlines():
        s = line.strip()
        if re.match(r"^##\s*项目信息\s*$", s):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#+\s", s):
                break
            m = re.match(r"^[-*]\s*(.+?)[：:]\s*(.+)$", s)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
                continue
            if s.startswith("|") and "|" in s[1:]:
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) == 2 and cells[0] and "---" not in cells[0] and cells[0] not in ("键", "项目"):
                    meta[cells[0]] = cells[1]
    return meta


def _iter_nodes(tree: list[dict]):
    for n in tree:
        yield n
        yield from _iter_nodes(n.get("children", []))


# ---------------------------------------------------------------------------
# 工具主体
# ---------------------------------------------------------------------------
@tool
def assemble_tender() -> str:
    """组装投标目录并发布为 Artifact（tender.directory，任务内唯一当前版本）。

    读取当前任务 work/analysis/（requirements-format / requirements-business /
    evaluation 构建来源登记表 MAND/TPL/REQ/SCORE）与 work/outline/tender-response-docs.md
    （响应文件 + 目录树 + 来源标注 + 目录说明），做 lineage 完整性核对
    （unused/dangling）后发布。悬空 ID 会发布但给出警告，应修复后重新组装。
    """
    try:
        ctx = runctx.current_run()
        task_id = ctx.task_id if ctx else None
        if not task_id:
            return "[组装失败] 缺少任务上下文：组装输入与 JSON 副本都在当前任务的 work/ 目录下"
        out_root = work_dir(task_id)
        inputs = {
            "work/analysis/requirements-format.md": out_root / "analysis" / "requirements-format.md",
            "work/analysis/requirements-business.md": out_root / "analysis" / "requirements-business.md",
            "work/analysis/evaluation.md": out_root / "analysis" / "evaluation.md",
            "work/outline/tender-response-docs.md": out_root / "outline" / "tender-response-docs.md",
        }
        missing = [k for k, p in inputs.items() if not p.is_file()]
        if missing:
            return (
                "[组装失败] 缺少上游产物：\n  " + "\n  ".join(missing)
                + "\n  请先由 tender-analysis / tender-outline 技能产出这些文件再组装。"
            )

        fmt_md = inputs["work/analysis/requirements-format.md"].read_text(encoding="utf-8")
        biz_md = inputs["work/analysis/requirements-business.md"].read_text(encoding="utf-8")
        eval_md = inputs["work/analysis/evaluation.md"].read_text(encoding="utf-8")
        outline_md = inputs["work/outline/tender-response-docs.md"].read_text(encoding="utf-8")

        mand_reg, tpl_reg = _build_mand_tpl_registry(fmt_md)
        req_reg = _build_req_registry(biz_md)
        score_reg = _build_score_registry(eval_md)
        registry: dict = {}
        for d in (mand_reg, tpl_reg, req_reg, score_reg):
            registry.update(d)

        outline_warnings: list[str] = []
        docs = _parse_response_docs(outline_md, outline_warnings)
        meta = _parse_meta(outline_md)

        # 唯一承载折叠：父子链重复挂载的来源 ID 收敛到最深节点（正文按节点血缘
        # 分配写作任务，重复挂载=重复成文）；只规范发布内容，源文件不动
        fold_count = 0
        for d in docs:
            d["directory"], n = _fold_lineage(d["directory"])
            fold_count += n

        referenced: set[str] = set()
        for d in docs:
            for n in _iter_nodes(d["directory"]):
                referenced.update(n.get("来源位置", []) or [])
        unused_ids = sorted(k for k in registry if k not in referenced)
        dangling_ids = sorted(i for i in referenced if i not in registry)

        warnings: list[str] = list(outline_warnings)
        if not docs or all(not d["directory"] for d in docs):
            warnings.append("未解析出任何响应文件目录，请检查 work/outline/tender-response-docs.md 格式")
        content: dict = {
            "response_documents": docs,
            "registry": registry,
            "meta": meta,
            "lineage_check": {"unused_ids": unused_ids, "dangling_ids": dangling_ids},
        }
        # 章节编号格式透传（2026-09-10 review）：numbering 唯一写入点是前端目录
        # 编辑器，重组装不带上会把用户选的格式静默清掉、下次合册回落 chapter。
        # 旧产物无此键或值不合法（contract Literal）→ 不带，缺省语义不变
        _, prev_content, _ = body_contract.load_directory(task_id)
        if isinstance(prev_content, dict):
            prev_numbering = prev_content.get("numbering")
            if prev_numbering in get_args(NumberingScheme):
                content["numbering"] = prev_numbering
        if warnings:
            content["warning"] = "\n".join(warnings)

        total = sum(1 for d in docs for _ in _iter_nodes(d["directory"]))
        json_path = out_root / "outline" / "tender-response-docs.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = publish.publish_artifact(
            CONTRACT_KEY,
            content,
            display_name=None,
            source={
                "skill": "tender-outline",
                "thread_id": ctx.conversation_id if ctx else None,
                "run_id": ctx.run_id if ctx else None,
            },
            task_id=task_id,
            conversation_id=ctx.conversation_id if ctx else None,
        )

        parts = [
            f"[组装发布成功] 投标目录（{manifest['artifact_id']}）："
            f"响应文件 {len(docs)} 个 / 目录节点 {total} 个 / "
            f"来源登记 MAND={len(mand_reg)} TPL={len(tpl_reg)} REQ={len(req_reg)} SCORE={len(score_reg)}",
        ]
        if fold_count:
            parts.append(
                f"已按最深承载折叠 {fold_count} 处父子重复血缘（父级无需重复标注子级已答要求）"
            )
        parts.extend(f"⚠️ {w}" for w in warnings)
        parts.extend(
            [
                f"JSON 副本：{out_root.relative_to(workspace_dir())}/outline/tender-response-docs.json",
                "已发布为投标目录成果（任务内唯一，后续阶段经 read_artifact 消费）。",
            ]
        )
        if dangling_ids:
            parts.append(
                f"⚠️ 悬空来源ID（被引用但登记表不存在，多为清单行序漂移或编号拼写错误）：{dangling_ids}；"
                "建议修正后重新组装发布"
            )
        if unused_ids:
            parts.append(
                f"⚠️ 未被任何目录节点引用的来源ID：{unused_ids}；逐条处置——能归位的修订"
                "目录后重新组装，确属无需对应章节的（如扣分项、后续轮次才出现的最终报价）"
                "必须在最终回复向用户点名列出并各给一句处置建议，不得只字不提"
            )
        return "\n".join(parts)
    except (publish.PublishError, ValidationError) as e:
        return f"[组装失败] 发布校验未通过：{e}"
    except Exception as e:
        return f"[组装失败] {type(e).__name__}: {e}"
