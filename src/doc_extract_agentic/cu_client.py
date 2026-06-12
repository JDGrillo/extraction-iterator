from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .models import ExtractionCandidate, OutputSchema

logger = logging.getLogger(__name__)


class AzureContentUnderstandingClient:
    """
    Wrapper for Azure Content Understanding REST API.

    This client analyzes documents and extracts fields using Azure Content Understanding.
    It maps extracted fields to your schema aliases and returns ExtractionCandidates.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "prebuilt-document",
        api_version: str = "2025-11-01",
    ):
        # Keep parameter name "model" for backward compatibility with existing config.
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.analyzer_id = model
        self.api_version = api_version
        self._client = None
        self.poll_interval_seconds = 1.0
        self.max_poll_attempts = 30

    def _get_client(self):
        """Validate configuration and return a client marker.

        Content Understanding is called via REST in this implementation.
        """
        if self._client is None:
            if not self.endpoint or not self.api_key:
                logger.warning(
                    "Azure Content Understanding endpoint/api_key missing; CU client unavailable"
                )
                self._client = None
            else:
                self._client = True
        return self._client

    def is_configured(self) -> bool:
        """Return True when endpoint and API key are set for Azure CU calls."""
        return bool(self._get_client())

    def _analyze_url(self) -> str:
        analyzer_id = urllib.parse.quote(self.analyzer_id, safe="")
        return (
            f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze"
            f"?api-version={self.api_version}"
        )

    def _to_payload(self, file_path: Path) -> bytes:
        mime_type, _ = mimetypes.guess_type(file_path.name)
        mime_type = mime_type or "application/octet-stream"

        file_data = file_path.read_bytes()
        encoded_data = base64.b64encode(file_data).decode("ascii")

        payload = {
            "inputs": [
                {
                    "name": file_path.name,
                    "mimeType": mime_type,
                    "data": encoded_data,
                }
            ]
        }
        return json.dumps(payload).encode("utf-8")

    def _submit_analyze(self, file_path: Path) -> str | None:
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(
            url=self._analyze_url(),
            data=self._to_payload(file_path),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                operation_location = response.headers.get("Operation-Location")
                if not operation_location:
                    logger.warning(
                        "Azure CU analyze accepted but Operation-Location header missing for %s",
                        file_path.name,
                    )
                    return None
                return operation_location
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.warning(
                "Azure CU analyze request failed for %s (status=%s): %s",
                file_path.name,
                exc.code,
                body,
            )
        except urllib.error.URLError as exc:
            logger.warning(
                "Azure CU analyze request failed for %s: %s",
                file_path.name,
                exc,
            )
        except (OSError, ValueError) as exc:
            logger.warning(
                "Azure CU analyze request failed for %s: %s",
                file_path.name,
                exc,
            )
        return None

    def _poll_result(
        self, operation_location: str, file_name: str
    ) -> dict[str, Any] | None:
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
        }

        for _ in range(self.max_poll_attempts):
            request = urllib.request.Request(
                url=operation_location,
                headers=headers,
                method="GET",
            )

            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                logger.warning(
                    "Azure CU polling failed for %s (status=%s): %s",
                    file_name,
                    exc.code,
                    body,
                )
                return None
            except (
                urllib.error.URLError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                logger.warning("Azure CU polling failed for %s: %s", file_name, exc)
                return None

            status = str(data.get("status", "")).lower()
            if status == "succeeded":
                return data
            if status in {"failed", "canceled", "cancelled"}:
                logger.warning(
                    "Azure CU analyze did not succeed for %s (status=%s)",
                    file_name,
                    data.get("status"),
                )
                return None

            time.sleep(self.poll_interval_seconds)

        logger.warning("Azure CU polling timed out for %s", file_name)
        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().replace("_", " ").split())

    def _map_field_name(
        self,
        raw_name: str,
        field_aliases: dict[str, list[str]],
        schema: OutputSchema,
    ) -> str | None:
        normalized_raw = self._normalize(raw_name)

        # First pass: exact normalized alias match.
        for field_name, aliases in field_aliases.items():
            candidates = aliases + [field_name]
            if any(self._normalize(alias) == normalized_raw for alias in candidates):
                return field_name

        # Second pass: normalized contains relation.
        for field_name, aliases in field_aliases.items():
            candidates = aliases + [field_name]
            for alias in candidates:
                normalized_alias = self._normalize(alias)
                if normalized_alias and (
                    normalized_alias in normalized_raw
                    or normalized_raw in normalized_alias
                ):
                    return field_name

        # Last pass: direct schema field name fallback.
        for field in schema.fields:
            if self._normalize(field.name) == normalized_raw:
                return field.name

        return None

    def _extract_value_and_confidence(
        self, field_data: dict[str, Any]
    ) -> tuple[str, float]:
        confidence_raw = field_data.get("confidence", 0.78)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.78

        for key in (
            "valueString",
            "valueNumber",
            "valueInteger",
            "valueBoolean",
            "valueDate",
            "valueTime",
        ):
            if key in field_data and field_data[key] is not None:
                return str(field_data[key]), confidence

        if "content" in field_data and field_data["content"] is not None:
            return str(field_data["content"]), confidence

        if "valueObject" in field_data and isinstance(field_data["valueObject"], dict):
            return json.dumps(field_data["valueObject"], ensure_ascii=False), confidence

        if "valueArray" in field_data and isinstance(field_data["valueArray"], list):
            return json.dumps(field_data["valueArray"], ensure_ascii=False), confidence

        return "", confidence

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
            logger.warning("Azure CU client not available; skipping %s", file_path.name)
            return candidates

        operation_location = self._submit_analyze(file_path)
        if not operation_location:
            return candidates

        result_payload = self._poll_result(operation_location, file_path.name)
        if not result_payload:
            return candidates

        contents = (
            result_payload.get("result", {}).get("contents", [])
            if isinstance(result_payload, dict)
            else []
        )

        for idx, content in enumerate(contents):
            fields = content.get("fields", {}) if isinstance(content, dict) else {}
            if not isinstance(fields, dict):
                continue

            for raw_name, field_data in fields.items():
                if not isinstance(raw_name, str) or not isinstance(field_data, dict):
                    continue

                mapped_name = self._map_field_name(raw_name, field_aliases, schema)
                if not mapped_name:
                    continue

                value, confidence = self._extract_value_and_confidence(field_data)
                if not value:
                    continue

                candidates.append(
                    ExtractionCandidate(
                        field_name=mapped_name,
                        value=value,
                        confidence=confidence,
                        extractor="azure_cu",
                        source_ref=f"{file_path.name}:content_{idx}:field_{raw_name}",
                    )
                )

        logger.info(
            "Azure CU extracted %s candidates from %s",
            len(candidates),
            file_path.name,
        )

        return candidates
