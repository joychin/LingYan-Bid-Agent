"""确定性状态检查工具：汇总当前任务 sources/parse/analysis 的事实状态。

机械检查下沉（document-parse 重入对账、tender-analysis / tender-outline 前置
检查的机器化）：**只报事实、零结论**——「可不可以继续」的裁决规则在技能 SKILL.md，
工具不替模型做判断（如「缺节允许跑但声明影响」是技能规则，工具只报缺了哪些节）。

契约（与各技能 SKILL.md 一致）：
- work/parse/sources.json：{"main": str, "supplements": [{"file","role"}], "excluded": [str]}
- 解析三件套：work/parse/<文件名>/<文件名>.{md,outline.json,meta.json}；
  meta 的 generated_at 为 ISO 8601 秒级 UTC（+00:00）
- analysis 产物无首行元信息头（2026-09-04 裁决：模型写头不可靠，已删）；
  「修订=用户」标记 = 用户界面保存时服务端盖的首行注释（程序可靠侧）
- 新鲜度 = 来源 meta.generated_at 晚于产物文件修改时间（mtime，OS 时钟）即报；
  两端均为程序写/OS 记的可靠侧；界面编辑/恢复会刷新 mtime——方向是漏报不误报
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.tools import tool

from .. import runctx
from ..artifact_store import sources_dir, work_dir

# 八件固定清单（七节 + 待澄清汇总），[analysis] 的已有/缺失以此为准
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

_PARSE_EXTS = ("md", "outline.json", "meta.json")


def _list_files(directory) -> list[str]:
    """目录下非隐藏文件清单（目录不存在返回空）。"""
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_file() and not p.name.startswith("."))


@tool
def check_pipeline_state() -> str:
    """汇总当前任务投标流水线的事实状态（来源确认/解析产物/要点产物/新鲜度/未纳入文件）。

    确定性检查、只读、幂等：来源确认单与候选文件对账、解析三件套齐备性、要点产物
    已有/缺失、来源文件是否晚于产物更新（新鲜度）、sources/ 下未纳入来源集合的文件。
    只报事实不含裁决——先调用本工具，再按当前技能 SKILL.md 的规则决定怎么继续。
    """
    try:
        ctx = runctx.current_run()
        task_id = ctx.task_id if ctx else None
        if not task_id:
            return "[检查失败] 缺少任务上下文：来源与产物都在当前任务目录下"

        wroot = work_dir(task_id)
        sroot = sources_dir(task_id)
        lines: list[str] = ["[pipeline 状态]（事实汇总，如何继续由技能规则裁决）"]

        # [sources] 来源确认单
        data: dict | None = None
        sources_path = wroot / "parse" / "sources.json"
        if not sources_path.is_file():
            lines.append("[sources] 未确认（来源确认单不存在，需先确认主文件与补充角色）")
        else:
            try:
                data = json.loads(sources_path.read_text(encoding="utf-8"))
                seg = f"主文件={data.get('main') or '（空）'}"
                sups = [f"{s.get('file', '?')}（{s.get('role', '?')}）" for s in data.get("supplements", [])]
                if sups:
                    seg += "；补充=" + "、".join(sups)
                excl = list(data.get("excluded", []))
                if excl:
                    seg += "；排除=" + "、".join(excl)
                lines.append(f"[sources] 已确认：{seg}")
            except (json.JSONDecodeError, ValueError, AttributeError) as e:
                lines.append(f"[sources] 确认单无法解析（JSON 语法错误：{e}）")

        # [candidates] 上传区候选
        names = _list_files(sroot)
        if not sroot.is_dir():
            lines.append("[candidates] sources/ 目录不存在（任务骨架未建或尚无上传）")
        else:
            lines.append("[candidates] sources/ 下文件：" + ("、".join(names) if names else "（空）"))

        # 来源集合内文件（对账/新鲜度都用它）
        known_files: list[str] = []
        if data:
            known_files = [data.get("main") or ""] + [s.get("file", "") for s in data.get("supplements", [])]
            known_files = [f for f in known_files if f]

        # [parse] 解析三件套齐备性 + 解析时间/档位
        parse_ts: dict[str, str | None] = {}
        for fname in known_files:
            pdir = wroot / "parse" / fname
            ts: str | None = None
            conv: str | None = None
            meta_p = pdir / f"{fname}.meta.json"
            if meta_p.is_file():
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                    ts = str(meta.get("generated_at") or "") or None
                    conv = str(meta.get("conversion") or "") or None
                except (json.JSONDecodeError, ValueError):
                    ts = None
            parse_ts[fname] = ts
            if not pdir.is_dir():
                lines.append(f"[parse] {fname}：无解析目录（从未解析）")
                continue
            missing = [e for e in _PARSE_EXTS if not (pdir / f"{fname}.{e}").is_file()]
            if missing:
                have = [e for e in _PARSE_EXTS if e not in missing]
                seg = f"[parse] {fname}：缺 {'、'.join(missing)}"
                if have:
                    seg += f"（已有 {'、'.join(have)}）"
                lines.append(seg)
            else:
                seg = f"[parse] {fname}：三件齐备"
                if ts:
                    seg += f"，生成={ts}"
                if conv:
                    seg += f"，档位={conv}"
                lines.append(seg)

        # [untracked] 未纳入来源集合的新文件（未确认时不报——所有文件都等于未纳入，无信息量）
        if data and sroot.is_dir():
            listed = set(known_files) | set(data.get("excluded", []))
            untracked = [n for n in names if n not in listed]
            if untracked:
                lines.append("[untracked] sources/ 中未纳入来源集合的文件：" + "、".join(untracked))

        # [analysis] 要点产物（修订标记=首行注释含「修订=用户」，新旧文件通吃）
        mtimes: dict[str, str] = {}
        revised: dict[str, bool] = {}
        adir = wroot / "analysis"
        if not adir.is_dir():
            lines.append("[analysis] 无产物（work/analysis/ 不存在）")
        else:
            extras: list[str] = []
            for p in sorted(adir.glob("*.md")):
                first = p.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
                revised[p.stem] = bool(first) and "修订=用户" in first[0]
                mtimes[p.stem] = datetime.fromtimestamp(
                    p.stat().st_mtime, timezone.utc
                ).isoformat(timespec="seconds")
                if p.stem not in _SECTIONS:
                    extras.append(p.name)
            have_sections = [s for s in _SECTIONS if s in revised]
            if have_sections:
                segs = [s + ("，修订=用户" if revised[s] else "") for s in have_sections]
                lines.append("[analysis] 已有产物：" + "、".join(segs))
                missing_sections = [s for s in _SECTIONS if s not in revised]
                if missing_sections:
                    lines.append("[analysis] 缺：" + "、".join(missing_sections))
            else:
                lines.append("[analysis] 无已知产物（八件清单一件都没有）")
            if extras:
                lines.append("[analysis] 未识别的文件（不在八件清单）：" + "、".join(extras))

        # [freshness] 来源解析晚于产物最后修改（mtime vs generated_at，均为程序可靠侧）
        if mtimes and not data:
            lines.append("[freshness] 无法核对（来源确认单不可用）")
        elif mtimes:
            fresh: list[str] = []
            for stem, mtime in mtimes.items():
                stale = [f for f in known_files if (parse_ts.get(f) or "") > mtime]
                for f in stale:
                    fresh.append(
                        f"[freshness] {f} 解析生成={parse_ts[f]} 晚于 {stem}.md 最后修改（{mtime}）"
                        "→ 该产物自原文最近一次解析后未再修改，可能基于旧版文件"
                    )
            if fresh:
                lines.extend(fresh)
            else:
                lines.append("[freshness] 无过期（已确认来源的解析时间均不晚于各产物最后修改时间）")

        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"[检查失败] {type(e).__name__}: {e}"
