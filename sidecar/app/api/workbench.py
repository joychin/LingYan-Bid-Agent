"""任务工作树 API（2026-08-31 重构：out/ → work/）：
列出 / 读取 / 编辑 work/ 下的 markdown 过程产物。

过程文件不是产物（不进索引、无事件）：它是任务级共享、随流水线重跑覆盖的
活中间态（parse→analysis→outline 的产物）。编辑走「探测 + 用户裁决 + 恢复点
兜底」——base_hash 乐观探测（409 → 前端拉取最新/保留我的）、写前留恢复点
（restorepoints/ 保留最近 3 个，与产物一致；旧版单一 .bak 首次写入时收编为
栈内最旧一条）、成功后盖「修订=用户」头标记（模型重跑前的提示线索，见
tender-analysis/tender-outline SKILL 纪律）。
json/隐藏文件不进列表（机器格式，面板不是调试器）；parse/ 只读（引用行号的
证据基准，手改=篡改原文）。
"""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import artifact_store, db

router = APIRouter()

# 恢复点栈深度（与产物 artifact_store 恢复点口径一致）
_RESTORE_KEEP = 3

# 产物头部元信息注释里的修订字段（「<!-- … | 修订=用户 2026-08-28T09:30:00+00:00 -->」）
_REVISED_RE = re.compile(r"修订=用户")
_REVISED_FIELD_RE = re.compile(r"\s*\|修订=[^|>]*")


def _require_task(task_id: str) -> None:
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")


def _resolve(task_id: str, path: str) -> Path:
    """把相对路径收进 <task>/work/（resolve 防 ../ 越界）；只放行 .md。"""
    root = artifact_store.work_dir(task_id).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix != ".md" or target.name.startswith("."):
        raise HTTPException(status_code=404, detail="工作文件不存在")
    return target


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _restore_dir(target: Path) -> Path:
    """恢复点栈目录（与文件同名同级）。条目 .bak 后缀不匹配 rglob("*.md")：
    既不进 GET /workbench 列表，也不进 run_files「本轮文件」收录口径。"""
    return target.with_name(target.name + ".restorepoints")


def _legacy_backup_path(target: Path) -> Path:
    """旧版单一 .bak（2026-09-04 恢复点栈之前）：首次写恢复点时收编，不删用户数据。"""
    return target.with_name(target.name + ".bak")


def _restore_points(target: Path) -> list[Path]:
    """栈内恢复点按文件名序（时间戳前缀单调递增；legacy 收编名 0 前缀排最前）。"""
    d = _restore_dir(target)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".bak")


def _adopt_legacy_backup(target: Path) -> None:
    """栈空且旧 .bak 存在 → 收编为栈内最旧一条；栈非空则留置（不删用户数据；
    .bak 后缀不进列表，留置无害）。"""
    legacy = _legacy_backup_path(target)
    if not legacy.is_file():
        return
    d = _restore_dir(target)
    if not d.is_dir():
        d.mkdir(parents=True, exist_ok=True)
    elif any(p.suffix == ".bak" for p in d.iterdir()):
        return
    (d / "00000000-legacy.bak").write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
    legacy.unlink()


def _push_restore_point(target: Path) -> None:
    """写前留底：当前内容入栈，保留最近 RESTORE_KEEP 个。"""
    if not target.exists():
        return
    _adopt_legacy_backup(target)
    d = _restore_dir(target)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    (d / f"{ts}.bak").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    for old in _restore_points(target)[:-_RESTORE_KEEP]:
        old.unlink()


def _revised(text: str) -> bool:
    return bool(_REVISED_RE.search(text.splitlines()[0] if text else ""))


def _stamp_revised(text: str) -> str:
    """盖「修订=用户」头标记：首行是 HTML 注释则原注释内追加/更新字段；
    否则首行前插一行注释（2026-09-04 起分析产物不再有模型写的头部，
    前插是常态路径；存量带头部的旧文件走注释内追加分支）。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    field = f" | 修订=用户 {now}"
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("<!--") and lines[0].rstrip().endswith("-->"):
        head = _REVISED_FIELD_RE.sub("", lines[0])
        lines[0] = head.rstrip()[:-2].rstrip() + field + " -->"
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return f"<!-- 工作文件{field} -->\n" + text


def _has_restore(target: Path) -> bool:
    return bool(_restore_points(target)) or _legacy_backup_path(target).is_file()


def _entry(p: Path, root: Path) -> dict:
    rel = p.relative_to(root).as_posix()
    st = p.stat()
    text_head = ""
    with p.open(encoding="utf-8", errors="replace") as f:
        text_head = f.readline()
    return {
        "path": rel,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "size": st.st_size,
        "revised": bool(_REVISED_RE.search(text_head)),
        "editable": not rel.startswith("parse/"),
        "has_restore": _has_restore(p),
    }


@router.get("/workbench")
async def list_workbench(task_id: str):
    """列出 work/ 全部 markdown（json/隐藏文件排除），扁平相对路径清单。"""
    _require_task(task_id)
    root = artifact_store.work_dir(task_id)
    entries: list[dict] = []
    if root.is_dir():
        for p in sorted(root.rglob("*.md")):
            if not p.name.startswith(".") and p.is_file():
                entries.append(_entry(p, root))
    return {"files": entries}


@router.get("/workbench/meta")
async def read_meta(task_id: str, path: str):
    """轻量探测：编辑器轮询外部更新只比哈希，不拉全文。"""
    _require_task(task_id)
    target = _resolve(task_id, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    text = target.read_text(encoding="utf-8")
    return {
        "hash": _hash(text),
        "revised": _revised(text),
        "editable": not path.startswith("parse/"),
        "has_restore": _has_restore(target),
    }


@router.get("/workbench/content")
async def read_content(task_id: str, path: str):
    _require_task(task_id)
    target = _resolve(task_id, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    text = target.read_text(encoding="utf-8")
    return {
        "content": text,
        "hash": _hash(text),
        "revised": _revised(text),
        "editable": not path.startswith("parse/"),
        "has_restore": _has_restore(target),
    }


class WorkbenchWrite(BaseModel):
    task_id: str
    path: str
    content: str
    base_hash: str
    force: bool = False


@router.put("/workbench/content")
async def write_content(body: WorkbenchWrite):
    _require_task(body.task_id)
    target = _resolve(body.task_id, body.path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    if body.path.startswith("parse/"):
        raise HTTPException(status_code=403, detail="解析产物只读（引用行号的证据基准，修改请重新上传解析）")
    current = target.read_text(encoding="utf-8")
    if not body.force and _hash(current) != body.base_hash:
        raise HTTPException(
            status_code=409,
            detail="文件已被其他修改更新（可能是模型重跑），请选择拉取最新或保留你的版本",
        )
    _push_restore_point(target)
    text = _stamp_revised(body.content)
    artifact_store._atomic_write(target, text)
    return {"ok": True, "hash": _hash(text)}


@router.post("/workbench/restore")
async def restore_backup(body: dict):
    """恢复上一版：当前内容先入恢复点栈，再写回最近恢复点（与产物 restore 同构，
    可再次恢复=撤销恢复；栈深 _RESTORE_KEEP）。"""
    task_id = body.get("task_id", "")
    path = body.get("path", "")
    _require_task(task_id)
    target = _resolve(task_id, path)
    if not target.is_file():
        raise HTTPException(status_code=409, detail="没有可恢复的上一版")
    _adopt_legacy_backup(target)
    points = _restore_points(target)
    if not points:
        raise HTTPException(status_code=409, detail="没有可恢复的上一版")
    previous = points[-1].read_text(encoding="utf-8")
    _push_restore_point(target)  # 当前内容入栈（恢复可再撤销）
    artifact_store._atomic_write(target, previous)
    return {"ok": True, "content": previous, "hash": _hash(previous)}


