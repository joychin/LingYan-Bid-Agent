"""文档解析注册表：扩展名 → 确定性转换器（docx/pdf/txt/md → markdown）。

知识库入库（app/knowledge/ingest.py）与 LLM 工具（app/tools/parse_document.py）
共用同一套核心转换器；工具层保留场景限制（任务场景不支持图片、扫描件拒绝）。

注册表只收**确定性**转换器（无 LLM 依赖、同输入同输出）。图片与扫描 PDF 页
需要视觉模型，属入库编排层职责（app/parse/image.py 提供转换器但不注册进
CONVERTERS——任务工具层与通用路由都不应静默触发外部模型调用）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = ["ParseResult", "convert", "register", "sha256_file", "supported_exts", "outline_with_lines", "count_nodes"]


@dataclass
class ParseResult:
    """统一转换契约：md 全文 + info 元信息（conversion/pages/tables/…，形状即 meta.json 子集）。"""

    md: str
    info: dict


# ext（含点、小写）→ convert(path) -> ParseResult
CONVERTERS: dict[str, Callable[[Path], ParseResult]] = {}


def register(exts: list[str]) -> Callable:
    def deco(fn: Callable[[Path], ParseResult]) -> Callable:
        for e in exts:
            CONVERTERS[e] = fn
        return fn

    return deco


def supported_exts() -> list[str]:
    return sorted(CONVERTERS)


def convert(path: Path) -> ParseResult:
    ext = Path(path).suffix.lower()
    fn = CONVERTERS.get(ext)
    if fn is None:
        raise ValueError(
            f"不支持的输入格式：{ext}（支持 {' '.join(supported_exts())}；"
            ".doc 请用 Word 另存为 .docx 后再上传）"
        )
    return fn(Path(path))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path: Path, text: str) -> None:
    """解析产物原子写（tmp + rename）：读者要么看到旧文件要么看到新文件，绝不读到
    截断内容。tmp 名带随机后缀——工具重跑/入库管线并发写同一目标时互不截断。
    产物三件套的落盘约定：md → outline → meta 顺序写、meta 最后写（隐式提交标记，
    幂等检查三件齐 + sha 一致才跳过重解析）。"""
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# 带行号区间的标题大纲（依赖惰性导入防循环）
def outline_with_lines(md_text: str) -> list[dict]:
    from .outline import outline_with_lines as _impl

    return _impl(md_text)


def count_nodes(tree: list[dict]) -> int:
    from .outline import count_nodes as _impl

    return _impl(tree)


# 触发注册（import 副作用：把内置转换器挂上注册表）
from . import docx as _docx  # noqa: E402,F401
from . import pdf as _pdf  # noqa: E402,F401
from . import text as _text  # noqa: E402,F401
