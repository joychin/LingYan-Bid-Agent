"""任务工作树 API（2026-08-31 重构：out/ → work/）：
列出 / 读取 / 编辑 work/ 下的 markdown 过程产物 + 存为笔记。

过程文件不是产物（不进索引、无事件）：它是任务级共享、随流水线重跑覆盖的
活中间态（parse→analysis→outline 的产物）。编辑走「探测 + 用户裁决 + 恢复点
兜底」——base_hash 乐观探测（409 → 前端拉取最新/保留我的）、写前留 .bak
（单一上一版，恢复=互换可再撤销）、成功后盖「修订=用户」头标记（模型重跑前
的提示线索，见 tender-analysis/tender-outline SKILL 纪律）。
json/隐藏文件不进列表（机器格式，面板不是调试器）；parse/ 只读（引用行号的
证据基准，手改=篡改原文）。
"""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import artifact_store, db, publish
from ..publish import PublishError

router = APIRouter()

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


def _backup_path(target: Path) -> Path:
    return target.with_name(target.name + ".bak")


def _revised(text: str) -> bool:
    return bool(_REVISED_RE.search(text.splitlines()[0] if text else ""))


def _stamp_revised(text: str) -> str:
    """盖「修订=用户」头标记：首行是 HTML 注释则原注释内追加/更新字段；
    否则首行前插一行注释（analysis/outline 产物首行本就是注释，前插是兜底）。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    field = f" | 修订=用户 {now}"
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("<!--") and lines[0].rstrip().endswith("-->"):
        head = _REVISED_FIELD_RE.sub("", lines[0])
        lines[0] = head.rstrip()[:-2].rstrip() + field + " -->"
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return f"<!-- 工作文件{field} -->\n" + text


def _save_backup(target: Path) -> None:
    """写前留上一版（单一 .bak；恢复时互换 → 恢复本身可再撤销）。"""
    if target.exists():
        _backup_path(target).write_text(target.read_text(encoding="utf-8"), encoding="utf-8")


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
        "has_backup": _backup_path(p).exists(),
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
        "has_backup": _backup_path(target).exists(),
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
    _save_backup(target)
    text = _stamp_revised(body.content)
    artifact_store._atomic_write(target, text)
    return {"ok": True, "hash": _hash(text)}


@router.post("/workbench/restore")
async def restore_backup(body: dict):
    """恢复上一版：当前内容与 .bak 互换（当前先存为 .bak → 恢复可再撤销）。"""
    task_id = body.get("task_id", "")
    path = body.get("path", "")
    _require_task(task_id)
    target = _resolve(task_id, path)
    bak = _backup_path(target)
    if not target.is_file() or not bak.is_file():
        raise HTTPException(status_code=409, detail="没有可恢复的上一版")
    current = target.read_text(encoding="utf-8")
    previous = bak.read_text(encoding="utf-8")
    artifact_store._atomic_write(bak, current)
    artifact_store._atomic_write(target, previous)
    return {"ok": True, "content": previous, "hash": _hash(previous)}


class WorkbenchNote(BaseModel):
    conversation_id: str
    path: str
    title: str | None = None


@router.post("/workbench/note", status_code=201)
async def save_as_note(body: WorkbenchNote):
    """存为笔记：把工作文件内容作为快照发布为 doc.note 产物（走既有
    publish 管线；task-multi 每次新建不覆盖）。"""
    conv = db.get_conversation(body.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    target = _resolve(conv["task_id"], body.path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    text = target.read_text(encoding="utf-8")
    name = Path(body.path).stem
    title = body.title or f"工作文件快照 · {name}"
    try:
        manifest = publish.publish_artifact(
            "doc.note/note-md@1",
            {"title": title, "body_md": text},
            display_name=title,
            source={"skill": "workbench"},
            task_id=conv["task_id"],
            conversation_id=body.conversation_id,
        )
    except PublishError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.mark_emitted(manifest["artifact_id"])
    return {"artifact_id": manifest["artifact_id"], "display_name": manifest.get("display_name")}
