"""知识库磁盘布局与操作（workspace/knowledge/，与 skills/archive 同级的全局目录）。

    knowledge/
      files/<原文件名>              # 上传原件（证据形态，投标引用用原件）
      parse/<文件名（含扩展名）>/<文件名>.md|.outline.json|.meta.json|.materials.json
                                    # 解析产物四件套（章节块 materials.json=写法类条目，
                                    # LLM 裁定真值）
      parse/<文件名（含扩展名）>/images/   # 文档图片（仅供内容页折叠区查看，与素材无关）

产物目录名用**完整文件名（含扩展名）**（2026-09-17 改，与任务侧 work/parse/<文件名>/
同口径）：早期用 stem，`证书.pdf` 与 `证书.docx` 会共享 `parse/证书/`——images/ 互清
（后入库者重抽即抹掉前者图）、删一条 rmtree 掉另一条的全部产物。md/outline/meta 因
带全名前缀可共存，但目录一删全灭；旧布局由 ingest.migrate_parse_dir_layout 一次性
迁移。materials.json 是章节块真值（一个块=一个能独立复用的最小完整主题；LLM 裁定非
确定性——重建索引用现成 JSON 不重算，块 id 只在一个 materials.json 生命周期内
稳定，重建=新 ID=旧引用可探测失效；excluded 排除开关随块存储，重建即重置）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..config import knowledge_dir


def kb_files_dir() -> Path:
    return knowledge_dir() / "files"


def kb_parse_root() -> Path:
    return knowledge_dir() / "parse"


def migrate_parse_dirs(
    parse_root: Path,
    file_names: list[str],
    prefixed_suffixes: tuple[str, ...],
    shared_entries: tuple[str, ...],
) -> dict:
    """旧布局 parse/<stem>/ → 新布局 parse/<文件名>/ 的一次性迁移（幂等，KB/MT 共用）。

    背景（2026-09-17）：目录键原用 Path(file_name).stem，`证书.pdf` 与 `证书.docx`
    共享 parse/证书/——带全名前缀的产物（md/outline/…）虽可共存，但共享件（KB 的
    images/、MT 的 blocks.json 等）互相污染，且 delete 按目录 rmtree 会连带毁掉
    同名兄弟的全部产物。迁移规则：

    - 单文件组：整目录 rename（一切随目录走，最快路径）；
    - 碰撞组：逐文件拆分——各方的 `<文件名><suffix>` 产物移进各自新目录；
      共享件（shared_entries：文件与子目录都支持）**拷贝给每一方**——共享期的
      内容污染是历史损伤、无法事后区分归属，拷贝=谁都不丢，各方独立后由用户
      自行清理（迁移日志按 stem 点名），最后删除旧目录；
    - 已是新布局（parse/<文件名>/ 存在）或从未解析的条目自然跳过，重跑无副作用。

    只动磁盘不动 DB（路径全部是 file_name 的纯函数，DB 无绝对路径引用）。
    """
    stats: dict = {"renamed": 0, "split": 0, "skipped": 0, "conflicts": []}
    if not parse_root.is_dir():
        return stats
    groups: dict[str, list[str]] = {}
    for name in file_names:
        groups.setdefault(Path(name).stem, []).append(name)
    for stem, names in groups.items():
        old = parse_root / stem
        if not old.is_dir():
            continue  # 新布局（stem≠文件名时目录不会以 stem 存在）或从未解析
        if len(names) == 1 and stem != names[0]:
            new = parse_root / names[0]
            if new.exists():
                stats["skipped"] += 1
                continue
            old.rename(new)
            stats["renamed"] += 1
            continue
        if stem == names[0] and len(names) == 1:
            continue  # 无扩展名文件：新旧同名，无需动
        # 碰撞组（或 stem 恰与另一文件全名相同的边缘形态）：逐文件拆分
        for name in names:
            new = parse_root / name
            new.mkdir(parents=True, exist_ok=True)
            for suffix in prefixed_suffixes:
                src = old / f"{name}{suffix}"
                if src.is_file():
                    _move_into(src, new / src.name)
            for entry in shared_entries:
                src = old / entry
                dst = new / entry
                if src.is_dir() and not dst.exists():
                    shutil.copytree(src, dst)
                elif src.is_file() and not dst.exists():
                    shutil.copy2(src, dst)
            stats["split"] += 1
        stats["conflicts"].append(stem)
        shutil.rmtree(old, ignore_errors=True)
    return stats


def _move_into(src: Path, dst: Path) -> None:
    """同盘移动（rename；目标已存在时跳过保新）。"""
    if dst.exists():
        return
    try:
        src.rename(dst)
    except OSError:
        pass


def kb_parse_dir(file_name: str) -> Path:
    """某文件的解析产物目录：knowledge/parse/<文件名（含扩展名）>/。"""
    return knowledge_dir() / "parse" / file_name


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
    """图片素材目录：parse/<文件名（含扩展名）>/images/（抽取的嵌入图存这里，image_path 相对于它）。"""
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
