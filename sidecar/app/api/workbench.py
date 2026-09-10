"""任务工作树 API（2026-08-31 重构：out/ → work/）：
列出 / 读取 / 编辑 work/ 下的 markdown 过程产物 + docx 正文只读视图。

过程文件不是产物（不进索引、无事件）：它是任务级共享、随流水线重跑覆盖的
活中间态（parse→analysis→outline 的产物）。编辑走「探测 + 用户裁决 + 恢复点
兜底」——base_hash 乐观探测（409 → 前端拉取最新/保留我的）、写前留恢复点
（restorepoints/ 保留最近 3 个，与产物一致；旧版单一 .bak 首次写入时收编为
栈内最旧一条）、成功后盖「修订=用户」头标记（模型重跑前的提示线索，见
tender-analysis/tender-outline SKILL 纪律）。
json/隐藏文件不进列表（机器格式，面板不是调试器）；parse/ 只读（引用行号的
证据基准，手改=篡改原文）；.docx（tender-body 正文节/整本合册）只读——面板
版式预览走 /workbench/raw 取字节（浏览器 docx-preview 本地渲染），文本结构
视图走 /workbench/docx-view，修订标记的审阅在 Word（abs_path 供前端 reveal 唤起）。
"""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
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


def _unique_suffix_match(root: Path, path: str, task_id: str) -> Path | None:
    """work/ 全树唯一后缀兜底：模型给的路径（ask_human guide_path 等）可能少前缀
    （body/ 下相对）或多前缀（work/、<task_id>/）。剥掉已知前缀后在全树找以剩余
    路径结尾的唯一真实文件（按路径边界匹配，防 asub/x.md 误中 sub/x.md）；
    无命中或歧义返回 None——维持精确路径的原有行为（下游 404）。
    """
    parts = path.split("/")
    while parts and parts[0] in ("work", task_id):
        parts.pop(0)
    cleaned = "/".join(parts)
    if not cleaned:
        return None

    def _hit(p: Path) -> bool:
        if not p.is_file() or p.suffix not in (".md", ".docx") or p.name.startswith("."):
            return False
        rel = p.relative_to(root).as_posix()
        return rel == cleaned or rel.endswith("/" + cleaned)

    hits = [p for p in root.rglob("*") if _hit(p)]
    return hits[0] if len(hits) == 1 else None


def _resolve(task_id: str, path: str) -> Path:
    """把相对路径收进 <task>/work/（resolve 防 ../ 越界）；放行 .md 与 .docx。

    精确路径不存在时走 _unique_suffix_match 唯一兜底（读写恢复/meta 全端点同口径，
    前端用原始路径保存/轮询也会确定性地落到同一真实文件）。
    """
    root = artifact_store.work_dir(task_id).resolve()
    target = (root / path).resolve()
    if (
        not target.is_relative_to(root)
        or target.suffix not in (".md", ".docx")
        or target.name.startswith(".")
    ):
        raise HTTPException(status_code=404, detail="工作文件不存在")
    if not target.exists():
        fuzzy = _unique_suffix_match(root, path, task_id)
        if fuzzy is not None:
            return fuzzy
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
    # abs_path：面板右键「打开文件夹」直取（与 docx-view/产物行的绝对路径口径一致）
    common = {
        "path": rel,
        "abs_path": str(p),
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "size": st.st_size,
    }
    if p.suffix == ".docx":
        # docx 无「修订=用户」头部语义；不可编辑（只读视图 + Word 审阅）；
        # 恢复点目录公式与 md 同款（<文件名>.restorepoints/），_has_restore 直接可用
        return {**common, "revised": False, "editable": False, "has_restore": _has_restore(p)}
    text_head = ""
    with p.open(encoding="utf-8", errors="replace") as f:
        text_head = f.readline()
    return {
        **common,
        "revised": bool(_REVISED_RE.search(text_head)),
        "editable": not rel.startswith("parse/"),
        "has_restore": _has_restore(p),
    }


@router.get("/workbench")
async def list_workbench(task_id: str):
    """列出 work/ 全部 markdown 与 docx（json/隐藏文件排除），扁平相对路径清单。"""
    _require_task(task_id)
    root = artifact_store.work_dir(task_id)
    entries: list[dict] = []
    if root.is_dir():
        for p in sorted(list(root.rglob("*.md")) + list(root.rglob("*.docx"))):
            if not p.name.startswith(".") and p.is_file():
                entries.append(_entry(p, root))
    return {"files": entries}


def _reject_docx(target: Path, *, writing: bool) -> None:
    """docx 走专用只读通道：md 的 meta/content/写/恢复端点一律明确拒绝（不猜二进制）。"""
    if target.suffix == ".docx":
        hint = (
            "编辑请用 Word（「在文件夹中显示」后双击打开），面板只提供只读视图"
            if writing else "docx 的只读文本视图走 GET /workbench/docx-view"
        )
        raise HTTPException(status_code=400, detail=f"docx 是 Word 正文文件（二进制）——{hint}")


@router.get("/workbench/meta")
async def read_meta(task_id: str, path: str):
    """轻量探测：编辑器轮询外部更新只比哈希，不拉全文。"""
    _require_task(task_id)
    target = _resolve(task_id, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    _reject_docx(target, writing=False)
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
    _reject_docx(target, writing=False)
    text = target.read_text(encoding="utf-8")
    return {
        "content": text,
        "hash": _hash(text),
        "revised": _revised(text),
        "editable": not path.startswith("parse/"),
        "has_restore": _has_restore(target),
    }


@router.get("/workbench/docx-view")
async def read_docx_view(task_id: str, path: str):
    """docx 正文只读文本视图：段落编号+样式+图片/修订标记+表格概览。

    与模型侧 docx_section_read 是同一份序列化（tools/docx_ops.view_lines）——
    面板不渲染格式：浏览内容结构用本视图，看格式/审修订标记经 abs_path
    reveal 到文件夹后用 Word 打开。不进 dto 契约（与 /workbench/meta 同先例）。
    """
    _require_task(task_id)
    target = _resolve(task_id, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    if target.suffix != ".docx":
        raise HTTPException(status_code=400, detail="本端点只服务 .docx（markdown 用 /workbench/content）")
    from docx import Document

    from ..tools.docx_ops import view_lines

    return {"lines": view_lines(Document(str(target))), "abs_path": str(target)}


_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/workbench/raw")
async def read_raw(task_id: str, path: str):
    """docx 原始字节：面板版式预览用（docx-preview 在浏览器本地渲染，文件不出本机）。
    限 .docx（markdown 走 /workbench/content 文本端点）；只读，不参与恢复点语义。
    不进 dto 契约（与 docx-view 同先例）。"""
    _require_task(task_id)
    target = _resolve(task_id, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="工作文件不存在")
    if target.suffix != ".docx":
        raise HTTPException(status_code=400, detail="本端点只服务 .docx（markdown 用 /workbench/content）")
    return FileResponse(
        target,
        filename=target.name,
        media_type=_DOCX_MEDIA_TYPE,
        headers={"X-Content-Type-Options": "nosniff"},
    )


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
    _reject_docx(target, writing=True)
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
    _reject_docx(target, writing=True)
    _adopt_legacy_backup(target)
    points = _restore_points(target)
    if not points:
        raise HTTPException(status_code=409, detail="没有可恢复的上一版")
    previous = points[-1].read_text(encoding="utf-8")
    _push_restore_point(target)  # 当前内容入栈（恢复可再撤销）
    artifact_store._atomic_write(target, previous)
    return {"ok": True, "content": previous, "hash": _hash(previous)}


