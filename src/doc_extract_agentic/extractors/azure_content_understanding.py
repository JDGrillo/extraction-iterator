from __future__ import annotations

import logging
from pathlib import Path

from ..cu_client import AzureContentUnderstandingClient
from ..cu_initialization import validate_cu_config
from ..models import ExtractionCandidate, OutputSchema
from .base import BaseExtractor

logger = logging.getLogger(__name__)


class AzureContentUnderstandingExtractor(BaseExtractor):
    name = "azure_cu"
    _client = None

    def extract(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[ExtractionCandidate]:
        """
        Extract candidates using Azure Content Understanding.

        Falls back gracefully if config is incomplete or the service is unavailable.
        """
        cu_cfg = config.get("azure_content_understanding", {})

        if not cu_cfg.get("enabled", False):
            return []

        is_valid, error_msg = validate_cu_config(config)
        if not is_valid:
            logger.debug("Azure CU not configured: %s", error_msg)
            return []

        # Lazy-initialize client
        if self._client is None:
            self._client = AzureContentUnderstandingClient(
                endpoint=cu_cfg.get("endpoint", ""),
                api_key=cu_cfg.get("api_key", ""),
                model=cu_cfg.get("model", "prebuilt-document"),
                api_version=cu_cfg.get("api_version", "2025-11-01"),
            )

        # Build field aliases from schema
        field_aliases = {
            field.name: field.aliases + [field.name] for field in schema.fields
        }

        return self._client.analyze_document(
            file_path=file_path,
            schema=schema,
            field_aliases=field_aliases,
        )
