from __future__ import annotations

from .base import BaseExtractor
from .excel_native import ExcelNativeExtractor
from .llm_native import LLMNativeExtractor
from .pdf_native import PdfNativeExtractor


def build_registry() -> dict[str, BaseExtractor]:
    extractors: list[BaseExtractor] = [
        LLMNativeExtractor(),
        ExcelNativeExtractor(),
        PdfNativeExtractor(),
    ]
    return {x.name: x for x in extractors}
