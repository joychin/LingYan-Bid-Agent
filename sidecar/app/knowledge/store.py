"""知识库磁盘布局与操作（workspace/knowledge/，与 skills/archive 同级的全局目录）。

    knowledge/
      files/<原文件名>              # 上传原件（证据形态，投标引用用原件）
      parse/<文件stem>/<文件名>.md|.outline.json|.meta.json|.materials.json
                                    # 解析产物三件套 + 章节块（写法类条目，LLM 裁定真值）
      parse/<文件stem>/images/      # 文档图片（仅供内容页折叠区查看，与素材无关）

产物目录名用文件 stem（知识库文件名已去重，同名不同扩展各自成目录不互踩）。
materials.json 是章节块真值（一个块=一个能独立复用的最小完整主题；LLM 裁定非
确定性——重建索引用现成 JSON 不重算，块 id 只在一个 materials.json 生命周期内
稳定，重建=新 ID=旧引用可探测失效；excluded 排除开关随块存储，重建即重置）。
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


def kb_parse_paths(file_name: str) -> tuple[Path, Path, Path, Path]:
    """(md, outline.json, meta.json, materials.json) 四产物路径。"""
    d = kb_parse_dir(file_name)
    return (
        d / f"{file_name}.md",
        d / f"{file_name}.outline.json",
        d / f"{file_name}.meta.json",
        d / f"{file_name}.materials.json",
    )


def kb_images_dir(file_name: str) -> Path:
    """图片素材目录：parse/<stem>/images/（抽取的嵌入图存这里，image_path 相对于它）。"""
    return kb_parse_dir(file_name) / "images"


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
