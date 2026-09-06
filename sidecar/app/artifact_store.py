"""产物包存储层（任务归属 + 单一当前版本，2026-09-04 两态移除）。

workspace 按任务分组（目录即命名空间，目录名只用不可变 id）：
    workspace/<task_id>/
      sources/                    只读来源（上传原件），AI 物理写不进
      work/                       工作树（任务级共享，AI 可写）
        parse/<src>/<src>.md      解析产物（只读 flag，证据锚点）
        analysis/<七节>.md        分析稿（可重生成，可带「已修订」）
        outline/...               目录草稿（工作表）
        body/...                  正文（预留）
        artifacts/<aid>/          登记产物包
      _meta/                      产物级谱系/暂存（UI 永不展示）
    workspace/skills/             全局技能（FilesystemBackend root 内）
    workspace/archive/<task_id>/  删任务软归档（整任务目录 mv，可手工找回）
    workspace/knowledge/          知识库（跨任务共享，唯一共享层）

包结构（内容与身份分离）：
    .../artifacts/<aid>/
      meta.json               身份（发布后不变）
      content.json            当前内容：唯一工作版本
      restorepoints/          覆盖前留底（保留最近 3 个）

meta.json 是权威数据源，SQLite（db.artifact_index）只是可重建索引 + 运行态
（content_seq/emitted）。所有写入走 tmp + rename 原子替换。包位置 =
(artifact_id, task_id) 的纯函数——文件归任务，会话只是 provenance（last_run_id/
last_thread_id），不再按会话分目录。
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

# workspace 根下的全局目录（不属于任何任务，索引扫描跳过）。conversation_history =
# deepagents SummarizationMiddleware 压缩时逐出历史的落盘处（压缩触发后才会出现）
_GLOBAL_DIR_NAMES = {"skills", "archive", "knowledge", "conversation_history"}


def task_dir(task_id: str) -> Path:
    return workspace_dir() / task_id


def sources_dir(task_id: str) -> Path:
    """只读来源（上传原件）。AI 文件工具写不进（fs_guard 黑名单）。"""
    return task_dir(task_id) / "sources"


def work_dir(task_id: str) -> Path:
    """工作树：过程文件（parse/analysis/outline/body）+ 产物包（artifacts/）。"""
    return task_dir(task_id) / "work"


def work_artifacts_dir(task_id: str) -> Path:
    """登记产物包根（work/artifacts/<aid>/）。"""
    return work_dir(task_id) / "artifacts"


def meta_dir(task_id: str) -> Path:
    """产物级谱系/暂存（UI 永不展示；fs_guard 拒写）。"""
    return task_dir(task_id) / "_meta"


def staging_dir(task_id: str) -> Path:
    """LLM 发布暂存区（publish 工具两步流的落点，发布时移动消费）。"""
    return meta_dir(task_id) / "staging"


def archive_task_dir(task_id: str) -> Path:
    return workspace_dir() / "archive" / task_id


# work/ 下的已知管线子目录（parse→analysis→outline 主线 + fragments 多册中间态）。
# 预建它们是因为「声明版式里的目录不存在」对模型永远是意外：写文件会自动建父目录，
# 但 ls 撞上空窗期吃 path_not_found 红错（2026-09-06 实测，2026-08-29 sources/work
# 先例的延伸）。新管线目录（如 tender-body 的 body/）随技能落地同步加这里。
_PROCESS_DIRS = ("parse", "analysis", "outline", "outline/fragments")


def ensure_task_skeleton(task_id: str) -> None:
    """预建 sources/work + 已知管线子目录（任务创建时 + 每次 run 启动自愈，双入口）。

    这些是 agent 开工最常探测的（ls sources/ 看资料、ls work/outline/fragments/
    等子代理产出），按需创建语义下它们在首次使用前不存在，模型的 ls 直接
    path_not_found 吃红错。artifacts/ 与 _meta/ 仍按需创建（publish/fs_guard
    各自拥有，模型不经文件工具访问）。
    """
    dirs = [sources_dir(task_id), work_dir(task_id)]
    dirs += [work_dir(task_id) / rel for rel in _PROCESS_DIRS]
    for d in dirs:
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
    """包目录 = (aid, task_id) 的纯函数。scope：db 索引行或 meta.json，含 task_id。"""
    task_id = scope.get("task_id")
    if not task_id:
        raise ValueError(f"产物包必须归属任务（scope 缺 task_id）：{aid}")
    return work_artifacts_dir(str(task_id)) / aid


def meta_path(aid: str, scope: Mapping) -> Path:
    return artifact_dir(aid, scope) / "meta.json"


def content_path(aid: str, scope: Mapping) -> Path:
    return artifact_dir(aid, scope) / "content.json"


def create_package(meta: dict, content_text: str) -> None:
    """新建产物包：meta + 当前内容（先内容后 meta，meta 落盘即视为发布完成）。"""
    aid = meta["artifact_id"]
    _atomic_write(content_path(aid, meta), content_text)
    _atomic_write(meta_path(aid, meta), json.dumps(meta, ensure_ascii=False, indent=2))


def replace_current_content(aid: str, scope: Mapping, content_text: str) -> None:
    _atomic_write(content_path(aid, scope), content_text)


def archive_task(task_id: str) -> bool:
    """删任务软归档：任务目录**整体移入** workspace/archive/<task_id>/
    （move 失败返回 False，调用方不得删库——目录原样保留，用户可重试或手工处理）。
    文件归任务：过程文件/产物/来源整体归档，不硬删任何子目录（删会话不再碰文件）。
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


def read_meta(aid: str, scope: Mapping) -> dict | None:
    p = meta_path(aid, scope)
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

    写路径读取侧统一走此入口（编辑保存 force 留底 / 恢复 / 发布覆盖留底 /
    read_artifact 工具），与 GET content 同标准——包目录被手工篡改出越界 symlink 时
    读不到 workspace 外内容。写侧（_atomic_write）仍直写包内路径：写入位置由
    (aid, task_id) 纯函数派生、无用户输入分量，当前威胁模型下不加 resolve。"""
    p = resolved_content_path(aid, scope)
    if p is None:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def list_from_disk() -> list[dict]:
    """结构化扫描各任务目录下的产物包 meta.json（供索引重建）。

    遍历 workspace/<task>/work/artifacts/*/，跳过全局目录（skills/archive/knowledge/
    conversation_history）。沿用 aid 合法性 + meta.artifact_id==目录名校验；
    scope 缺 task_id 的散包跳过（新布局下包必须归属任务）。
    """
    result: list[dict] = []
    root = workspace_dir()
    if not root.is_dir():
        return result
    for task_p in sorted(root.iterdir()):
        if not task_p.is_dir() or task_p.name in _GLOBAL_DIR_NAMES:
            continue
        artifacts = task_p / "work" / "artifacts"
        if not artifacts.is_dir():
            continue
        for p in sorted(artifacts.iterdir()):
            if not p.is_dir() or not _aid_ok(p.name):
                continue
            try:
                m = json.loads((p / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get("artifact_id") == p.name and m.get("task_id"):
                result.append(m)
    return result


def package_ready(aid: str, scope: Mapping) -> bool:
    """包完整（meta 与当前内容都在且 aid 合法）——供 API 过滤磁盘缺失记录。"""
    return _aid_ok(aid) and meta_path(aid, scope).is_file() and content_path(aid, scope).is_file()


def resolved_content_path(aid: str, scope: Mapping) -> Path | None:
    """产物读路径 containment：resolve（跟随符号链接）后必须仍在 workspace 内。"""
    if not _aid_ok(aid):
        return None
    try:
        resolved = content_path(aid, scope).resolve()
    except OSError:
        return None
    return resolved if resolved.is_relative_to(workspace_dir().resolve()) else None
