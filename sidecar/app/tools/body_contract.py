"""tender-body 正文阶段的路径与格式契约（check_pipeline / validate_body / SKILL.md 共用真值）。

目录产物（tender.directory）的树节点没有稳定 id——身份就是标题文本；正文文件与
节点的映射因此按「清洗后的标题」对账（清洗规则在此单一实现，工具与技能文档引用
同一份约定）。标题改版后失配由 check_pipeline 的 [body] 段报事实、用户裁决，
不做锁定（无锁铁则：探测 + 提示裁决 + 恢复点兜底）。
"""

from __future__ import annotations

import json
import re

# 写作指引 / 承诺清单固定落点（相对 work/）
GUIDE_RELPATH = "body/写作指引.md"
PROMISE_RELPATH = "body/关键事实与承诺.md"

# 写作模式枚举（指引表「模式」列的合法取值，「+」组合）
MODES = ("素材修订", "格式跟随", "推理撰写")

# 无需正文文件的交付形态（模板填充走待填清单、容器不写）
NON_PROSE_DELIVERY = ("模板或附件填充", "目录容器")

# 正文内联占位前缀——2026-09-08 起待办的正规落点是 Word 批注（docx_comment_add），
# 正文禁止占位文字；本表仅作兜底扫描口径（validate_body 点名 + 合册 ⚠️ 警告）。
# 【缺】不在此列：它只用于写作指引表的素材列（指引是 md，合法占位）。
PLACEHOLDER_MARKS = ("【待补", "【待澄清", "【待补充")

_ILLEGAL = re.compile(r"[\\/:*?\"<>|\r\n\t]")


def sanitize_name(title: str, limit: int = 60) -> str:
    """标题 → 文件名/目录名：非法字符替换空格、折叠空白、截断。

    清洗是对账的公共分母——工具按同一规则清洗两侧（叶子标题 vs 文件名）再比，
    因此规则变化只允许发生在这里。
    """
    s = _ILLEGAL.sub(" ", title or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit].strip() or "未命名"


def _iter_nodes(tree: list[dict]):
    for n in tree:
        yield n
        yield from _iter_nodes(n.get("children") or [])


def iter_leaves(content: dict) -> list[tuple[str, str, str]]:
    """产出 (册名, 节点标题, 交付形态)——每册目录树的叶子节点（无子节点）。

    防御性解析：目录/children 键可能缺失（产物内容是原始 dict 序列化，Pydantic
    只验证不物化默认值）。
    """
    out: list[tuple[str, str, str]] = []
    for doc in content.get("response_documents") or []:
        vol = str(doc.get("name") or "").strip() or "主册"
        for n in _iter_nodes(doc.get("directory") or []):
            if n.get("children"):
                continue
            title = str(n.get("目录名称") or "").strip()
            if title:
                out.append((vol, title, str(n.get("交付形态") or "").strip()))
    return out


def multi_volume(content: dict) -> bool:
    """多册判定：有目录树的响应文件多于一份。"""
    docs = content.get("response_documents") or []
    return len([d for d in docs if d.get("directory")]) > 1


def prose_leaves(content: dict) -> list[tuple[str, str, str]]:
    """需要正文文件的叶子：交付形态为 正文编写/混合/待核验/空（空=未标注，技能裁决）。"""
    return [
        (vol, title, mode)
        for vol, title, mode in iter_leaves(content)
        if mode not in NON_PROSE_DELIVERY
    ]


def load_directory(task_id: str):
    """取任务内当前投标目录产物：(索引行, 内容 dict, content.json mtime)。

    无产物返回 (None, None, None)；包内容不可读返回 (row, None, None)
    ——调用方按事实报告，不在此裁决。
    """
    from .. import artifact_store, db

    row = db.find_artifact_index("tender.directory", "tender-response-docs", 1, task_id=task_id)
    if not row:
        return None, None, None
    p = artifact_store.content_path(row["artifact_id"], row)
    try:
        content = json.loads(p.read_text(encoding="utf-8"))
        mtime = p.stat().st_mtime
    except (OSError, json.JSONDecodeError, ValueError):
        return row, None, None
    return row, content, mtime
