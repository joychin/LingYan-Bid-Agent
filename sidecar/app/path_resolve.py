"""模型可达路径的统一解析单点（2026-09-15 路径可靠性批）。

路径类事故反复出现的第三种失败模式是「防线点状、各管一段」：文件工具的坏路径
换算在 agent._PathRescueMiddleware、面板接口的后缀兜底在 api/workbench、解析/
发布/docx 各有自有约定——新工具或新链路不接防线就静默绕过（当日实证：>200 字
派发描述绕过拼装器，写手自选路径致合册 46/59）。本模块两件事：

1. 收拢两份可复用的纯机械逻辑（**行为零变化**，原调用方改为引用，两侧既有测试
   不动即等价证明）：
   - norm_candidates：文件工具坏路径的换算候选序（原 agent._path_rescue_candidates）
   - unique_suffix_match：work/ 全树唯一后缀兜底（原 api/workbench._unique_suffix_match）
2. PATH_RESOLVER_REGISTRY 登记表：每个「模型可达的路径参数」由哪套解析器负责。
   守卫测试（tests/test_path_resolve.py）扫 TOOLS 参数与登记表对账——新增带路径
   参数的工具不登记当场红，防线覆盖从「记得」变「测试」。

原则（本批拍板）：结构性路径（输出落点）由机器推导、模型只消费（dispatch_enrich
注入输出路径）；探索性路径过解析器、打错也能活。docx_ops._dest_path 等领域解析
器工作正常、原地不动，只登记（搬动徒增风险）；登记值=可 import 的点路径，
「内联在工具体里」的解析登记工具函数本身。
"""

from __future__ import annotations

import re
from pathlib import Path

# 文件工具换算时视为「全局共享、不带任务前缀」的顶层目录（罗盘三行同款口径）
RESCUE_GLOBAL_DIRS = ("skills", "materials", "knowledge")


def norm_vpath(path: str) -> str | None:
    """模型给的路径归一为虚拟绝对路径（"/x/y"）；带穿越段/家目录则 None（不碰）。"""
    p = "/" + path.strip().lstrip("/")
    segments = p.split("/")
    if ".." in segments or "~" in segments:
        return None
    return p


def norm_candidates(path: str, task_id: str, workspace_root: str) -> list[str]:
    """坏路径的换算候选（确定性、按序、去重、规则可叠两层）。

    覆盖实测四类猜错形态：①多余 /workspace 段；②拼了本机真实根前缀；③缺任务
    前缀（主形态，14 次）；④任务前缀误套在全局目录前。两层叠加处理复合形态
    （/真实根/work/x → /work/x → /t_x/work/x；/workspace/t_x/skills/ → → /skills/）。
    """
    norm = norm_vpath(path)
    if norm is None:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def push(cand: str | None) -> None:
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)

    def rules(p: str) -> list[str]:
        results: list[str] = []
        if p.startswith("/workspace/"):
            results.append(p[len("/workspace"):])
        if workspace_root and p.startswith(workspace_root):
            results.append(p[len(workspace_root):] or "/")
        if task_id and not p.startswith(f"/{task_id}/"):
            results.append(f"/{task_id}{p}")
        if task_id:
            parts = p.lstrip("/").split("/", 1)
            if (
                len(parts) == 2
                and parts[0] == task_id
                and parts[1].split("/", 1)[0] in RESCUE_GLOBAL_DIRS
            ):
                results.append("/" + parts[1])
        return results

    for first in rules(norm):
        push(first)
        for second in rules(first):
            push(second)
    return out


def unique_suffix_match(root: Path, path: str, task_id: str) -> Path | None:
    """work/ 全树唯一后缀兜底：模型给的路径（ask_human guide_path 等）可能少前缀
    （body/ 下相对）或多前缀（work/、<task_id>/）。剥掉已知前缀后在全树找以剩余
    路径结尾的唯一真实文件（按路径边界匹配，防 asub/x.md 误中 sub/x.md）；
    无命中或歧义返回 None——维持精确路径的原有行为（下游 404）。
    """
    parts = path.split("/")
    while parts and parts[0] in ("work", task_id):
        parts.pop(0)
    cleaned = "/".join(parts)
    if not cleaned:
        return None

    def _hit(p: Path) -> bool:
        if not p.is_file() or p.suffix not in (".md", ".docx") or p.name.startswith("."):
            return False
        parts = p.relative_to(root).parts
        if parts and parts[0] == "artifacts":  # 产物包文件走产物卡通道，不参与后缀兜底
            return False
        rel = "/".join(parts)
        return rel == cleaned or rel.endswith("/" + cleaned)

    hits = [p for p in root.rglob("*") if _hit(p)]
    return hits[0] if len(hits) == 1 else None


# ── 登记表：模型可达路径参数 → 解析器（点路径，守卫测试逐一验证可 import）──
# 职责划分：
# - fs 六件套：norm_candidates 事前换算（经 agent._PathRescueMiddleware 挂载）+
#   GuardedBackend 越界/保护区拒——两层各管一半，这里登记换算层；
# - docx/parse/publish/validate：领域解析器原地不动（自有约定：body/ 前缀、
#   staging containment 等），登记其入口；
# - workbench API 读端点：api/workbench._resolve（精确→唯一后缀兜底）；
# - ask_human.guide_path：前端「打开指引」按钮经 workbench 端点解析。
PATH_RESOLVER_REGISTRY: dict[str, dict[str, str]] = {
    "ls": {"path": "app.path_resolve.norm_candidates"},
    "glob": {"path": "app.path_resolve.norm_candidates"},
    "grep": {"path": "app.path_resolve.norm_candidates"},
    "read_file": {"file_path": "app.path_resolve.norm_candidates"},
    "write_file": {"file_path": "app.path_resolve.norm_candidates"},
    "edit_file": {"file_path": "app.path_resolve.norm_candidates"},
    "parse_document": {"path": "app.tools.parse_document._resolve_ws_path"},
    "publish_artifact": {"draft_path": "app.tools.publish._resolve_draft"},
    "validate_body": {"section": "app.tools.validate_body.validate_body"},  # 解析内联在工具体（work/ containment）
    "ask_human": {"guide_path": "app.api.workbench._resolve"},  # 前端按钮经面板端点解析
    "docx_section_create": {"path": "app.tools.docx_ops._dest_path"},
    "docx_section_read": {"path": "app.tools.docx_ops._dest_path"},
    "docx_section_revise": {"path": "app.tools.docx_ops._dest_path"},
    "docx_comment_add": {"path": "app.tools.docx_ops._dest_path"},
    "docx_material_inject": {"dest": "app.tools.docx_ops._dest_path"},
    "docx_source_inject": {
        "source": "app.tools.docx_ops.docx_source_inject",  # 剥目录、sources/ basename（内联）
        "dest": "app.tools.docx_ops._dest_path",
    },
    "docx_image_insert": {
        "dest": "app.tools.docx_ops._dest_path",
        "image": "app.tools.docx_ops.docx_image_insert",  # sources/knowledge 归一+containment（内联）
    },
    "docx_diagram_insert": {"dest": "app.tools.docx_ops._dest_path"},
    "docx_html_figure": {"dest": "app.tools.docx_ops._dest_path"},
}

# 参数名命中路径类模式、但语义不是文件系统路径的显式例外（新增须带理由注释）
REGISTRY_IGNORE: dict[str, set[str]] = {
    "check_name_residue": {"source_item_id"},  # 知识库条目 id，非路径
}

# 守卫测试用它扫 TOOLS 参数：命中即必须登记（或进 REGISTRY_IGNORE）
PATH_PARAM_RE = re.compile(r"path|file|dir|dest|source|draft|section|image")
