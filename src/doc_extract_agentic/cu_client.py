from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .models import ExtractionCandidate, OutputSchema

logger = logging.getLogger(__name__)


class AzureContentUnderstandingClient:
    """
    Wrapper for Azure Document Intelligence (formerly Form Recognizer) API.

    This client analyzes documents and extracts fields using Azure's AI capabilities.
    It maps extracted fields to your schema aliases and returns ExtractionCandidates.
    """

    def __init__(self, endpoint: str, api_key: str, model: str = "prebuilt-document"):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy-load the Azure SDK client."""
        if self._client is None:
            try:
                from azure.ai.documentintelligence import DocumentIntelligenceClient
                from azure.core.credentials import AzureKeyCredential

                self._client = DocumentIntelligenceClient(
                    endpoint=self.endpoint,
                    credential=AzureKeyCredential(self.api_key),
                )
            except ImportError as e:
                logger.warning(
                    f"Azure Document Intelligence SDK not installed. Install with: pip install azure-ai-documentintelligence. Error: {e}"
                )
                self._client = None
        return self._client

    def analyze_document(
        self,
        file_path: Path,
        schema: OutputSchema,
        field_aliases: dict[str, list[str]],
    ) -> list[ExtractionCandidate]:
        """
        Analyze a document and extract fields based on the schema.

        Args:
            file_path: Path to the document (PDF, XLSX, etc.)
            schema: Output schema defining target fields
            field_aliases: Map of field name to list of aliases

        Returns:
            List of ExtractionCandidate objects
        """
        candidates: list[ExtractionCandidate] = []
        client = self._get_client()

        if client is None:
            logger.warning(f"Azure CU client not available; skipping {file_path.name}")
            return candidates

        try:
            # Read document bytes
            with file_path.open("rb") as f:
                file_data = f.read()

            # Call Azure Document Intelligence API
            from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

            poller = client.begin_analyze_document(
                model_id=self.model,
                analyze_request=AnalyzeDocumentRequest(base64_source=file_data),
            )
            result = poller.result()

            # Extract key-value pairs
            if hasattr(result, "key_value_pairs") and result.key_value_pairs:
                for kv in result.key_value_pairs:
                    key_text = kv.key.content.lower().strip() if kv.key else ""
                    value_text = kv.value.content.strip() if kv.value else ""

                    # Match key against field aliases
                    for field_name, aliases in field_aliases.items():
                        for alias in aliases:
                            if alias.lower() in key_text or key_text == alias.lower():
                                candidates.append(
                                    ExtractionCandidate(
                                        field_name=field_name,
                                        value=value_text,
                                        confidence=0.85,
                                        extractor="azure_cu",
                                        source_ref=f"{file_path.name}:kv_pair",
                                    )
                                )
                                break

            # Extract tables if present
            if hasattr(result, "tables") and result.tables:
                for table in result.tables:
                    for cell in table.cells:
                        cell_text = cell.content.lower().strip() if cell.content else ""
                        # Try to find field aliases in table cells
                        for field_name, aliases in field_aliases.items():
                            for alias in aliases:
                                if alias.lower() in cell_text:
                                    candidates.append(
                                        ExtractionCandidate(
                                            field_name=field_name,
                                            value=cell_text,
                                            confidence=0.78,
                                            extractor="azure_cu",
                                            source_ref=f"{file_path.name}:table_cell",
                                        )
                                    )
                                    break

            logger.info(
                f"Azure CU extracted {len(candidates)} candidates from {file_path.name}"
            )

        except Exception as e:
            logger.warning(f"Azure CU analysis failed for {file_path.name}: {e}")

        return candidates
