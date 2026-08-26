"""Artifact 包存储层（artifact-system-design.md §4/§16 任务分组布局）。

workspace 按任务分组（目录即命名空间，目录名只用不可变 id）：
    workspace/<task_id>/
      formal/art_<id>/             任务正式稿包（转正目标）
      threads/<conv_id>/art_<id>/  各会话过程稿包
      files/                       任务输入文件（上传区）
      out/                         技能工作台（parse/analysis/outline）
      drafts/                      LLM 发布草稿区
    workspace/skills/              全局技能（FilesystemBackend root 内）
    workspace/archive/<task_id>/   删任务软归档（整任务目录 mv，可手工找回）

包结构（内容与身份分离）：
    .../art_<id>/
      manifest.json          稳定身份：发布时写一次，此后不再变
      current/content.json   当前内容：唯一工作版本
      restorepoints/         覆盖前留底（保留最近 3 个）

manifest 是权威数据源，SQLite（db.artifact_index）只是可重建索引 + 运行态。
所有写入走 tmp + rename 原子替换。包的磁盘位置是 (artifact_id, scope) 的纯函数：
scope 的 task_id 恒为所属任务（过程稿也写），conversation_id 非空 → threads/ 下，
为空 → formal/ 下——scope 即 db 索引行或 manifest（两者都含这两个键）。
"""

import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from .config import workspace_dir

logger = logging.getLogger(__name__)

_AID_RE = re.compile(r"^art_[0-9a-f]{12}$")

# workspace 根下的全局目录（不属于任何任务，索引扫描跳过）
_GLOBAL_DIR_NAMES = {"skills", "archive"}


def task_dir(task_id: str) -> Path:
    return workspace_dir() / task_id


def formal_dir(task_id: str) -> Path:
    return task_dir(task_id) / "formal"


def thread_dir(task_id: str, conversation_id: str) -> Path:
    return task_dir(task_id) / "threads" / conversation_id


def task_files_dir(task_id: str) -> Path:
    return task_dir(task_id) / "files"


def task_out_dir(task_id: str) -> Path:
    return task_dir(task_id) / "out"


def task_drafts_dir(task_id: str) -> Path:
    return task_dir(task_id) / "drafts"


def archive_task_dir(task_id: str) -> Path:
    return workspace_dir() / "archive" / task_id


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _aid_ok(aid: str) -> bool:
    return bool(_AID_RE.match(aid))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def artifact_dir(aid: str, scope: Mapping) -> Path:
    """包目录 = scope 的纯函数（scope：db 索引行或 manifest，含 task_id/conversation_id）。"""
    task_id = scope.get("task_id")
    conversation_id = scope.get("conversation_id")
    if conversation_id:
        return thread_dir(str(task_id), str(conversation_id)) / aid
    if task_id:
        return formal_dir(str(task_id)) / aid
    raise ValueError(f"产物包必须归属任务（scope 缺 task_id）：{aid}")


def manifest_path(aid: str, scope: Mapping) -> Path:
    return artifact_dir(aid, scope) / "manifest.json"


def content_path(aid: str, scope: Mapping) -> Path:
    return artifact_dir(aid, scope) / "current" / "content.json"


def create_package(manifest: dict, content_text: str) -> None:
    """新建 Artifact 包：manifest + 当前内容（先内容后 manifest，manifest 落盘即视为发布完成）。"""
    aid = manifest["artifact_id"]
    _atomic_write(content_path(aid, manifest), content_text)
    _atomic_write(manifest_path(aid, manifest), json.dumps(manifest, ensure_ascii=False, indent=2))


def replace_current_content(aid: str, scope: Mapping, content_text: str) -> None:
    _atomic_write(content_path(aid, scope), content_text)


def archive_task(task_id: str) -> None:
    """删任务软归档：过程稿（threads/）先硬删（文件夹语义），任务目录整体移入
    workspace/archive/<task_id>/（正式稿/上传文件/工作台 out 全部可手工找回）。"""
    src = task_dir(task_id)
    threads = src / "threads"
    if threads.is_dir():
        shutil.rmtree(threads, ignore_errors=True)
    if not src.is_dir():
        return
    dst = archive_task_dir(task_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
    except OSError:
        logger.warning("归档任务目录失败：%s", task_id, exc_info=True)


# ---------- 恢复点（后台安全网，非版本管理：覆盖"他人内容"前留底，保留最近 3 个） ----------


def restore_dir(aid: str, scope: Mapping) -> Path:
    return artifact_dir(aid, scope) / "restorepoints"


def save_restore_point(aid: str, scope: Mapping, seq: int, content_text: str) -> None:
    """覆盖前留底。触发点：发布覆盖当前内容 / 用户强制保留自己的版本 / 恢复操作本身。"""
    d = restore_dir(aid, scope)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"rp_{int(time.time() * 1000):013d}_{seq:06d}.json").write_text(content_text, encoding="utf-8")
    points = sorted(d.glob("rp_*.json"))
    for old in points[:-3]:
        old.unlink(missing_ok=True)


def latest_restore_point(aid: str, scope: Mapping) -> Path | None:
    d = restore_dir(aid, scope)
    if not d.is_dir():
        return None
    points = sorted(d.glob("rp_*.json"))
    return points[-1] if points else None


def has_restore_point(aid: str, scope: Mapping) -> bool:
    return latest_restore_point(aid, scope) is not None


def read_manifest(aid: str, scope: Mapping) -> dict | None:
    p = manifest_path(aid, scope)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def read_content(aid: str, scope: Mapping) -> str | None:
    try:
        return content_path(aid, scope).read_text(encoding="utf-8")
    except OSError:
        return None


def list_from_disk() -> list[dict]:
    """结构化扫描各任务目录下的产物包 manifest（供索引重建）。

    遍历 workspace/<task>/formal/*/ 与 workspace/<task>/threads/*/*/，跳过全局目录
    （skills/archive）。沿用 aid 合法性 + manifest.artifact_id==目录名校验；
    scope 缺 task_id 的散包跳过（新布局下包必须归属任务）。
    """
    result: list[dict] = []
    root = workspace_dir()
    if not root.is_dir():
        return result
    for task_p in sorted(root.iterdir()):
        if not task_p.is_dir() or task_p.name in _GLOBAL_DIR_NAMES:
            continue
        package_dirs: list[Path] = []
        formal = task_p / "formal"
        if formal.is_dir():
            package_dirs.extend(sorted(formal.iterdir()))
        threads = task_p / "threads"
        if threads.is_dir():
            for conv_p in sorted(threads.iterdir()):
                if conv_p.is_dir():
                    package_dirs.extend(sorted(conv_p.iterdir()))
        for p in package_dirs:
            if not p.is_dir() or not _aid_ok(p.name):
                continue
            try:
                m = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get("artifact_id") == p.name and m.get("task_id"):
                result.append(m)
    return result


def package_ready(aid: str, scope: Mapping) -> bool:
    """包完整（manifest 与当前内容都在且 aid 合法）——供 API 过滤磁盘缺失记录。"""
    return _aid_ok(aid) and manifest_path(aid, scope).is_file() and content_path(aid, scope).is_file()


def resolved_content_path(aid: str, scope: Mapping) -> Path | None:
    """产物读路径 containment：resolve（跟随符号链接）后必须仍在 workspace 内。"""
    if not _aid_ok(aid):
        return None
    try:
        resolved = content_path(aid, scope).resolve()
    except OSError:
        return None
    return resolved if resolved.is_relative_to(workspace_dir().resolve()) else None
