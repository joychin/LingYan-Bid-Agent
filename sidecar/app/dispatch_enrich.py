"""tender-body-writer 派发说明程序化拼装（2026-09-08 token 治理批）。

动因：主代理派发说明塌成节名五～十字（SKILL「必带清单缺一不派」是纪律，管不住
模型行为方差——2026-09-08 实测 32/32 派发仅 7~10 字符），子代理被迫开局自救：
521 次 ls/grep/read 重建本该一句话给到的上下文，读回的全文再被此后 ~26 轮逐轮
重发（占整本 14.5M 输入 token 的约六成）。修法=派发契约从纪律升机制：task 调用
进 sidecar 时（agent.py _DispatchEnrichMiddleware）把共享上下文程序拼进
description——任务前缀/输出路径/指引行/要求清单（registry 解析为原文+出处）/
承诺清单全部值/兄弟节摘要，写手开局只读方法论一份。

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
import logging
import re
from datetime import date

from . import artifact_store
from .tools import body_contract, docx_ops

# 注意：assemble_tender 在 tools/__init__ 里被同名 @tool 对象遮蔽，私有函数须走模块路径
from .tools.assemble_tender import _norm_id
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
    vdir = artifact_store.work_dir(task_id) / "body" / (vol if multi else "")
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
        rel = f"body/{vol + '/' if multi else ''}{body_contract.sanitize_name(title)}.docx"

        req_lines: list[str] = []
        has_tpl = False
        mode = ""
        mat = ""
        guide = _guide_row(task_id, content, vol, title)
        if guide is not None:
            cells, cols = guide
            req_lines, has_tpl = _requirement_lines(cells, cols, content.get("registry") or {})
            mode = cells[cols["模式"]].strip() if "模式" in cols else ""
            if "素材" in cols and cols["素材"] < len(cells):
                mat = cells[cols["素材"]].strip()

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
        if mat and mat != "—":
            out.append(f"可用素材块：{mat}")
        promises = _promise_lines(task_id)
        out.append("承诺清单全部值（承诺类数字只能用这里）：")
        out.extend(promises or ["（清单文件缺失或为空——缺项一律写【待澄清：…】不得编造）"])
        sibs = _sibling_lines(task_id, content, vol, title)
        if sibs:
            out.append("兄弟节开头摘要（避免重复展开）：")
            out.extend(sibs)
        return "\n".join(out)
    except Exception:
        logger.debug("派发说明拼装失败，放行原文（task=%s）", task_id, exc_info=True)
        return None
