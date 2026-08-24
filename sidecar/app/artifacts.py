"""产物登记：run 前后对 out/ 目录做快照 diff，新增或大小变化的文件即本次产物。

与工具代码完全解耦——工具只管写文件，这里在 run 边界做检测（PRD §4.2）。
"""

import uuid
from pathlib import Path

from . import db
from .config import workspace_dir

_TYPE_BY_SUFFIX = {
    ".html": "html",
    ".json": "json",
    ".md": "md",
}


def out_dir() -> Path:
    return workspace_dir() / "out"


def resolve_artifact_path(path: str) -> Path | None:
    """产物读路径 containment（与工具侧铁律同一标准）：只允许 workspace/out 内的文件。

    artifacts 表的 path 无库级约束，脏数据/历史记录可能指向工作区外；resolve() 会
    跟随符号链接，out/ 内指向外部的 symlink 也一并拒绝。越界返回 None。
    """
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    return resolved if resolved.is_relative_to(out_dir().resolve()) else None


def snapshot_out() -> dict[str, tuple[int, float]]:
    """扫描 out/ 目录：文件名 → (size, mtime)。"""
    out = out_dir()
    snap: dict[str, tuple[int, float]] = {}
    if not out.is_dir():
        return snap
    for p in out.iterdir():
        if p.is_file():
            st = p.stat()
            snap[p.name] = (st.st_size, st.st_mtime)
    return snap


def detect_type(name: str) -> str:
    """按扩展名推断产物类型（PRD §4.4：html/json/md/other）。"""
    return _TYPE_BY_SUFFIX.get(Path(name).suffix.lower(), "other")


def diff_artifacts(snapshot: dict[str, tuple[int, float]]) -> list[dict]:
    """重扫 out/，返回新增或大小变化的文件列表。"""
    out = out_dir()
    current = snapshot_out()
    found: list[dict] = []
    for name, (size, _mtime) in current.items():
        old = snapshot.get(name)
        if old is None or old[0] != size:
            found.append(
                {
                    "name": name,
                    "path": str(out / name),
                    "type": detect_type(name),
                    "size": size,
                }
            )
    return found


def register_run_artifacts(
    cid: str, rid: str, snapshot: dict[str, tuple[int, float]]
) -> list[dict]:
    """把 run 期间新增/变化的 out/ 文件写入 artifacts 表，返回带 id 的产物 dict（供 emit）。"""
    result: list[dict] = []
    for art in diff_artifacts(snapshot):
        aid = f"a_{uuid.uuid4().hex[:12]}"
        record = db.create_artifact(
            aid, cid, rid, art["name"], art["path"], art["type"], art["size"]
        )
        result.append(record)
    return result
