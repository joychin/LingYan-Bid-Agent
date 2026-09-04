"""tender-analysis 产物机器校验工具（提示不是门禁：逐条给修复写法，不阻塞流程）。

校验契约（真值 = tender-analysis SKILL.md 输出约定 + 引用键纪律）：
- coverage：七节必有「## coverage 声明」段（structure 允许「四、」序号前缀），段内含
  「已检查：」与「未检查：」；disqualification 另必有「反查词表：」；clarifications
  不要求 coverage（它是汇总清单，用「## 状态」段）
- 出处列（节→列名）：structure / requirements-qualification / requirements-submission /
  disqualification / evaluation =「出处」；requirements-business =
  「出处（章/节/附件编号）」（第 2 列，assemble 的 REQ 登记表位置）；requirements-format =
  「原文出处线索」；clarifications 无出处列
- 引用键三层：①段首锚定——出处段以「同文件 」或来源文件名开头，「/」分隔段继承前段锚、
  「；」分隔段各自独立锚；②文件名 ∈ sources.json 已确认来源集合；③L 行号 ≤ 该来源
  解析 md 的总行数（引用无解析产物的文件=违规，降级文件不可引用）
"""

from __future__ import annotations

import json
import re

from langchain_core.tools import tool

from .. import runctx
from ..artifact_store import work_dir

# 八件清单（与 check_pipeline 一致；本工具按文件自己发现，这里用于识别未识别文件）
_SECTIONS = (
    "structure",
    "requirements-qualification",
    "requirements-submission",
    "requirements-business",
    "requirements-format",
    "disqualification",
    "evaluation",
    "clarifications",
)

# 需 coverage 声明的七节（clarifications 豁免）
_NEED_COVERAGE = set(_SECTIONS) - {"clarifications"}

# 节 → 出处列名（表格头精确匹配；business 同时接受简写「出处」——assemble 的 REQ
# 登记表按第 2 列取值，不以列名为准）
_CITATION_COLUMNS: dict[str, tuple[str, ...]] = {
    "structure": ("出处",),
    "requirements-qualification": ("出处",),
    "requirements-submission": ("出处",),
    "requirements-business": ("出处（章/节/附件编号）", "出处"),
    "requirements-format": ("原文出处线索",),
    "disqualification": ("出处",),
    "evaluation": ("出处",),
}

_COVERAGE_RE = re.compile(r"^##\s*(?:[一二三四五]+、\s*)?coverage\s*声明\s*$")
_FILENAME_LIKE = re.compile(r"^(?P<fn>[^\s（();；/]+?\.(?:docx|pdf|txt|md))(?=[\s（]|$)")
_L_NUM = re.compile(r"L(\d+)")


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def _iter_tables(lines: list[str]):
    """逐表产出 (起始行号, 表头 cells, [(行号, cells)])；行号 1 起。"""
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            start = i
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                i += 1
            block = [(start + 1 + n, _split_row(lines[k])) for n, k in enumerate(range(start, i))]
            header = block[0][1]
            body = [r for r in block[2:] if not _is_separator(r[1])] if len(block) > 1 else []
            yield start + 1, header, body
        else:
            i += 1


def _excerpt(cell: str, limit: int = 40) -> str:
    return cell if len(cell) <= limit else cell[: limit - 1] + "…"


def _split_top(cell: str, seps: str) -> list[str]:
    """只在括号深度 0 处分割（golden 校准：括号内的「；」是行文注释
    「L52；后果见同文件 须知 20.1（L210）」，不是多出处分隔）。"""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in cell:
        if ch in "（([":
            depth += 1
        elif ch in "）)]":
            depth = max(0, depth - 1)
        if ch in seps and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _match_known_file(seg: str, known: list[str]) -> str | None:
    for fn in known:
        if seg == fn or seg.startswith(fn + " ") or seg.startswith(fn + "（") or seg.startswith(fn + "("):
            return fn
    return None


def _check_citation_cell(
    cell: str,
    known: list[str],
    src_lines: dict[str, int],
    table_anchor: dict,
) -> list[str]:
    """校验一个出处格（三层：锚定/文件名集合/行号上限），返回问题清单。"""
    issues: list[str] = []
    cell = cell.strip()
    if not cell:
        return ["出处列为空——每行证据都必须能独立定位到文件（「文件名 …（L…）」或「同文件 …（L…）」）"]
    for part in _split_top(cell, "；"):
        anchor: str | None = None
        for raw in _split_top(part, "/"):
            seg = raw.strip()
            if not seg:
                continue
            kf = _match_known_file(seg, known)
            if kf:
                anchor = kf
                table_anchor["file"] = kf
            elif seg.startswith("同文件"):
                anchor = table_anchor["file"]
                if not anchor:
                    issues.append(
                        f"出处「{_excerpt(seg)}」用了「同文件」但本表此前没有出现任何文件名锚"
                        "——首个出处须写全文件名"
                    )
            else:
                m = _FILENAME_LIKE.match(seg)
                if m:
                    issues.append(
                        f"出处「{_excerpt(seg)}」的文件名「{m.group('fn')}」不在已确认来源集合"
                        f"（{'、'.join(known) or '空'}）——核对文件名拼写，不得引用未确认/编造的文件"
                    )
                    anchor = None
                elif anchor is None:
                    issues.append(
                        f"出处「{_excerpt(seg)}」缺文件名或「同文件」前缀"
                        "——写全「文件名 章节（L…）」或「同文件 章节（L…）」"
                    )
            nums = [int(n) for n in _L_NUM.findall(seg)]
            if not nums:
                issues.append(f"出处「{_excerpt(seg)}」缺行号引用——每段须含 L行号（如 L97 / L18-L22）")
            elif anchor:
                limit = src_lines.get(anchor)
                if limit is None:
                    issues.append(
                        f"出处「{_excerpt(seg)}」引用的「{anchor}」没有解析产物"
                        "（解析失败降级的文件不可引用）"
                    )
                else:
                    over = [n for n in nums if n > limit]
                    if over:
                        issues.append(
                            f"出处「{_excerpt(seg)}」的行号 {'、'.join(f'L{n}' for n in over)}"
                            f"超出「{anchor}」解析结果总行数 {limit}——行号只能来自实际读取的区段"
                        )
    return issues


@tool
def validate_analysis() -> str:
    """机器校验当前任务 work/analysis/ 的要点产物（coverage 声明/出处引用键两层）。

    写完一节或几节后调用：[校验通过] 才算该节完成；[校验未通过] 会逐条给出
    「文件:行号 现状→修复写法」，按提示修复产物后重新运行。校验是纪律不是门禁，
    不阻塞流程——但收尾汇报前必须全部通过。只读、幂等。
    """
    try:
        ctx = runctx.current_run()
        task_id = ctx.task_id if ctx else None
        if not task_id:
            return "[校验失败] 缺少任务上下文：要点产物在当前任务的 work/analysis/ 下"
        wroot = work_dir(task_id)
        adir = wroot / "analysis"
        if not adir.is_dir():
            return "[校验失败] work/analysis/ 不存在——请先按 tender-analysis 技能产出要点文档"
        files = sorted(adir.glob("*.md"))
        if not files:
            return "[校验失败] work/analysis/ 下没有 .md 产物"

        # 来源集合与各来源解析 md 行数（行号上限校验的真值）
        known: list[str] = []
        src_lines: dict[str, int] = {}
        sources_note = ""
        sources_path = wroot / "parse" / "sources.json"
        if sources_path.is_file():
            try:
                data = json.loads(sources_path.read_text(encoding="utf-8"))
                known = [data.get("main") or ""] + [s.get("file", "") for s in data.get("supplements", [])]
                known = [f for f in known if f]
                for fn in known:
                    md = wroot / "parse" / fn / f"{fn}.md"
                    if md.is_file():
                        src_lines[fn] = len(md.read_text(encoding="utf-8", errors="replace").splitlines())
            except (json.JSONDecodeError, ValueError):
                sources_note = "sources.json 无法解析：文件名集合与行号上限校验已跳过"
        else:
            sources_note = "sources.json 不存在：文件名集合与行号上限校验已跳过"

        issues: list[str] = []
        warnings: list[str] = []
        citations = 0
        stems: list[str] = []

        for p in files:
            stem = p.stem
            stems.append(stem)
            rel = p.name
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

            # coverage（七节）
            if stem in _NEED_COVERAGE:
                cover = None
                for i, ln in enumerate(lines):
                    if _COVERAGE_RE.match(ln.strip()):
                        j = i + 1
                        while j < len(lines) and not lines[j].startswith("#"):
                            j += 1
                        cover = "\n".join(lines[i:j])
                        break
                if cover is None:
                    issues.append(f"{rel} 缺「## coverage 声明」段——「未发现」只能对已检查范围成立，范围必须声明")
                else:
                    for kw in ("已检查：", "未检查："):
                        if kw not in cover:
                            issues.append(f"{rel} 的 coverage 声明缺「{kw}」——两半都要写（未检查为无也写「未检查：无」）")
                    if stem == "disqualification" and "反查词表：" not in cover:
                        issues.append(f"{rel} 的 coverage 声明缺「反查词表：」——废标节必须逐词列出反查词")

            # 出处列引用键
            col_names = _CITATION_COLUMNS.get(stem)
            if col_names:
                for _, header, body in _iter_tables(lines):
                    col_idx = next((i for i, c in enumerate(header) if c in col_names), None)
                    if col_idx is None:
                        continue
                    table_anchor: dict = {"file": None}
                    for lineno, cells in body:
                        if col_idx >= len(cells):
                            continue
                        found = _check_citation_cell(cells[col_idx], known, src_lines, table_anchor)
                        if not found:
                            citations += 1
                        issues.extend(f"{rel}:{lineno} {msg}" for msg in found)

        # 汇总级
        if "clarifications" not in stems and set(_NEED_COVERAGE) <= set(stems):
            warnings.append("clarifications.md 不存在——七节齐时应汇总待澄清清单")
        extras = [s for s in stems if s not in _SECTIONS]
        if extras:
            warnings.append("存在未识别文件（不在八件清单）：" + "、".join(extras) + "——若是临时文件请移走，避免混入流水线")
        if sources_note:
            warnings.append(sources_note)

        if not issues:
            parts = [
                f"[校验通过] work/analysis/ 共 {len(files)} 件：coverage/出处引用（{citations} 条）全部合规"
            ]
            parts.extend(f"⚠️ {w}" for w in warnings)
            return "\n".join(parts)
        parts = [f"[校验未通过] 共 {len(issues)} 处问题（按提示修复产物后重新运行 validate_analysis，全部通过才算完成）："]
        parts.extend(f"- {i}" for i in issues)
        parts.extend(f"⚠️ {w}" for w in warnings)
        return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"[校验失败] {type(e).__name__}: {e}"
