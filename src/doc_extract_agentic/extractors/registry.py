from __future__ import annotations

from .azure_content_understanding import AzureContentUnderstandingExtractor
from .base import BaseExtractor
from .excel_native import ExcelNativeExtractor
from .pdf_native import PdfNativeExtractor


def build_registry() -> dict[str, BaseExtractor]:
    extractors: list[BaseExtractor] = [
        ExcelNativeExtractor(),
        PdfNativeExtractor(),
        AzureContentUnderstandingExtractor(),
    ]
    return {x.name: x for x in extractors}
