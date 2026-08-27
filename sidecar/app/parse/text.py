"""txt/md 透传（gb18030 兜底）。自 tools/parse_document.py 迁入，逻辑不变。"""

from __future__ import annotations

from pathlib import Path

from . import ParseResult, register


def read_text_auto(p: Path) -> str:
    """txt/md 读取：utf-8 优先，中文遗留编码（gb18030 超集）兜底。"""
    raw = p.read_bytes()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@register([".txt", ".md"])
def convert(path: Path) -> ParseResult:
    ext = path.suffix.lower()
    return ParseResult(
        read_text_auto(path),
        {"conversion": "txt-passthrough" if ext == ".txt" else "md-passthrough", "tables": 0},
    )
