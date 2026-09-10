"""tender-body 正文产物机器校验工具（提示不是门禁：逐条给修复写法，不阻塞流程）。

校验契约（真值 = tender-body SKILL.md + references/guide-format.md）：
- 写作指引（body/写作指引.md）：需正文的目录叶子每节有行（多册键=「册名/标题」，
  与目录标题逐字一致）、模式列取值合法（素材修订/格式跟随/推理撰写，「+」组合；
  非正文节点可「—」）、素材列块 id 可解析（blk_ 存在于素材库）、素材不跨节复用
  （同块多派=issue——注入两节即逐字重复；不同块同素材文件区间重叠=弱级提示，
  治历史重复建块）
- 正文节（body/<册>/<节>.docx，兼容旧 .md）：待办批注清点（docx_comment_add 落的
  Word 批注——收尾汇报逐条点名）、内联占位【待补/待澄清】**判不过**（占位文字会进
  交付稿，正规落点是批注）、疑似残留（选用素材块所在文件名主干入扫描表——弱级来源，
  通用产品词可能误报，提示核对而非必须清零）、素材使用率（正文与选用
  块的字符级 shingle 重叠率——「查到素材却凭空写」的机械防线，提示不是门禁）；
  docx 节按**接受全部修订后的终稿视角**取文本（评委最终看到的），批注/占位定位段落
  为 P 段号、表格行为 T{t}R{r}（与 docx_section_read 视图互查），md 节仍为 L 行号
  （旧任务兼容：md 无批注能力，内联占位维持清点不判不过）
- 全局（section="body"）：承诺清单（关键事实与承诺.md 的「事项｜值」表）每个值
  是否落进任意正文节——去空白归一化子串匹配，未落正文点名（该节未写/值被改写）；
  节间两两查重（归一化 shingle 交集/较小方 ≥50% 点名——同一素材进多节或原文
  照搬，独立于承诺清单跑）；「整本-」合册产物不参与（派生产物）；反向「正文
  出现与清单不一致的值」属语义审阅，不在此判
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from docx import Document
from langchain_core.tools import tool

from .. import db, runctx
from ..artifact_store import work_dir
from ..knowledge import materials_lib
from . import body_contract
from .check_residue import re_split_name, scan_residue
from .docx_ops import section_comments_labeled, section_lines_labeled, section_text_lines
from .validate_analysis import _iter_tables

_BLOCK_ID_RE = re.compile(r"blk_[0-9a-f]{12}")
# 占位/待澄清标记：真值在 body_contract（docx_ops 合册兜底扫描共用）——待办的
# 正规落点是 docx_comment_add 批注，本表只用于发现违规内联占位
_PLACEHOLDER_MARKS = body_contract.PLACEHOLDER_MARKS
# 素材使用率：块 shingle 在正文中的出现比例低于该值提示「未实质使用」
_OVERLAP_HINT = 0.10
# 节间查重：两节归一化 shingle 交集 / 较小方 ≥ 该值提示「疑似重复」
# （同块多派/原文照搬的实测形态在 78%+；50% 线避开共享承诺值等短重叠）
_DUP_RATIO = 0.50
_SHINGLE = 10


def _normalize(text: str) -> str:
    """块切片与节文本的统一归一化：在剥注释/空白行之外，再剥两侧形态差符号——
    块侧是 md（表格竖线与 --- 分隔行、列表/标题前缀），节侧是 docx 终稿行
    （表格行以 " | " 拼格）。不剥则表格为主的块 shingle 大面积对不上，素材
    使用率误报「未实质使用」（2026-09-08 实证）。
    """
    out = []
    for ln in text.splitlines():
        s = ln.replace("<!--", "").replace("-->", "").strip()
        if not s:
            continue
        s = s.lstrip("#>- ").strip()  # md 标题/列表前缀
        s = s.replace("|", "").strip()  # md 表格竖线（节侧 " | " 拼格同剥）
        s = re.sub(r"\s+", "", s)  # 行内空白（两侧空格数不定）
        if not s or set(s) <= {"-"}:  # 表格分隔行 |---|---|
            continue
        out.append(s)
    return "".join(out)


def _shingles(text: str) -> set[str]:
    return {text[i : i + _SHINGLE] for i in range(max(0, len(text) - _SHINGLE + 1))}


def _overlap_ratio(section_text: str, block_text: str) -> float | None:
    """块 shingle 在正文中的出现比例（None=块太短，比率无意义）。"""
    bs = _shingles(_normalize(block_text))
    if len(bs) < 5:
        return None
    return len(bs & _shingles(_normalize(section_text))) / len(bs)


def _block_text(bid: str) -> tuple[dict | None, str]:
    """按块 id 取块行与切片全文（块失效返回 (None, "")）。"""
    b = db.mt_get_block(bid)
    if not b:
        return None, ""
    f = db.mt_get_file(b["file_id"])
    if not f:
        return b, ""
    md_path, _, _ = materials_lib.mt_parse_paths(f["file_name"])
    return b, materials_lib._slice(md_path, b.get("ranges") or [])


def _residue_names(block_ids: list[str]) -> list[str]:
    """选用素材块所在文件名的主干词（≥4 字）——旧项目名最常见的藏身处。"""
    names: list[str] = []
    seen: set[str] = set()
    for bid in block_ids:
        b = db.mt_get_block(bid)
        if not b:
            continue
        f = db.mt_get_file(b["file_id"])
        if not f:
            continue
        for part in re_split_name(Path(f["file_name"]).stem):
            if len(part) >= 4 and part not in seen:
                seen.add(part)
                names.append(part)
    return names


def _parse_guide_rows(lines: list[str]) -> list[tuple[int, list[str], dict[str, int]]]:
    """指引表的 (行号, cells, 列名→下标)；无合法表返回空。"""
    rows: list[tuple[int, list[str], dict[str, int]]] = []
    for _, header, body in _iter_tables(lines):
        idx = {c: i for i, c in enumerate(header)}
        if "节" not in idx or "模式" not in idx:
            continue
        col = idx["节"]
        for lineno, cells in body:
            if col < len(cells) and cells[col].strip():
                rows.append((lineno, cells, idx))
    return rows


def _ranges_overlap(a: list, b: list) -> bool:
    """两组行号区间是否有交集（与前端建块重叠提示 anyOverlap 同语义）。"""
    return any(s1 <= e2 and s2 <= e1 for s1, e1 in a for s2, e2 in b)


def _validate_guide(lines: list[str], task_id: str) -> tuple[list[str], list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []

    _, content, _ = body_contract.load_directory(task_id)
    if content is None:
        warnings.append("无目录产物或内容不可读——叶子对账跳过，仅校验模式取值与素材块 id")

    multi = body_contract.multi_volume(content) if content else False
    leaf_keys: set[str] = set()
    prose_keys: set[str] = set()
    delivery: dict[str, str] = {}
    if content:
        for vol, title, mode in body_contract.iter_leaves(content):
            key = f"{vol}/{title}" if multi else title
            leaf_keys.add(key)
            delivery[key] = mode
            if mode not in body_contract.NON_PROSE_DELIVERY:
                prose_keys.add(key)

    rows = _parse_guide_rows(lines)
    if not rows:
        issues.append("指引缺少表格——须为「| 节 | 模式 | 依据 | 素材 | 缺口/备注 |」的 Markdown 表")
        return issues, warnings, []

    row_keys: set[str] = set()
    # 块 id → 派给的节名（同块多派=正文逐字重复）；bid → db 块行缓存（避免重复查询）
    row_blocks: dict[str, list[str]] = {}
    block_cache: dict[str, dict | None] = {}
    for lineno, cells, idx in rows:
        key = cells[idx["节"]].strip()
        row_keys.add(key)
        mode = cells[idx["模式"]].strip() if idx.get("模式", 1) < len(cells) else ""
        material = cells[idx["素材"]].strip() if idx.get("素材", 3) < len(cells) else ""

        if content and key not in leaf_keys:
            issues.append(
                f"写作指引.md:{lineno} 行「{key}」不在目录叶子中——节名须与目录逐字一致"
                f"（多册写「册名/标题」），目录改版后须重对指引"
            )
        tokens = [t.strip() for t in mode.split("+") if t.strip()]
        if tokens == ["—"]:
            if key in prose_keys:
                # 降为提示（2026-09-06 实测）：评标索引表/分项报价表等表格类节点
                # 常被目录错标为需正文——不把模型逼进修改循环，给两条出路
                warnings.append(
                    f"写作指引.md:{lineno} 「{key}」被目录标为需正文但模式写了「—」——"
                    "若实为表格/索引/填表类节点，指引行注明「按招标格式填表」即可；"
                    "确需正文则补写模式"
                )
        elif not tokens:
            issues.append(f"写作指引.md:{lineno} 模式列为空——素材修订/格式跟随/推理撰写（可「+」组合）")
        else:
            bad = [t for t in tokens if t not in body_contract.MODES]
            if bad:
                issues.append(
                    f"写作指引.md:{lineno} 模式「{'、'.join(bad)}」不合法——只能取 "
                    f"{'/'.join(body_contract.MODES)}（「+」组合；非正文节点写「—」）"
                )
            if "素材修订" in tokens and not _BLOCK_ID_RE.findall(material) and "【缺】" not in material:
                warnings.append(
                    f"写作指引.md:{lineno} 「{key}」素材修订模式但素材列无块 id 也未标【缺】——"
                    "先 search_references 检索，确实没有再标【缺】（缺料清单要向用户点名）"
                )
        for bid in dict.fromkeys(_BLOCK_ID_RE.findall(material)):  # 行内同块去重
            if bid not in block_cache:
                block_cache[bid] = db.mt_get_block(bid)
            b = block_cache[bid]
            if b is None:
                issues.append(f"写作指引.md:{lineno} 素材块 {bid} 失效（块已删除）——重检索并更新指引")
                continue
            keys = row_blocks.setdefault(bid, [])
            if key not in keys:
                keys.append(key)
        dep = cells[idx["依据"]].strip() if idx.get("依据", 2) < len(cells) else ""
        if not dep and content and key in prose_keys:
            warnings.append(f"写作指引.md:{lineno} 「{key}」依据列为空——纯过渡章允许；应写节须挂 REQ/SCORE/MAND ID")

    # 同块多派：同一素材块出现在多行 → 注入两节=正文逐字重复（2026-09-08 实测事故：
    # 同一 625 段素材块全文进了两个节）。issue 级——与 docx_material_inject 的
    # 同文件重复拦截同语义，格式跟随不用素材块、推理撰写不该挂块，无正当场景
    for bid, keys in row_blocks.items():
        if len(keys) > 1:
            title = (block_cache.get(bid) or {}).get("title") or bid
            issues.append(
                f"素材块 {bid}《{title}》同时派给 {len(keys)} 个节（{'、'.join(keys)}）——"
                "同一块注入两节会造成正文逐字重复：素材库按行号拆成小范围块一节一块，"
                "或只保留一节用该块、其余节改推理撰写"
            )
    # 马甲块：不同块 id 同素材文件且区间有交集、派给不同节（弱级——历史重复建块
    # 不会被失效检查发现，点名核对）
    by_file: dict[str, list[str]] = {}
    for bid, keys in row_blocks.items():
        b = block_cache.get(bid) or {}
        if len(keys) == 1 and b.get("file_id"):
            by_file.setdefault(b["file_id"], []).append(bid)
    for fid, bids in by_file.items():
        if len(bids) < 2:
            continue
        f = db.mt_get_file(fid)
        fname = (f or {}).get("file_name") or fid
        for i in range(len(bids)):
            for j in range(i + 1, len(bids)):
                ba, bb = block_cache[bids[i]], block_cache[bids[j]]
                if not _ranges_overlap(ba.get("ranges") or [], bb.get("ranges") or []):
                    continue
                warnings.append(
                    f"素材块《{ba.get('title') or bids[i]}》与《{bb.get('title') or bids[j]}》"
                    f"同属素材文件 {fname} 且勾选区间重叠，分别派给「{row_blocks[bids[i]][0]}」"
                    f"「{row_blocks[bids[j]][0]}」——内容大面积相同，两节正文可能重复："
                    "确认是否重复建块（保留其一），或改拆成不重叠区间"
                )

    if content:
        for key in sorted(prose_keys - row_keys):
            issues.append(f"指引缺行：「{key}」（交付形态={delivery.get(key) or '未标注'}）——需正文的每节都要一行")
    return issues, warnings, []


def _validate_section(
    lines: list[str], block_ids: list[str] | None, pos: str = "L",
    labels: list[str] | None = None, docx: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    if not any(ln.strip() for ln in lines):
        hint = (
            "缺料用 docx_comment_add 加批注记待办"
            if docx else "缺料在收尾汇报向用户逐项点名"  # md 旧形态无批注能力
        )
        return (
            [f"正文为空——每节须有实质内容（{hint}），不得留空文件"],
            warnings,
            notes,
        )

    # 内联占位：docx 节判不过（占位文字会进交付稿——待办该走 docx_comment_add 批注）；
    # md 节是旧任务兼容形态（md 无批注能力），维持清点进 notes 供收尾点名
    # （md 节 pos=L 行号；docx 节 labels 逐行给定位——段落 P 段号、表格行 T 行号，
    # 与 docx_section_read 视图互查）
    for i, ln in enumerate(lines, 1):
        if any(mark in ln for mark in _PLACEHOLDER_MARKS):
            loc = labels[i - 1] if labels and i <= len(labels) else f"{pos}{i}"
            snippet = ln.strip()[:30]
            if docx:
                issues.append(
                    f"{loc}：正文含内联占位「{snippet}」——占位文字会随交付稿出去，"
                    "删除该文字、改用 docx_comment_add 加批注记待办"
                    "（缺料/待澄清/待核验都落批注，不落正文）"
                )
            else:
                notes.append(f"{loc}：{ln.strip()[:50]}{'…' if len(ln.strip()) > 50 else ''}")

    if block_ids is None:
        warnings.append("未传 block_ids——旧名残留与素材使用率检查跳过（使用计划里选了哪些块就传哪些）")
        return issues, warnings, notes

    # 残留：扫描表全部来自素材文件名主干=弱级来源（通用产品词会混进来，
    # 2026-09-06 实测「流程管理」误报）——提示核对，不是必须清零的硬错误；
    # 硬级（元数据项目名/客户名、显式名单）经 check_name_residue 工具单独扫
    for hit in scan_residue(lines, _residue_names(block_ids), labels=labels):
        warnings.append(f"疑似残留（来自素材文件名，可能为通用术语）：{hit}——逐条核对，旧项目用语→替换")

    for bid in dict.fromkeys(block_ids):  # 去重：同一块重复传入只报一次
        b, text = _block_text(bid)
        if b is None:
            issues.append(f"素材块 {bid} 失效（块已删除）——重检索换块后重写本节或更新使用计划")
            continue
        if not text:
            warnings.append(f"素材块「{b.get('title') or bid}」取不到内容（解析产物缺失）——跳过重叠率")
            continue
        ratio = _overlap_ratio("\n".join(lines), text)
        if ratio is None:
            continue
        if ratio < _OVERLAP_HINT:
            warnings.append(
                f"素材块「{b.get('title') or bid}」重叠率 {ratio:.0%}——未实质使用素材"
                f"（素材修订=先把块贴进底稿再改写适配，不是看着参考另写一篇）"
            )
    return issues, warnings, notes


def _section_dup_warnings(body_dir: Path, sections: list[Path], finals: list[str]) -> list[str]:
    """节间两两查重：同一素材块进多节、或一节原文照搬另一节（2026-09-08 实测：
    同一 625 段素材块全文进了「总体建设方案」与「系统集成方案」两节）。
    重叠率 = 归一化 shingle 交集 / 较小方；短节（<5 shingle，承诺行级别）跳过；
    提示不是门禁——收尾前逐对裁决（拆块或改写）。"""
    sigs: list[tuple[str, set[str]]] = []
    for q, text in zip(sections, finals, strict=True):
        sh = _shingles(_normalize(text))
        if len(sh) < 5:
            continue
        sigs.append((q.relative_to(body_dir).with_suffix("").as_posix(), sh))
    warns: list[str] = []
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            (na, sa), (nb, sb) = sigs[i], sigs[j]
            ratio = len(sa & sb) / min(len(sa), len(sb))
            if ratio >= _DUP_RATIO:
                warns.append(
                    f"节间疑似重复：「{na}」与「{nb}」内容重叠约 {ratio:.0%}——"
                    "同一素材进多节或原文照搬；对照写作指引素材列，拆块或改写"
                )
    return warns


def _validate_body_global(body_dir: Path) -> str:
    """全局收尾比对：承诺清单的每个值是否落进了正文（单向：清单→正文）+ 节间查重。

    匹配 = 去空白归一化后的子串（「90 天」↔「90天」视为一致）；未在任何正文节
    出现的值点名提示（该节未写或值被改写，核对后补落正文或修正清单）。节间查重
    独立于承诺清单（清单缺失/格式不对也照跑——两节大面积重叠才是它要抓的事）。
    全部为提示级——提示不是门禁；反向「正文出现与清单不一致的值」属语义审阅，
    不在此判。
    """
    # 节文件收 .docx（现役形态）与 .md（旧任务兼容）；同名并存去重（docx 排序序
    # 在前=新形态优先）；「整本-」合册产物是派生物不参与比对
    seen: set[tuple[Path, str]] = set()
    sections: list[Path] = []
    for q in sorted(list(body_dir.rglob("*.docx")) + list(body_dir.rglob("*.md"))):
        if q.name in ("写作指引.md", "关键事实与承诺.md") or q.name.startswith("整本-"):
            continue
        key = (q.parent, q.stem)
        if key in seen:
            continue
        seen.add(key)
        sections.append(q)
    if not sections:
        return "[校验通过] body 全局：暂无正文节——跳过承诺比对"

    def _final_text(q: Path) -> str:
        # docx 按接受全部修订后的终稿视角取文本（评委看到的）
        if q.suffix == ".docx":
            return "\n".join(section_text_lines(Document(str(q))))
        return q.read_text(encoding="utf-8", errors="replace")

    # 单节损坏不拖垮全局（2026-09-10 review）：坏节剔除并点名，承诺比对/节间
    # 查重对其余节照常跑——同类消费者（兄弟摘要/合册缺节点名）都是这个口径
    finals: list[str] = []
    broken: list[str] = []
    readable: list[Path] = []
    for q in sections:
        try:
            finals.append(_final_text(q))
            readable.append(q)
        except Exception:
            broken.append(f"{q.parent.name}/{q.name}")
    if broken and not finals:
        return "[校验失败] body 全局：正文节全部损坏（" + "、".join(broken) + "）——删除重建后再收尾"
    sections = readable
    dup_warns = _section_dup_warnings(body_dir, sections, finals)

    skip_note: str | None = None
    promise_summary = ""
    warn_lines: list[str] = []
    promise_path = body_dir / "关键事实与承诺.md"
    if not promise_path.is_file():
        skip_note = "无关键事实与承诺清单——跳过承诺比对（开工时应生成 body/关键事实与承诺.md）"
    else:
        rows: list[tuple[int, str, str]] = []
        header_seen = False
        for _, header, body in _iter_tables(
            promise_path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            idx = {c: i for i, c in enumerate(header)}
            if "事项" not in idx or "值" not in idx:
                continue
            header_seen = True
            for lineno, cells in body:
                ci, cv = idx["事项"], idx["值"]
                if ci < len(cells) and cv < len(cells):
                    item, val = cells[ci].strip(), cells[cv].strip()
                    if item and val:
                        rows.append((lineno, item, val))
        if not header_seen:
            skip_note = "承诺清单不是「事项｜值｜说明」表——跳过比对（格式契约见技能 references/guide-format.md）"
        else:
            texts = [re.sub(r"\s+", "", t) for t in finals]
            placed = 0
            for lineno, item, val in rows:
                key = re.sub(r"\s+", "", val)
                if len(key) < 2:
                    continue
                if any(key in t for t in texts):
                    placed += 1
                else:
                    warn_lines.append(
                        f"关键事实与承诺.md:{lineno} 「{item}={val}」未在任何正文出现"
                        "——该节未写或值被改写，核对后补落正文或修正清单"
                    )
            promise_summary = (
                f"，承诺 {len(rows)} 项比对，{placed} 项已落正文"
                + (f"，{len(warn_lines)} 项未落正文" if warn_lines else "")
            )
    warn_lines.extend(dup_warns)
    if broken:
        warn_lines.append(
            "损坏节（无法按终稿视角读取，已跳过、未参与比对/查重）：" + "、".join(broken)
            + "——删除重建或人工核查"
        )

    head = (
        f"[校验通过] body 全局：{len(sections)} 节正文{promise_summary}"
        if skip_note is None
        else f"[校验通过] body 全局：{skip_note}"
    )
    if dup_warns:
        head += f"，节间查重 {len(dup_warns)} 对疑似重复"
    return "\n".join([head] + [f"⚠️ {m}" for m in warn_lines])


@tool
def validate_body(section: str, block_ids: list[str] | None = None) -> str:
    """机器校验正文产物：写作指引表 / 单节正文 / body 全局承诺比对+节间查重。

    写完指引后传 section="body/写作指引.md" 校验表完整性（每节有行/模式合法/
    素材块可解析/素材不跨节复用——同块派多节直接判不过：注入两节=正文逐字重复，
    拆块或只留一节用块）；写完一节正文后传该节路径与使用计划选用的素材块 id
    （docx 节按接受全部修订后的终稿视角校验，docx_comment_add 落的待办批注清点进
    收尾点名、内联占位判不过；定位段落为 P 段号、表格行为 T 行号；旧 .md 节兼容）；
    整本收尾传 section="body"（目录）跑全局承诺比对与节间查重——承诺清单每个值
    未在任何正文出现、两节内容大面积重叠（同一素材进多节/原文照搬）都会被点名。
    [校验通过] 才算该节完成；[校验未通过] 逐条给出
    「文件:行号 现状→修复」。校验是纪律不是门禁，不阻塞流程——但收尾汇报前
    必须全部通过。只读、幂等。
    Args:
        section: work/ 下的相对路径（如 body/写作指引.md、body/技术部分/3.1
                 项目理解.docx）；传 "body" 触发全局承诺比对
        block_ids: 本节使用计划选用的素材块 id（blk_…，search_references 的
                   evidence 里带；校验指引与全局模式时忽略）
    """
    try:
        ctx = runctx.current_run()
        task_id = ctx.task_id if ctx else None
        if not task_id:
            return "[校验失败] 缺少任务上下文：正文产物在当前任务的 work/body/ 下"

        raw = (section or "").strip()
        pure = PurePosixPath(raw)
        if not raw or raw.startswith("/") or ".." in pure.parts:
            return "[校验失败] section 须为 work/ 下的相对路径（如 body/写作指引.md）"
        wroot = work_dir(task_id).resolve()
        p = (wroot / raw).resolve()
        if not p.is_relative_to(wroot):
            return "[校验失败] 路径越界：section 须在 work/ 内"
        if p.is_dir():
            return _validate_body_global(p)
        if not p.exists():
            return f"[校验失败] {raw} 不存在"
        if p.suffix == ".docx":
            # docx 节：终稿视角文本（接受全部修订后），批注/占位定位段落 P 段号、表格行 T 行号
            doc = Document(str(p))
            labeled = section_lines_labeled(doc)
            issues, warnings, notes = _validate_section(
                [t for _, t in labeled], block_ids, labels=[lbl for lbl, _ in labeled], docx=True
            )
            # 待办批注清点（docx_comment_add 落的待办——收尾汇报逐条点名，不是门禁）
            notes.extend(
                f"{loc}〔批注〕：{t[:50]}{'…' if len(t) > 50 else ''}"
                for loc, t in section_comments_labeled(doc)
            )
        elif p.suffix == ".md":
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if pure.name == "写作指引.md" and "body" in pure.parts:
                issues, warnings, notes = _validate_guide(lines, task_id)
            else:
                issues, warnings, notes = _validate_section(lines, block_ids)
        else:
            return "[校验失败] 只支持 .md/.docx 正文文件（或传 body 跑全局比对）"

        head = f"[校验通过] {raw}" if not issues else (
            f"[校验未通过] {raw} 共 {len(issues)} 处问题（按提示修复后重新运行 validate_body，全部通过才算完成）："
        )
        parts = [head]
        parts.extend(f"- {i}" for i in issues)
        parts.append(f"[待办批注/占位] 共 {len(notes)} 处（收尾汇报逐条点名，不得只字不提）："
                     if notes else "[待办批注/占位] 无")
        parts.extend(f"- {n}" for n in notes)
        parts.extend(f"⚠️ {w}" for w in warnings)
        return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"[校验失败] {type(e).__name__}: {e}"
