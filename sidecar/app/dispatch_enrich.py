"""tender-body-writer 派发说明程序化拼装（2026-09-08 token 治理批）。

动因：主代理派发说明塌成节名五～十字（SKILL「必带清单缺一不派」是纪律，管不住
模型行为方差——2026-09-08 实测 32/32 派发仅 7~10 字符），子代理被迫开局自救：
521 次 ls/grep/read 重建本该一句话给到的上下文，读回的全文再被此后 ~26 轮逐轮
重发（占整本 14.5M 输入 token 的约六成）。修法=派发契约从纪律升机制：task 调用
进 sidecar 时（agent.py _DispatchEnrichMiddleware）把共享上下文程序拼进
description——任务前缀/输出路径/指引行/要求清单（registry 解析为原文+出处）/
素材块逐块名片（标题/字数/含图/来源文件/备注——指引期检索的内容层复用，写手
据此直接列使用计划，不再每节重检索一遍素材库）/缺口列原文（指引期知识库命中的
公司事实与缺料点名，2026-09-10 接线——此前该列零消费，检索命中沉淀不进派发，
资质/基本情况类节的公司事实对写手不可见）/承诺清单全部值/兄弟节摘要，
写手开局只读方法论一份。

契约与边界：
- 只对 tender-body-writer 生效（中间件三层过滤：工具名/子代理名/任务上下文）；
- 节名对不上目录叶子、或一节多义时原样放行（宁可不猜——拼错节的说明比瘦说明更糟）；
- 产出文本零 REQ/MAND/SCORE/TPL 编号（2026-09-08 派发契约：编号会被写手镜像
  进正文首句）；依据列 ID 由 registry 解析为「要求原文+出处」后即弃；
- 拼装块除天级「今天日期」行外无时间戳、同子代理 run 内字节稳定（前缀缓存
  铁律；日期与任务上下文块同精度——写手子代理不继承任务上下文拿不到日期，
  模型自编日期不可信，封面/投标函落款用这行）；兄弟摘要随派发时点
  变化，但那属于各子代理自己的独立前缀，不伤共享前缀；
- 任何内部异常一律放行原文，绝不打断 run。
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import date

from . import artifact_store, config, db
from .tools import body_contract, docx_ops

# 注意：assemble_tender 在 tools/__init__ 里被同名 @tool 对象遮蔽，私有函数须走模块路径
from .tools.assemble_tender import _norm_id
from .tools.search_knowledge import _mt_image_count
from .tools.validate_analysis import _iter_tables
from .tools.validate_body import _parse_guide_rows

logger = logging.getLogger(__name__)

_ENRICH_MARK = "〔系统附"  # 幂等标记：含此标记的描述（重派/续跑再走一层）不再拼装
_MAX_ORIG_DESC = 200  # 模型已写富文本的稀有情況：信任原文，不重复拼装
_MAX_SIBLINGS = 3  # 兄弟摘要上限（防派发随波数线性膨胀）
_SIBLING_HEAD_CHARS = 200
_ID_RE = re.compile(r"^(?:MAND|TPL|REQ|SCORE)-\d+$", re.IGNORECASE)
_WRAPPER_RE = re.compile(r"^(?:重写|续写|新写|撰写|补写|写)\s*")
_TAIL_RE = re.compile(r"(?:的)?(?:节|章节|小节|正文)$")

# 写作纪律内联（2026-09-12）：写手子代理 spec 无 skills 字段（deepagents 的
# SkillsMiddleware 只挂主代理），故每个写手开局都要 read_file 读一遍
# section-writing.md——实测全库该文件被读 215 次、其中 205 次在子代理，每次都是一个
# 完整往返 + 约 3.2K token 回灌。改为主代理派发时把这份方法论直接附进任务描述。
# 进程内缓存：文件内容部署期固定（改技能需重启），跨派发复用同一字符串
# （单 run 内字节稳定，遵守前缀缓存铁律）。
_SKILL_DOC = ("tender-body", "references/section-writing.md")
_skill_cache: str | None = None


def _skill_text() -> str | None:
    """写手方法论全文（section-writing.md）；不可用时返回 None（调用方跳过该段）。

    读失败只损失这一段内联，绝不影响其余拼装（与 _material_lines 等降级同款）。
    """
    global _skill_cache
    if _skill_cache is not None:
        return _skill_cache
    try:
        path = config.skills_source_dir().joinpath(*_SKILL_DOC)
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        _skill_cache = text
        return text
    except Exception:
        logger.debug("写手方法论内联读取失败，跳过该段", exc_info=True)
        return None


def _needle(desc: str) -> str:
    """派发描述 → 节名探针：剥「重写/写」类前缀与「节」类后缀。"""
    s = _WRAPPER_RE.sub("", desc.strip())
    s = _TAIL_RE.sub("", s)
    return s.strip() or desc.strip()


def _match_leaf(needle: str, leaves: list[tuple[str, str, str]]) -> tuple[str, str, str] | None:
    """探针对账目录叶子：精确相等 > 包含 > 近似（缩写容忍，如「低代码产品方案」
    命中「低代码开发平台产品方案」），近似需显著唯一（头两名分差 ≥0.10）。

    返回 (册名, 标题, 交付形态)；0 命中或歧义返回 None——放行原文不猜。
    """
    scored: list[tuple[float, str, str, str]] = []
    for vol, title, delivery in leaves:
        st = body_contract.sanitize_name(title)
        if not needle:
            continue
        if needle == st:
            scored.append((2.0, vol, title, delivery))
        elif needle in st or st in needle:
            scored.append((1.0, vol, title, delivery))
        else:
            ratio = difflib.SequenceMatcher(None, needle, st).ratio()
            if ratio >= 0.55:
                scored.append((ratio, vol, title, delivery))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.10:
        return None  # 两个候选难分伯仲：多义，放行
    _, vol, title, delivery = scored[0]
    return vol, title, delivery


def _guide_row(
    task_id: str, content: dict, vol: str, title: str
) -> tuple[list[str], dict[str, int]] | None:
    """匹配叶子的指引行 (cells, 列名→下标)；无指引文件或无对应行返回 None。

    多册时指引「节」列是「册名/标题」复合（与 check_pipeline [body] 同款拆分）。
    """
    p = artifact_store.work_dir(task_id) / body_contract.GUIDE_RELPATH
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    multi = body_contract.multi_volume(content)
    wvol = body_contract.sanitize_name(vol)
    wtitle = body_contract.sanitize_name(title)
    for _lineno, cells, cols in _parse_guide_rows(lines):
        raw = cells[cols["节"]].strip()
        gvol, gtitle = "", raw
        if multi and "/" in raw:
            head, _, tail = raw.partition("/")
            gvol, gtitle = head.strip(), tail.strip()
        if multi:
            if body_contract.sanitize_name(gvol) == wvol and body_contract.sanitize_name(gtitle) == wtitle:
                return cells, cols
        elif body_contract.sanitize_name(gtitle) == wtitle:
            return cells, cols
    return None


def _requirement_lines(cells: list[str], cols: dict[str, int], registry: dict) -> tuple[list[str], bool]:
    """依据列 ID → 「要求原文+出处」行（编号解析后即弃）；返回 (行, 是否含格式件)。"""
    key = cols.get("依据")
    raw = cells[key].strip() if key is not None and key < len(cells) else ""
    ids = [_norm_id(t.upper()) for t in re.split(r"[、,，;；\s]+", raw) if _ID_RE.match(t)]
    out: list[str] = []
    has_tpl = False
    for i in ids:
        e = registry.get(i)
        text = str((e or {}).get("text") or "").strip()
        if not text:
            logger.debug("派发拼装：依据 %s 在目录产物 registry 无对应行，跳过", i)
            continue
        if str((e or {}).get("type") or "") == "模板":
            has_tpl = True
        src = str((e or {}).get("出处") or "").strip() or "—"
        out.append(f"- {text}（出处：{src}）")
    return out, has_tpl


def _promise_lines(task_id: str) -> list[str]:
    """承诺清单「事项|值|说明」全部行（派发契约：承诺值必须随派发全量送达）。"""
    p = artifact_store.work_dir(task_id) / body_contract.PROMISE_RELPATH
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for _start, _header, body in _iter_tables(lines):
        for _lineno, cells in body:
            if len(cells) < 2 or not cells[0].strip():
                continue
            line = f"- {cells[0].strip()}：{cells[1].strip()}"
            note = cells[2].strip() if len(cells) > 2 else ""
            if note and note != "—":
                line += f"（{note}）"
            out.append(line)
    return out


def _sibling_lines(task_id: str, content: dict, vol: str, own_title: str) -> list[str]:
    """同册已写节的开头摘要（mtime 降序 ≤3 个，排除自己与整本合册）。"""
    multi = body_contract.multi_volume(content)
    # 册名清洗后拼路径（实际落点=docx_assemble_volume/check_pipeline 的 sanitize_name
    # 口径；原样拼接在册名含 /: 等字符时指错目录——摘要静默空、路径行误导）
    vdir = artifact_store.work_dir(task_id) / "body" / (body_contract.sanitize_name(vol) if multi else "")
    if not vdir.is_dir():
        return []
    own = body_contract.sanitize_name(own_title) + ".docx"
    try:
        files = [f for f in vdir.glob("*.docx") if f.name != own and not f.name.startswith("整本-")]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return []
    out: list[str] = []
    for f in files[:_MAX_SIBLINGS]:
        try:
            head = docx_ops.head_text(f, _SIBLING_HEAD_CHARS)
        except Exception:
            continue  # 兄弟文件损坏：摘要缺一行不打断派发
        if head:
            out.append(f"- {f.stem}：{head}")
    return out


def _material_lines(mat: str) -> list[str] | None:
    """素材列 blk id → 逐块名片（标题/字数/含图/来源文件/备注）。

    指引期检索的内容层复用：此前派发只传 id 字符串，写手不知块内是什么、
    被迫每节再 search_references 一遍（2026-09-10 收口——名片够列使用计划，
    全文走 docx_material_inject 注入后经读视图可见）。素材列无任何 blk id
    （【缺】/—）返回 None，调用方维持旧行；查不到的 id 以失效提示降级
    （写手自行检索）。来源文件名必须随行——改写后 check_name_residue 扫
    旧机构名的 old_names 取自它。
    """
    ids = [t for t in re.split(r"[、,，;；\s]+", mat) if t.startswith("blk_")]
    if not ids:
        return None
    files = {f["id"]: f for f in db.mt_list_files()}
    blocks_by_id = {b["id"]: b for b in db.mt_list_blocks()}
    out: list[str] = []
    for bid in ids:
        b = blocks_by_id.get(bid)
        if not b:
            out.append(f"- {bid}（已失效——请自行检索确认）")
            continue
        f = files.get(b.get("file_id"))
        src = f["file_name"] if f else "（来源文件已删除）"
        img = _mt_image_count(src, b.get("ranges")) if f else 0
        img_bit = f"，含图 {img} 处" if img else ""
        line = f"- 《{b['title']}》（约 {b.get('chars') or 0:,} 字{img_bit}）｜来源文件：{src}｜id：{bid}"
        if b.get("note"):
            line += f"｜备注：{b['note']}"
        out.append(line)
    return out


_GAP_COL_KEYS = ("缺口", "备注")  # 指引缺口列表头名变体（契约名「缺口/备注」）
_BARE_ID_RE = re.compile(r"(?:MAND|TPL|REQ|SCORE)-\d+")

# 原件定位：标记与核心名提取（2026-09-10）。标记=附件N/附表N/表N（限 1-3 位
# 数字、后不接年月日防「报表2026年」误报）；核心名=剥标记与全部标点空白。
_LOC_MARK_RE = re.compile(r"(?:附件|附表|表)\s*(\d{1,3})(?![0-9年月日])")
_LOC_NOISE_RE = re.compile(r"[\s（）()【】\[\]：:、，,。．.；;！!？?\-—_/·]+")


def _core_name(s: str) -> tuple[str, tuple[str, ...]]:
    """标题 → (清洗核心名, 标记元组)：匹配比较用的稳定键。"""
    marks = tuple(re.sub(r"\s+", "", m.group(0)) for m in _LOC_MARK_RE.finditer(s))
    core = _LOC_NOISE_RE.sub("", _LOC_MARK_RE.sub("", s))
    return core, marks


def _source_location_line(task_id: str, leaf_title: str) -> str | None:
    """节名 → 「原件定位」行：在全部已解析来源的 outline.json 标题树里唯一定位
    该节对应的原件区段（2026-09-10）。

    动因：格式跟随/格式件节的写手此前要自己找「附件14」在哪——grep outline +
    读原文试探，实测最重节 71 轮里约 40 轮在找位置。匹配保守：标记（附件N/
    表N）双现且核心相容，或清洗核心名全等；跨全部文件唯一命中才带行，0 命中
    或歧义返回 None（宁可不带——定位错比不带更糟）。同文件内相邻（间距 ≤2 行）
    的命中合并区间（「表1：报价表」标题壳与正文条目两节点的常见形态）。
    """
    core_leaf, marks_leaf = _core_name(leaf_title)
    if not core_leaf and not marks_leaf:
        return None
    pdir = artifact_store.work_dir(task_id) / "parse"
    if not pdir.is_dir():
        return None
    hits: list[tuple[str, str, int, int]] = []  # (文件名, 条目标题, 起, 止)
    for outline_path in sorted(pdir.glob("*/*.outline.json")):
        try:
            tree = json.loads(outline_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        fname = outline_path.name[: -len(".outline.json")]
        stack = list(tree) if isinstance(tree, list) else []
        while stack:
            n = stack.pop()
            if not isinstance(n, dict):
                continue
            title = str(n.get("标题") or "")
            s, e = n.get("start_line") or 0, n.get("end_line") or 0
            if title and isinstance(s, int) and isinstance(e, int) and s and e:
                core_e, marks_e = _core_name(title)
                shared = set(marks_leaf) & set(marks_e)
                if shared and (not core_leaf or not core_e or core_leaf in core_e or core_e in core_leaf):
                    hits.append((fname, title, s, e))
                elif core_leaf and core_e and core_leaf == core_e:
                    hits.append((fname, title, s, e))
            stack.extend(n.get("children") or [])
    if not hits:
        return None
    by_file: dict[str, list[tuple[str, int, int]]] = {}
    for fname, title, s, e in hits:
        by_file.setdefault(fname, []).append((title, s, e))
    spans: list[tuple[str, str, int, int]] = []
    for fname, items in by_file.items():
        items.sort(key=lambda x: x[1])
        first, cur_s, cur_e = items[0]
        for title, s, e in items[1:]:
            if s - cur_e <= 2:
                cur_e = max(cur_e, e)
            else:
                spans.append((fname, first, cur_s, cur_e))
                first, cur_s, cur_e = title, s, e
        spans.append((fname, first, cur_s, cur_e))
    if len(spans) != 1:
        return None  # 跨文件或同文件多处命中：歧义不带
    fname, title, s, e = spans[0]
    return (
        f"原件定位：{fname} L{s}-L{e}（{title}）——docx_source_inject 的 lines 参数"
        "直接用此区间；核对原文可按同区间 read_file 解析 md"
    )


def _gap_lines(cells: list[str], cols: dict[str, int]) -> str | None:
    """指引缺口列 → 「公司材料与缺口」段原文（整段透传，程序不解析格式）。

    缺口列由指引期知识库检索写入（【知识库】命中事实 + 【缺：…】未命中点名，
    见 guide-format.md）；这里只做机械透传。四类招标编号剥除（零编号派发契约：
    模型可能把依据列编号抄进缺口列，编号镜像进正文即泄漏）；CLAR 类澄清编号
    不剥——不是招标条款引用，写手需原样带回待办。
    """
    key = next((k for k in cols if any(x in k for x in _GAP_COL_KEYS)), None)
    if key is None:
        return None
    idx = cols[key]
    if idx >= len(cells):
        return None
    raw = cells[idx].strip()
    if not raw or raw in ("—", "无"):  # 「无」=中文指引常见占位，非内容
        return None
    text = _BARE_ID_RE.sub("", raw)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[（(]\s*[、，;；]?\s*[）)]", "", text)  # 删编号后残留的空括号
    return text or None


def build_enriched_description(desc: str, task_id: str) -> str | None:
    """瘦派发描述 → 补全派发说明；不适合拼装返回 None（调用方原样放行）。

    模型原话永远第一行（UI 子代理卡标题取首行）；其后是程序拼的共享上下文块。
    """
    try:
        if not isinstance(desc, str) or not desc.strip() or _ENRICH_MARK in desc:
            return None
        if len(desc) > _MAX_ORIG_DESC:
            return None
        _row, content, _mtime = body_contract.load_directory(task_id)
        if not content:
            return None
        leaves = body_contract.iter_leaves(content)
        if not leaves:
            return None
        match = _match_leaf(_needle(desc), leaves)
        if match is None:
            return None
        vol, title, delivery = match
        multi = body_contract.multi_volume(content)
        rel = f"body/{body_contract.sanitize_name(vol) + '/' if multi else ''}{body_contract.sanitize_name(title)}.docx"

        req_lines: list[str] = []
        has_tpl = False
        mode = ""
        mat = ""
        gap = None
        loc = None
        guide = _guide_row(task_id, content, vol, title)
        if guide is not None:
            cells, cols = guide
            req_lines, has_tpl = _requirement_lines(cells, cols, content.get("registry") or {})
            mode = cells[cols["模式"]].strip() if "模式" in cols else ""
            if "素材" in cols and cols["素材"] < len(cells):
                mat = cells[cols["素材"]].strip()
            gap = _gap_lines(cells, cols)
        try:
            loc = _source_location_line(task_id, title)
        except Exception:
            logger.debug("派发拼装：原件定位解析失败，跳过该行", exc_info=True)

        out = [
            desc.strip(),
            f"{_ENRICH_MARK}：本节派发上下文（程序自动生成，直接使用；"
            "无需再读 写作指引/关键事实与承诺，也无需 check_pipeline_state）",
            f"任务目录前缀：{task_id}/",
            f"输出路径：{task_id}/work/{rel}",
            # 天级日期（写手子代理不继承任务上下文块拿不到日期，模型自编日期
            # 不可信——封面/投标函等落款用这行；单日内字节稳定，前缀缓存无伤）
            f"今天日期：{date.today().isoformat()}",
        ]
        if mode and mode != "—":
            out.append(f"写作模式：{mode}")
        elif delivery:
            out.append(f"交付形态：{delivery}（指引无对应行，按目录节点形态处理）")
        if req_lines:
            out.append("要求清单（正文呼应要求本身或招标文件真实章节条款号）：")
            out.extend(req_lines)
            if has_tpl:
                out.append(
                    "本节含格式件：从 sources/ 招标原件拷贝（docx_source_inject；"
                    "pdf 原件无可拷元素，按解析文本自行成形）。"
                )
        if loc:
            out.append(loc)
        if mat and mat != "—":
            try:
                mat_lines = _material_lines(mat)
            except Exception:
                logger.debug("派发拼装：素材块名片解析失败，降级 id 原文", exc_info=True)
                mat_lines = None
            if mat_lines:
                out.append("可用素材块（直接据此列使用计划并注入，无需再检索）：")
                out.extend(mat_lines)
            else:
                out.append(f"可用素材块：{mat}")
        if gap:
            out.append(
                "公司材料与缺口（指引缺口列原文；【知识库】=知识库命中的公司事实，"
                "证书数字照抄不得改写；【缺】=库里没有，加批注待办，禁止编造）："
            )
            out.append(gap)
        promises = _promise_lines(task_id)
        out.append("承诺清单全部值（承诺类数字只能用这里）：")
        out.extend(promises or ["（清单文件缺失或为空——缺项一律写【待澄清：…】不得编造）"])
        sibs = _sibling_lines(task_id, content, vol, title)
        if sibs:
            out.append("兄弟节开头摘要（避免重复展开）：")
            out.extend(sibs)
        # 写作方法论内联：写手子代理没有 SkillsMiddleware，此前每节都要自己
        # read_file 读一遍（205 次实测）；这段已在任务描述里，开局不必再读。
        skill = _skill_text()
        if skill:
            out.append(
                "写作纪律（完整方法论已在下方给出——**不要再 read_file "
                "section-writing.md**，直接照此执行）："
            )
            out.append(skill)
        return "\n".join(out)
    except Exception:
        logger.debug("派发说明拼装失败，放行原文（task=%s）", task_id, exc_info=True)
        return None
