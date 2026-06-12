from __future__ import annotations

from pathlib import Path

from ..models import ExtractionCandidate, OutputSchema
from .base import BaseExtractor


class AzureContentUnderstandingExtractor(BaseExtractor):
    name = "azure_cu"

    def extract(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[ExtractionCandidate]:
        # Baseline template intentionally returns no candidates.
        # Replace this with Azure CU API calls and map returned fields to schema aliases.
        # Keep this extractor optional via config so the pipeline works without Azure dependencies.
        _ = (file_path, schema, config)
        return []
