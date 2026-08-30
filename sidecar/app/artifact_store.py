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
import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from .config import workspace_dir

logger = logging.getLogger(__name__)

# 内容写锁（不可见 plumbing，publish 先例的宿主）：API 端点跑在事件循环线程、
# LLM 发布工具跑在 worker 线程，两者对同一包的「读行→写文件→写索引」真并行。
# 共用这一把锁串行化落盘段，不做任何用户可见的互斥——覆盖策略仍遵循文件夹语义。
write_lock = threading.Lock()

_AID_RE = re.compile(r"^art_[0-9a-f]{12}$")

# workspace 根下的全局目录（不属于任何任务，索引扫描跳过）
_GLOBAL_DIR_NAMES = {"skills", "archive", "knowledge"}


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


def ensure_task_skeleton(task_id: str) -> None:
    """预建 files/out/drafts 骨架目录（任务创建时 + 每次run启动自愈，双入口）。

    其余目录仍按需创建（发布/上传各自 mkdir）；这三个是 agent 开工第一步最常探测的
    （ls files/ 看资料、ls drafts/ 找草稿），按需创建语义下它们在首次使用前不存在，
    模型的 ls 直接 path_not_found 吃红错（2026-08-29 实测：主/子代理第一步即错，
    还会诱导子代理去翻别的任务目录找资料）。threads/ 不预建——按会话粒度按需建。
    run 启动自愈覆盖骨架预建（2026-08-29）之前创建的旧任务：那些任务只有库行、
    没有磁盘目录，纯检索/对话任务无按需建目录的时机，模型 ls 任务根目录必错。
    """
    for d in (task_files_dir(task_id), task_out_dir(task_id), task_drafts_dir(task_id)):
        d.mkdir(parents=True, exist_ok=True)


def new_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _aid_ok(aid: str) -> bool:
    return bool(_AID_RE.match(aid))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时名带随机后缀：事件循环线程与 worker 线程可能写同一目标文件，
    # 固定 .tmp 名会互相截断/抢占（第二次 replace 直接 FileNotFoundError）
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
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


def archive_task(task_id: str) -> bool:
    """删任务软归档：任务目录**整体先移入** workspace/archive/<task_id>/
    （move 失败返回 False，调用方不得删库——目录原样保留，用户可重试或手工处理），
    移动成功后再硬删归档内的 threads/（过程稿按文件夹语义不进归档）。
    顺序不能反：先删 threads 再 move，move 失败时会话过程稿已不可恢复。
    """
    src = task_dir(task_id)
    if not src.is_dir():
        return True
    dst = archive_task_dir(task_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
    except OSError:
        logger.warning("归档任务目录失败：%s", task_id, exc_info=True)
        return False
    threads = dst / "threads"
    if threads.is_dir():
        shutil.rmtree(threads, ignore_errors=True)
    return True


# ---------- 恢复点（后台安全网，非版本管理：覆盖"他人内容"前留底，保留最近 3 个） ----------


def restore_dir(aid: str, scope: Mapping) -> Path:
    return artifact_dir(aid, scope) / "restorepoints"


def save_restore_point(aid: str, scope: Mapping, seq: int, content_text: str) -> None:
    """覆盖前留底。触发点：发布覆盖当前内容 / 用户强制保留自己的版本 / 恢复操作本身。

    文件名带随机后缀防碰撞（同毫秒同 seq 的两次留底互相覆盖会丢恢复点），
    走 _atomic_write 保证读者（latest_restore_point）不会读到截断内容。
    """
    d = restore_dir(aid, scope)
    d.mkdir(parents=True, exist_ok=True)
    name = f"rp_{int(time.time() * 1000):013d}_{seq:06d}_{uuid.uuid4().hex[:8]}.json"
    _atomic_write(d / name, content_text)
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


def read_content_resolved(aid: str, scope: Mapping) -> str | None:
    """读当前内容（containment 版）：resolve 后必须仍在 workspace 内，越界返回 None。

    写路径读取侧统一走此入口（编辑保存 force 留底 / 恢复 / 转正 / 发布覆盖留底 /
    read_artifact 工具），与 GET content 同标准——包目录被手工篡改出越界 symlink 时
    读不到 workspace 外内容。写侧（_atomic_write）仍直写包内路径：写入位置由
    (aid, scope) 纯函数派生、无用户输入分量，当前威胁模型下不加 resolve。"""
    p = resolved_content_path(aid, scope)
    if p is None:
        return None
    try:
        return p.read_text(encoding="utf-8")
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
