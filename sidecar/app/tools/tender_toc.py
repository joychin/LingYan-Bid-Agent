"""tender-toc 三个确定性桥接工具（从 deepagents-demo/demo.py 迁移）。

Skill 讲方法论（SKILL.md / references/prompts.md），Tool 做确定性执行：
  convert_tender  docx/doc/pdf → tender-full.md（Agent 阅读分析）
  extract_toc     仅抽招标文件自身标题大纲（免 LLM）
  build_tender    读取 Agent 产出的中间文件，组装最终交付物

路径约定：脚本在 data/workspace/skills/tender-toc/scripts/parse_toc.py，
中间产物与最终交付物在 data/workspace/out/。
"""

import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from ..config import workspace_dir

TOC_SCRIPT = workspace_dir() / "skills" / "tender-toc" / "scripts" / "parse_toc.py"
OUTDIR = workspace_dir() / "out"


def _resolve_path(p: str) -> Path:
    """把 agent 给的路径解析到 workspace 内的真实文件（兼容虚拟路径 / 前导斜杠写法）。

    只允许读取 workspace 内的文件：解析（含符号链接）后必须落在 workspace_dir() 之下，
    否则拒绝——防止文档内容注入诱导模型读取工作区外的敏感文件。
    """
    ws = workspace_dir().resolve()
    cand = Path(p).expanduser()
    if not cand.is_absolute():
        cand = ws / cand
    resolved = cand.resolve()  # 跟随符号链接后再校验，防 symlink 逃逸
    if not resolved.is_relative_to(ws):
        raise ValueError(f"路径越界：只允许访问工作区内的文件（{ws}），收到 {p}")
    return resolved


def _run_script(*args: str) -> str:
    """用当前 venv 的 python 跑 parse_toc.py（依赖 python-docx 已装在 venv 里）。"""
    OUTDIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(TOC_SCRIPT), *args],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        return f"[脚本失败]\n{proc.stderr[-1500:]}"
    out = (proc.stdout or "").strip()
    return out[-1500:] if out else "OK"


@tool
def convert_tender(docx_path: str) -> str:
    """把招标文件(.docx/.doc/.pdf)转换为完整 Markdown（out/tender-full.md），供后续 S1/S2/S3 分析使用。"""
    try:
        path = _resolve_path(docx_path)
    except ValueError as e:
        return f"[路径校验失败] {e}"
    result = _run_script("convert", str(path), "--outdir", str(OUTDIR))
    return f"{result}\n[提示] 已生成 out/tender-full.md，请用 read_file 读取后开始分析。"


@tool
def extract_toc(docx_path: str) -> str:
    """仅抽取招标文件自身的标题大纲（免推理），生成 out/tender-file-toc.md/.json。"""
    try:
        path = _resolve_path(docx_path)
    except ValueError as e:
        return f"[路径校验失败] {e}"
    return _run_script("file", str(path), "--outdir", str(OUTDIR))


@tool
def build_tender() -> str:
    """读取 out/ 目录下 Agent 产出的中间文件，组装最终交付物（tender-response-docs.json / tender-directory.json / .html / registry）。"""
    return _run_script("build", "--outdir", str(OUTDIR))


TOOLS = [convert_tender, extract_toc, build_tender]
