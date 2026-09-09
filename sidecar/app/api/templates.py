"""版式库 API：版式文件管理（上传/删除/设默认/预览）。

版式=格式资产（与素材=内容资产分离，2026-09-08 用户拍板拆库）：版式活在
.docx 的样式表，默认版式=app_settings docx_template（缺省内置基准；同日
用户定名「默认」，原「当前生效」）；建节/合册经 docx_ops.
_active_template_path 读默认位、改动即时生效（无重启）。
定名沿革：2026-09-09 用户拍板「模板库」改名「版式库」（「模板」二字三义
歧义），代码标识符（端点/设置键/目录）保留 templates 不迁。
「应用到已有章节」换装已于 2026-09-08 整链移除（用户拍板没有业务意义）——
版式只管新节外观，已写内容不动。
读侧真值（清单/目录/默认位/内置身份）下沉在 docx_ops——本模块与 LLM 工具
list_templates 同源消费（tools 反向 import api 会循环导入：app.tools 包
初始化先于 api 模块执行）。
"""

import os
import uuid
from pathlib import Path

from docx import Document as _DocxDocument
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import db
from ..contracts.dto import TemplateInfo
from ..tools import docx_ops

router = APIRouter()

_CHUNK = 1024 * 1024
_MAX_TEMPLATE_BYTES = 20 * 1024 * 1024


def _resolve(key: str) -> Path:
    """key → 版式路径（内置键或用户版式文件名；Path.name 清洗防目录穿越）。"""
    if key == docx_ops.BUILTIN_TEMPLATE_KEY:
        return docx_ops._BASE_TEMPLATE
    name = Path(key).name
    if not name or name.startswith("."):
        raise HTTPException(status_code=400, detail="版式文件名非法")
    p = docx_ops.templates_dir() / name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="版式不存在（可能已被删除），请刷新列表")
    return p


@router.get("/templates")
async def list_templates() -> list[TemplateInfo]:
    return [TemplateInfo(**d) for d in docx_ops.list_templates_info()]


@router.post("/templates", status_code=201)
async def upload_template(file: UploadFile = File(...)) -> TemplateInfo:
    raw = file.filename or ""
    name = Path(raw).name.strip()
    if not name or name.startswith(".") or Path(name).suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="仅支持 .docx 版式文件")
    tmp = docx_ops.templates_dir() / f".{name}.{uuid.uuid4().hex[:8]}.part"
    size = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_TEMPLATE_BYTES:
                    raise HTTPException(status_code=413, detail="版式文件超过 20MB 上限")
                f.write(chunk)
        # 可打开校验：损坏/伪装 docx 立即拒收——起建时才炸会让用户换版式后
        # 第一次建节报错，错误离决策点太远
        try:
            _DocxDocument(str(tmp))
        except Exception:
            raise HTTPException(
                status_code=400, detail="文件不是可解析的 Word 文档，请确认上传的是 .docx 版式文件"
            )
        dest = docx_ops.templates_dir() / name
        os.replace(tmp, dest)  # 同名覆盖=上传新版语义（若正激活则即刻生效）
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    row = next(d for d in docx_ops.list_templates_info() if d["key"] == dest.name)
    return TemplateInfo(**row)


@router.delete("/templates/{key}")
async def delete_template(key: str):
    if key == docx_ops.BUILTIN_TEMPLATE_KEY:
        raise HTTPException(status_code=400, detail="内置版式不可删除")
    p = _resolve(key)
    p.unlink()
    # 删的是默认版式：回落内置（不留悬空默认位）
    if docx_ops.active_template_name() == p.name:
        db.set_setting(docx_ops.TEMPLATE_SETTING_KEY, "")
    return {"ok": True}


@router.post("/templates/{key}/activate")
async def activate_template(key: str):
    _resolve(key)  # 存在性校验（内置键恒可激活）
    if key == docx_ops.BUILTIN_TEMPLATE_KEY:
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
