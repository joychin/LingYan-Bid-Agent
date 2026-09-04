"""旧名残留机械扫描（拷贝修订模式的第一道防线，行业第一大事故=提交稿残留旧
机构/旧项目名）。纯确定性检查，零 LLM：扫描表 = 显式名单 + 来源条目的项目名/
客户名（元数据锚点）+ 来源文件名去扩展名。拷整章后必须调用。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from .. import db
from ..knowledge.roles import item_meta


@tool
def check_name_residue(text: str, source_item_id: str | None = None, old_names: list[str] | None = None) -> str:
    """扫描文本中残留的旧项目名/旧客户名/旧机构名（整章拷贝修订后必须调用）。

    扫描名单 = old_names 显式补充 + 来源资料的项目名/客户名（自动取）+ 来源文件名
    去扩展名。返回残留位置（行号+上下文）清单；无残留返回通过。
    Args:
        text: 待检查的正文（拷贝来的章节/段落）
        source_item_id: 可选，来源条目 id——知识库条目（kb: 前缀，自动取项目名/
                        客户名）或素材库文件（mt: 前缀，自动取文件名主干）
        old_names: 可选，额外显式名单（旧机构名、旧项目简称等）
    """
    try:
        names: list[str] = [n.strip() for n in (old_names or []) if isinstance(n, str) and len(n.strip()) >= 2]
        if source_item_id:
            item = db.kb_get_item(source_item_id)
            file_name = None
            if item:
                file_name = item["file_name"]
                for code in ("project_name", "client"):
                    v = item_meta(item, code)
                    if v and len(v) >= 2:
                        names.append(v)
            else:
                mt_file = db.mt_get_file(source_item_id)
                if mt_file:
                    file_name = mt_file["file_name"]
            if file_name:
                stem = Path(file_name).stem
                # 文件名常含项目名+年份后缀，取主干（去括号/空格分段的首段长词）
                for part in re_split_name(stem):
                    if len(part) >= 4:
                        names.append(part)
        seen: set[str] = set()
        uniq = [n for n in names if not (n in seen or seen.add(n))]

        lines = (text or "").splitlines()
        found: list[str] = []
        for name in uniq:
            hits: list[str] = []
            for i, ln in enumerate(lines, 1):
                if name in ln:
                    ctx = ln.strip()
                    hits.append(f"L{i}：{ctx[:60]}{'…' if len(ctx) > 60 else ''}")
            if hits:
                found.append(f"残留「{name}」× {len(hits)} 处：" + "；".join(hits[:5]))

        if not found:
            return f"[残留扫描通过] 扫描 {len(uniq)} 个旧名，无残留。" if uniq else (
                "[残留扫描通过] 扫描表为空——建议传 source_item_id 或 old_names。"
            )
        return (
            f"[旧名残留告警] 共 {len(found)} 个旧名残留，提交前必须全部替换：\n"
            + "\n".join(found)
        )
    except Exception as e:
        return f"[残留扫描失败] {type(e).__name__}: {e}"


def re_split_name(stem: str) -> list[str]:
    import re

    return [p for p in re.split(r"[\s（）()\-_—【】\[\]]+", stem) if p]
