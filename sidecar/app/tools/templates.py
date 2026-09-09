"""版式库查询工具：给 LLM 的版式库现状只读视图。

动因（2026-09-09 实测）：版式文件存在 data/templates/ 与 app/resources/，
都在任务工作区之外——ls/glob 等文件工具结构上看不见；system prompt 词汇表
定义了库的概念却无查询通道，模型全盘扫文件系统 23 步后得出「没有版式库、
数量 0」的错误结论。本工具=拉式只读查询，清单真值与 HTTP API 同源
（docx_ops.list_templates_info）。
只读不写：上传/删除/设默认是用户在界面「版式库」的裁决（探测+提示用户
裁决铁则），不提供写能力。
定名沿革：库原叫「模板库」，2026-09-09 用户拍板改名「版式库」（「模板」
二字三义歧义：版式资产/招标格式件/旧标书）；代码标识符（工具名/端点/目录）
保留 templates 不迁。
"""

from datetime import datetime

from langchain_core.tools import tool

from . import docx_ops


@tool
def list_templates() -> str:
    """查看版式库现状（版式清单与当前默认版式；用户口中的「模板库」即此）。

    版式=纯版式资产，只决定之后新建正文节与重新合册的样式；版式文件存放在
    任务工作区之外，ls/glob 等文件工具看不到——凡涉及版式/模板数量、默认
    版式、有没有某个版式的问题，先调本工具，不要检索文件系统。
    """
    try:
        rows = docx_ops.list_templates_info()
        builtin_n = sum(1 for r in rows if r["builtin"])
        user_n = len(rows) - builtin_n
        default = next((r["name"] for r in rows if r["active"]), None)
        lines = [
            f"版式库共 {len(rows)} 个：内置 {builtin_n} 个、用户上传 {user_n} 个；"
            f"当前默认={default or '（未设置，建节按内置基准）'}"
        ]
        for i, r in enumerate(rows, 1):
            tag = "内置" if r["builtin"] else f"用户上传（{datetime.fromtimestamp(r['mtime']):%Y-%m-%d}）"
            mark = " · 当前默认" if r["active"] else ""
            lines.append(f"{i}. {r['name']} —— {tag}{mark}")
        lines.append(
            "说明：版式只影响之后新建的节与重新合册，不改已写内容；"
            "更换默认版式需用户在界面「版式库」中「设为默认」，本工具只读。"
        )
        return "\n".join(lines)
    except Exception as e:  # 工具异常必须返回错误字符串，抛出会打崩整个 run
        return f"[查询失败] {type(e).__name__}: {e}"
