"""pdfium 引擎（PyMuPDF 替换批：四级识别链的引擎原语实现）。

原语全部经 pdfium_kit（全局锁纪律——PDFium 官方禁多线程）；文本块/表格
见 pdf_text / pdf_tables。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from . import pdf_tables, pdf_text, pdfium_kit
from .pdf import Block, Table

logger = logging.getLogger(__name__)


class Engine:
    name = "pdfium"

    def open(self, path: Path | str):
        return pdfium_kit.open_document(path)

    def n_pages(self, doc) -> int:
        return pdfium_kit.n_pages(doc)

    def iter_pages(self, doc) -> Iterator[tuple[int, object]]:
        for i in range(pdfium_kit.n_pages(doc)):
            yield i + 1, pdfium_kit.get_page(doc, i)

    def page_height(self, page) -> float:
        return pdfium_kit.page_size(page)[1]

    def text_blocks(self, page) -> list[Block]:
        return pdf_text.text_blocks(page)

    def page_text(self, page) -> str:
        return pdf_text.page_text(page)

    def find_tables(self, page) -> list[Table]:
        # 与旧 mupdf 引擎同款兜底：识别异常降级为无表（不让整份解析崩掉），
        # 不静默——留日志可诊断
        try:
            return pdf_tables.find_tables(page)
        except Exception:
            logger.exception("pdfium 表格识别异常，本页降级为无表")
            return []

    def toc(self, doc) -> list[tuple[int, str, int]]:
        return pdfium_kit.toc(doc)

    def goto_links(self, doc, page) -> list[tuple[tuple[float, float, float, float], int]]:
        return pdfium_kit.goto_links(doc, page)

    def text_in_rect(self, page, rect: tuple[float, float, float, float]) -> str:
        return pdfium_kit.text_in_rect(page, rect)


ENGINE = Engine()
