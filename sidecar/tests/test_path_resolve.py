"""路径解析登记表守卫（2026-09-15 路径可靠性批）。

防线覆盖从「记得」变「测试」：凡模型可达的工具带路径类参数，必须登记进
app/path_resolve.py 的 PATH_RESOLVER_REGISTRY（或进 REGISTRY_IGNORE 并带理由）；
登记的解析器点路径必须真实可 import（防登记成摆设）。新工具不接线当场红。
"""

import importlib

from app.path_resolve import (
    PATH_PARAM_RE,
    PATH_RESOLVER_REGISTRY,
    REGISTRY_IGNORE,
    norm_candidates,
    norm_vpath,
)
from app.tools import TOOLS


def test_every_tool_path_param_is_registered():
    """扫全部注册工具的参数名：命中路径类模式却未登记/未豁免 → 当场点名。"""
    missing = []
    for t in TOOLS:
        ignored = REGISTRY_IGNORE.get(t.name, set())
        for pname in (t.args or {}):
            if PATH_PARAM_RE.search(pname) and pname not in ignored:
                if PATH_RESOLVER_REGISTRY.get(t.name, {}).get(pname) is None:
                    missing.append(f"{t.name}.{pname}")
    assert not missing, (
        f"未登记的路径参数：{missing}——登记进 app/path_resolve.py 的 "
        "PATH_RESOLVER_REGISTRY（解析器点路径），非路径语义进 REGISTRY_IGNORE 带理由"
    )


def test_ignore_list_entries_are_not_paths():
    """豁免项必须确实不是文件路径参数（防豁免被滥用成绕后门）。"""
    allowed = {"check_name_residue"}  # source_item_id=知识库条目 id
    unknown = set(REGISTRY_IGNORE) - allowed
    assert not unknown, f"REGISTRY_IGNORE 出现未审阅豁免：{unknown}"


def test_registry_resolvers_are_real():
    """登记的解析器点路径逐一可 import——防登记表与实现漂移成摆设。"""
    for tool, params in PATH_RESOLVER_REGISTRY.items():
        for param, dotted in params.items():
            mod_name, _, attr = dotted.rpartition(".")
            mod = importlib.import_module(mod_name)
            assert hasattr(mod, attr), f"{tool}.{param} 登记的 {dotted} 不存在"


def test_norm_vpath_rejects_traversal():
    assert norm_vpath("a/../../etc/passwd") is None
    assert norm_vpath("~/x") is None
    assert norm_vpath("work/body") == "/work/body"


def test_norm_candidates_covers_prefix_forms():
    """换算候选序的既有序：多层前缀/缺任务前缀/全局目录误套（收拢后等价抽查）。"""
    cands = norm_candidates("/work/body/x.md", "t_1", "/real/root")
    assert "/t_1/work/body/x.md" in cands
    cands = norm_candidates("/workspace/t_1/skills/s.md", "t_1", "/real/root")
    assert "/skills/s.md" in cands
    assert norm_candidates("a/../../x", "t_1", "/r") == []
