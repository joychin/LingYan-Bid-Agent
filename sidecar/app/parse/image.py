"""图片转写转换器：视觉模型把图变文本（VL 定位 = OCR 替代）。

不注册进通用 CONVERTERS（见 __init__.py 注释）：任务工具层不触发外部模型调用，
知识库入库层显式路由。VLM 未配置时抛 VlmUnavailable，由调用方降级
（收原件+登记资产+人工填表，不阻塞上传）。

元数据抽取不在此层——转写产物统一走文本抽取管线（与 docx/pdf 同路），
视觉层职责纯粹：图 → markdown 文本。
"""

from __future__ import annotations

from pathlib import Path

from ..vlm import vlm_read_image
from . import ParseResult

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_TRANSCRIBE_PROMPT = (
    "完整转写这张图片中的所有可见文字（证书/执照/文件/照片均适用），要求：\n"
    "1. 按阅读顺序输出为 markdown；标题、字段名、编号、日期、金额、印章文字都要逐字保留\n"
    "2. 表格用 markdown 表格；印章/签名/照片等非文字元素用「[印章：xxx]」「[签名]」「[照片]」标注\n"
    "3. 无法辨认的字用「□」占位，不要猜测编造\n"
    "4. 只输出转写内容，不要总结、不要评论"
)


def transcribe(path: Path) -> ParseResult:
    """图片 → 视觉模型转写文本。未配置 VLM 抛 VlmUnavailable（调用方降级）。"""
    text = vlm_read_image(Path(path), _TRANSCRIBE_PROMPT)
    return ParseResult(text, {"conversion": "vision", "pages": 1, "tables": 0})
