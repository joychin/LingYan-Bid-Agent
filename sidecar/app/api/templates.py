"""文档模板库 API：模板管理（上传/删除/激活/预览）与任务换装。

模板=格式资产（与素材=内容资产分离，2026-09-08 用户拍板拆库）：版式活在
.docx 的样式表，生效位=app_settings docx_template（缺省内置基准）；建节/
合册经 docx_ops._active_template_path 读生效位、改动即时生效（无重启）。
「应用到已有章节」=重建式换装（docx_ops.restyle_docx：恢复点兜底+409 活跃
run 守卫，无锁铁则）。
"""

import os
import uuid
from pathlib import Path

from docx import Document as _DocxDocument
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import artifact_store, db
from ..config import data_dir
from ..contracts.dto import RestyleReport, RestyleResult, TemplateInfo
from ..tools import docx_ops

router = APIRouter()

_BUILTIN_KEY = "__builtin__"
_BUILTIN_NAME = "内置标书基准模板"
_CHUNK = 1024 * 1024
_MAX_TEMPLATE_BYTES = 20 * 1024 * 1024


class _ApplyBody(BaseModel):
    task_id: str


def _templates_dir() -> Path:
    d = data_dir() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve(key: str) -> Path:
    """key → 模板路径（内置键或用户模板文件名；Path.name 清洗防目录穿越）。"""
    if key == _BUILTIN_KEY:
        return docx_ops._BASE_TEMPLATE
    name = Path(key).name
    if not name or name.startswith("."):
        raise HTTPException(status_code=400, detail="模板名非法")
    p = _templates_dir() / name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="模板不存在（可能已被删除），请刷新列表")
    return p


def _active_name() -> str | None:
    return (db.get_setting(docx_ops.TEMPLATE_SETTING_KEY) or "").strip() or None


def _info(p: Path, *, key: str, name: str, builtin: bool) -> TemplateInfo:
    st = p.stat()
    return TemplateInfo(
        name=name,
        key=key,
        builtin=builtin,
        active=(key == _active_name()) or (key == _BUILTIN_KEY and _active_name() is None),
        size=st.st_size,
        mtime=st.st_mtime,
    )


@router.get("/templates")
async def list_templates() -> list[TemplateInfo]:
    out = [
        _info(docx_ops._BASE_TEMPLATE, key=_BUILTIN_KEY, name=_BUILTIN_NAME, builtin=True)
    ]
    # stat 竞态（glob 到 stat 之间文件被删）跳过该行，不为一个消失的文件 500
    items: list[tuple[float, Path]] = []
    for p in _templates_dir().glob("*.docx"):
        try:
            items.append((p.stat().st_mtime, p))
        except OSError:
            continue
    for _, p in sorted(items, reverse=True):
        try:
            out.append(_info(p, key=p.name, name=p.stem, builtin=False))
        except OSError:
            continue
    return out


@router.post("/templates", status_code=201)
async def upload_template(file: UploadFile = File(...)) -> TemplateInfo:
    raw = file.filename or ""
    name = Path(raw).name.strip()
    if not name or name.startswith(".") or Path(name).suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="仅支持 .docx 模板文件")
    tmp = _templates_dir() / f".{name}.{uuid.uuid4().hex[:8]}.part"
    size = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_TEMPLATE_BYTES:
                    raise HTTPException(status_code=413, detail="模板文件超过 20MB 上限")
                f.write(chunk)
        # 可打开校验：损坏/伪装 docx 立即拒收——起建时才炸会让用户换模板后
        # 第一次建节报错，错误离决策点太远
        try:
            _DocxDocument(str(tmp))
        except Exception:
            raise HTTPException(
                status_code=400, detail="文件不是可解析的 Word 文档，请确认上传的是 .docx 模板"
            )
        dest = _templates_dir() / name
        os.replace(tmp, dest)  # 同名覆盖=上传新版语义（若正激活则即刻生效）
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return _info(dest, key=dest.name, name=dest.stem, builtin=False)


@router.delete("/templates/{key}")
async def delete_template(key: str):
    if key == _BUILTIN_KEY:
        raise HTTPException(status_code=400, detail="内置模板不可删除")
    p = _resolve(key)
    p.unlink()
    # 删的是当前生效模板：回落内置（不留悬空激活位）
    if _active_name() == p.name:
        db.set_setting(docx_ops.TEMPLATE_SETTING_KEY, "")
    return {"ok": True}


@router.post("/templates/{key}/activate")
async def activate_template(key: str):
    _resolve(key)  # 存在性校验（内置键恒可激活）
    if key == _BUILTIN_KEY:
        db.set_setting(docx_ops.TEMPLATE_SETTING_KEY, "")
    else:
        db.set_setting(docx_ops.TEMPLATE_SETTING_KEY, Path(key).name)
    return {"ok": True}


@router.get("/templates/{key}/raw")
async def template_raw(key: str):
    p = _resolve(key)
    return FileResponse(
        str(p),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=p.name,
    )


@router.post("/templates/apply", response_model=RestyleReport)
def apply_template(body: _ApplyBody) -> RestyleReport:
    """把当前生效模板应用到任务已有正文节（用户显式操作；整本-派生物跳过，
    换装后如需整本可重新合册）。同步 def（非 async）：几十节的循环是磁盘
    密集型，FastAPI 会丢线程池执行，不阻塞事件循环上的 SSE 心跳。"""
    if not db.get_task(body.task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    for cid in db.list_task_conversation_ids(body.task_id):
        if db.active_run_exists(cid):
            raise HTTPException(
                status_code=409, detail="任务下有正在运行的会话，请等运行结束后再应用模板"
            )
    wroot = artifact_store.work_dir(body.task_id) / "body"
    report = RestyleReport()
    if not wroot.is_dir():
        return report
    for p in sorted(wroot.rglob("*.docx")):
        rel = str(p.relative_to(wroot))
        if p.name.startswith("整本-"):
            report.skipped_volumes += 1
            continue
        try:
            stats = docx_ops.restyle_docx(p)
            report.applied += 1
            report.results.append(RestyleResult(file=rel, ok=True, elements=stats["elements"]))
        except Exception as e:  # 单节失败不中断（工具铁律：人话报错带回报告）
            report.failed += 1
            report.results.append(RestyleResult(file=rel, ok=False, error=str(e)[:200]))
    return report
