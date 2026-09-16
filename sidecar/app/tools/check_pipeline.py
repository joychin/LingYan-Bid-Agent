"""确定性状态检查工具：汇总当前任务 sources/parse/analysis/body 的事实状态。

机械检查下沉（document-parse 重入对账、tender-analysis / tender-outline / tender-body
前置检查的机器化）：**只报事实、零结论**——「可不可以继续」的裁决规则在技能 SKILL.md，
工具不替模型做判断（如「缺节允许跑但声明影响」是技能规则，工具只报缺了哪些节）。

契约（与各技能 SKILL.md 一致）：
- work/parse/sources.json：{"main": str, "supplements": [{"file","role"}], "excluded": [str]}
- 解析三件套：work/parse/<文件名>/<文件名>.{md,outline.json,meta.json}；
  meta 的 generated_at 为 ISO 8601 秒级 UTC（+00:00）
- analysis 产物无首行元信息头（2026-09-04 裁决：模型写头不可靠，已删）；
  「修订=用户」标记 = 用户界面保存时服务端盖的首行注释（程序可靠侧）
- 新鲜度 = 来源 meta.generated_at 晚于产物文件修改时间（mtime，OS 时钟）即报；
  两端均为程序写/OS 记的可靠侧；界面编辑/恢复会刷新 mtime——方向是漏报不误报
- 正文阶段：body/ 节文件（.docx 现役形态、旧 .md 兼容；同名并存以 docx 为准并
  报事实）与目录产物（tender.directory 当前内容）叶子按「清洗后标题」
  对账（映射契约见 tools/body_contract.py），新鲜度 = 产物 content.json 的 mtime；
  「整本-」合册文件是派生产物不算节；标题改版后失配在此报事实，重写范围由用户裁决。
  extra 侧按全部叶子对账（模板填充类产出的格式件文件是合法节文件），missing 侧
  只算需正文叶子（格式件未产出不算缺）
- 待写节清单：指引已生成时列出**待写**节及每节事实（模式·素材块数），零结论——
  派发怎么分组、分几波由主 agent 按 tender-body SKILL.md 自行规划（2026-09-15
  拍板：拆分粒度归模型，机械均衡分波参考删除）；已写节剔除、物理附件类不列
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

from .. import runctx
from ..artifact_store import sources_dir, work_dir
from . import body_contract
from .validate_body import _BLOCK_ID_RE, _parse_guide_rows

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
    """汇总当前任务投标流水线的事实状态（来源/解析/要点/正文指引与已写节/新鲜度/未纳入文件）。

    确定性检查、只读、幂等：来源确认单与候选文件对账、解析三件套齐备性、要点产物
    已有/缺失、写作指引与承诺清单存在性、正文文件与目录产物叶子的对账、待写节
    清单（每节模式与素材块数，派发分组由技能规则自定）、来源/目录是否晚于产物
    更新（新鲜度）、sources/ 下未纳入来源集合的文件。
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

        # [body] 正文阶段事实（指引/承诺清单、已写节、与目录产物的对账；本段首次读产物）
        # 节文件收 .docx（现役形态）与 .md（旧任务兼容）；「整本-」是合册派生产物不算节
        bdir = wroot / "body"
        dir_row, dir_content, dir_mtime = body_contract.load_directory(task_id)
        all_body = sorted(
            list(bdir.rglob("*.docx")) + list(bdir.rglob("*.md"))
        ) if bdir.is_dir() else []
        guide_ok = (bdir / body_contract.GUIDE_NAME).is_file()
        promise_ok = (bdir / body_contract.PROMISE_NAME).is_file()
        section_files: list = []
        coexist: list[str] = []
        seen_stems: dict[tuple, Path] = {}
        # 整本产物恒落 body 根层且名为「整本-<清洗后册名>.docx」（合册约定）——
        # 只排除这些确切路径；子目录里的 整本-*.docx 是写手错放，照常进对账
        #（合册侧会按孤儿点名）。裸「文件名前缀」排除会把标题恰以「整本-」开头的
        # 合法节文件在对账三处同时隐身（2026-09-15 审计修复）
        vol_file_names: set[str] = set()
        if dir_content:
            for d in dir_content.get("response_documents") or []:
                _vol = str(d.get("name") or "").strip() or "主册"
                vol_file_names.add(
                    body_contract.VOLUME_PREFIX + body_contract.sanitize_name(_vol) + ".docx"
                )
        for p in all_body:
            if p.name in (body_contract.GUIDE_NAME, body_contract.PROMISE_NAME):
                continue
            if p.parent == bdir and (
                p.name in vol_file_names
                or (not vol_file_names and p.name.startswith(body_contract.VOLUME_PREFIX))
            ):
                continue
            key = (p.parent, p.stem)
            if key in seen_stems:
                # 同名 .docx/.md 并存：对账以 docx 为准（排序序 .docx 在前先入）
                if p.suffix == ".docx":
                    section_files.remove(seen_stems[key])
                    section_files.append(p)
                    seen_stems[key] = p
                coexist.append(
                    str(p.relative_to(bdir).with_suffix(""))
                    + "（旧稿残留，以 docx 为准——请用户确认后清理旧 md）"
                )
                continue
            seen_stems[key] = p
            section_files.append(p)
        # 孤立 .md（无同名 docx）不计入已写/对账：合册只并 docx（现役形态），计入
        # 会「check 报已写、合册报缺节」两侧矛盾——降为旧稿残留提示
        _docx_keys = {(p.parent, p.stem) for p in section_files if p.suffix == ".docx"}
        _lone_md = [p for p in section_files if p.suffix == ".md" and (p.parent, p.stem) not in _docx_keys]
        if _lone_md:
            _drop = {(p.parent, p.stem) for p in _lone_md}
            section_files = [p for p in section_files if (p.parent, p.stem) not in _drop]
        if dir_row is None:
            lines.append("[body] 无目录产物（正文依据投标目录当前内容，需先 tender-outline 生成）")
            if all_body:
                lines.append(f"[body] 但 work/body/ 已有 {len(all_body)} 个文件（目录未发布或已删除）")
        elif not guide_ok and not promise_ok and not section_files:
            lines.append("[body] 未开始（无写作指引、无正文文件）")
        else:
            seg = (
                "[body] 指引" + ("已生成" if guide_ok else "未生成")
                + "；承诺清单" + ("已生成" if promise_ok else "未生成")
                + f"；已写 {len(section_files)} 节"
            )
            lines.append(seg)
            if coexist:
                lines.append("[body] 同时存在 .docx 与 .md 的节：" + "、".join(coexist))
            if _lone_md:
                lines.append(
                    "[body] " + str(len(_lone_md)) + " 个旧稿 .md 残留（现役形态 docx，"
                    "合册不并入——请用户确认后清理）："
                    + "、".join(str(p.relative_to(bdir).with_suffix("")) for p in _lone_md[:8])
                    + ("…" if len(_lone_md) > 8 else "")
                )
            if dir_content is None:
                lines.append("[body] 目录产物内容无法读取——叶子对账与新鲜度跳过")
            else:
                multi = body_contract.multi_volume(dir_content)
                # 实际文件按（册目录, 文件名主干）归组；期望叶子按同规则清洗标题。
                # extra 侧对账用**全部叶子**——模板填充类产出的格式件文件也是合法
                # 节文件（2026-09-06 拍板：产出即并整本）；missing 侧维持需正文叶子
                # ——格式件未产出不算缺（按附件对待）
                actual: set[tuple[str, str]] = set()
                # 合册只认固定深度：单册 body/<stem>.docx、多册 body/<册>/<stem>.docx
                #——更深的嵌套文件（09-15 事故形态：写手自选章节子目录）按「错位」
                # 单列点名，不再折名进 actual（折名会把它当成正常文件判「对账一致」，
                # 与合册 missing+孤儿两侧矛盾）
                misplaced: list[str] = []
                expected_depth = 2 if multi else 1
                for p in section_files:
                    rel = p.relative_to(bdir)
                    if len(rel.parts) > expected_depth:
                        misplaced.append(rel.as_posix())
                        continue
                    vol = body_contract.sanitize_name(rel.parts[0]) if len(rel.parts) > 1 else ""
                    # stem 同过清洗（与期望侧同规则）：超长标题被 sanitize 截到 60 字、
                    # 连续空白折叠——两侧规则不一会同时误报 extra+missing
                    actual.add((vol, body_contract.sanitize_name(p.stem)))
                if misplaced:
                    lines.append(
                        "[body] " + str(len(misplaced)) + " 个文件嵌套在子目录（与合册平铺"
                        "约定不符，合册找不到——移到 body/ 根层或多册目录下）："
                        + "、".join(misplaced[:8]) + ("…" if len(misplaced) > 8 else "")
                    )
                seen_titles: dict[tuple[str, str], int] = {}
                known: set[tuple[str, str]] = set()
                for vol, title, _mode in body_contract.iter_leaves(dir_content):
                    pair = (body_contract.sanitize_name(vol) if multi else "",
                            body_contract.sanitize_name(title))
                    known.add(pair)
                    seen_titles[pair] = seen_titles.get(pair, 0) + 1
                expected = {
                    (body_contract.sanitize_name(vol) if multi else "",
                     body_contract.sanitize_name(title))
                    for vol, title, _mode in body_contract.prose_leaves(dir_content)
                }
                dup = [k for k, n in seen_titles.items() if n > 1]
                if dup:
                    lines.append(
                        "[body] 同册存在同名叶子（清洗后文件名冲突）："
                        + "、".join(f"{v}/{s}" if v else s for v, s in sorted(dup))
                        + "——文件名映射歧义，需用户改名其一"
                    )
                missing = expected - actual
                if missing:
                    lines.append(
                        "[body] 目录节点未写正文："
                        + "、".join(f"{v}/{s}" if v else s for v, s in sorted(missing))
                    )
                extra = actual - known
                if extra:
                    lines.append(
                        "[body] body/ 文件无对应目录节点（标题不一致或目录已改版）："
                        + "、".join(f"{v}/{s}" if v else s for v, s in sorted(extra))
                    )
                if not missing and not extra and section_files:
                    lines.append("[body] 叶子对账一致（需正文节点均有文件，模板填充类按产出计）")
                stale = [
                    p for p in section_files
                    if dir_mtime is not None and p.stat().st_mtime < dir_mtime
                ]
                if stale:
                    lines.append(
                        "[body] 目录产物更新晚于正文最后修改（可能基于旧目录，重写范围由用户裁决）："
                        + "、".join(str(p.relative_to(bdir)) for p in stale)
                    )
                # 待写节清单（零结论事实）：只覆盖**待写**节——派发分组与波次由主
                # agent 按 SKILL 规则自行规划（2026-09-15 拍板：拆分粒度归模型，
                # 机械均衡分波参考删除；重节分散等调度启发式改写在 SKILL 纪律里）；
                # 指引缺行的待写需正文叶子按「指引缺行」兜底补入（validate_body
                # 另有缺行警告）；物理附件类（建壳/贴图，2026-09-14 起）与目录页
                # 节点由主线程处理、不派子代理故不列
                if guide_ok:
                    pending: dict[tuple[str, str], tuple[str, str, int]] = {}
                    try:
                        guide_text = (bdir / body_contract.GUIDE_NAME).read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except OSError:
                        guide_text = ""
                    for _lineno, cells, cols in _parse_guide_rows(guide_text.splitlines()):
                        title = cells[cols["节"]].strip()
                        vol = ""
                        if multi and "/" in title:
                            head, _, tail = title.partition("/")
                            vol, title = head.strip(), tail.strip()
                        key = (
                            body_contract.sanitize_name(vol) if multi else "",
                            body_contract.sanitize_name(title),
                        )
                        if key not in known or key in actual:
                            continue  # 指引行不在目录树（改版残留）或该节已写
                        # 缺口列头变体匹配（与 dispatch_enrich._GAP_COL_KEYS 同口径）：
                        # 模型把契约列头「缺口/备注」写成「缺口」等变体时，精确键拿不
                        # 到列 → 物理附件节漏剔除被派子代理（两处判定分叉的收口）
                        note_i = next(
                            (i for k, i in cols.items() if ("缺口" in k or "备注" in k)),
                            4,
                        )
                        note = cells[note_i] if note_i < len(cells) else ""
                        if "物理附件" in note:
                            continue
                        mode_i = cols["模式"]
                        raw_mode = cells[mode_i].strip() if mode_i < len(cells) else ""
                        mode = raw_mode if raw_mode and raw_mode != "—" else "模式未填"
                        mat_i = cols.get("素材", 3)
                        mat = cells[mat_i] if mat_i < len(cells) else ""
                        label = f"{key[0]}/{key[1]}" if key[0] else key[1]
                        pending[key] = (label, mode, len(_BLOCK_ID_RE.findall(mat)))
                    for key in sorted(missing - set(pending)):
                        label = f"{key[0]}/{key[1]}" if key[0] else key[1]
                        pending[key] = (label, "指引缺行", 0)
                    if pending:
                        lines.append(
                            f"[body] 待写节清单（共 {len(pending)}，派发分组与波次由你按"
                            "技能规则自行规划；物理附件类不在此列）："
                        )
                        for label, mode, nmat in pending.values():
                            lines.append(f"  {label}（{mode}·素材{nmat}块）")

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
