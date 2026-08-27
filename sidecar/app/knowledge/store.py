"""知识库磁盘布局与操作（workspace/knowledge/，与 skills/archive 同级的全局目录）。

    knowledge/
      files/<原文件名>              # 上传原件（证据形态，投标引用用原件）
      parse/<文件stem>/<文件名>.md|.outline.json|.meta.json   # 解析产物（检索/阅读表示）

产物目录名用文件 stem（知识库文件名已去重，同名不同扩展各自成目录不互踩）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..config import knowledge_dir


def kb_files_dir() -> Path:
    return knowledge_dir() / "files"


def kb_parse_dir(file_name: str) -> Path:
    """某文件的解析产物目录：knowledge/parse/<stem>/。"""
    return knowledge_dir() / "parse" / Path(file_name).stem


def kb_parse_paths(file_name: str) -> tuple[Path, Path, Path]:
    """(md, outline.json, meta.json) 三产物路径。"""
    d = kb_parse_dir(file_name)
    return d / f"{file_name}.md", d / f"{file_name}.outline.json", d / f"{file_name}.meta.json"


def ensure_dirs() -> None:
    kb_files_dir().mkdir(parents=True, exist_ok=True)


def unique_file_path(file_name: str) -> Path:
    """同名不同内容加序号后缀（同 hash 在 API 层已拦截，这里只防同异 hash 同名）。"""
    cand = kb_files_dir() / file_name
    if not cand.exists():
        return cand
    stem, ext = Path(file_name).stem, Path(file_name).suffix
    i = 2
    while (kb_files_dir() / f"{stem} ({i}){ext}").exists():
        i += 1
    return kb_files_dir() / f"{stem} ({i}){ext}"


def delete_item_files(file_name: str) -> None:
    """删条目连带原件与解析产物（目录级，容错）。"""
    src = kb_files_dir() / file_name
    if src.is_file():
        src.unlink(missing_ok=True)
    shutil.rmtree(kb_parse_dir(file_name), ignore_errors=True)
    knowledge_dir().mkdir(parents=True, exist_ok=True)
