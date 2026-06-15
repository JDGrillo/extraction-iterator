from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..example_store import ExampleStore
from ..local_llm_client import LocalLLMClient
from ..models import ExtractionCandidate, OutputSchema
from ..sheet_serializer import serialize_excel_for_llm
from .base import BaseExtractor


class LLMNativeExtractor(BaseExtractor):
    name = "llm_native"

    def extract(
        self,
        file_path: Path,
        schema: OutputSchema,
        config: dict,
    ) -> list[ExtractionCandidate]:
        if file_path.suffix.lower() not in {".xlsx", ".xls"}:
            return []

        client = LocalLLMClient.from_config(config)
        if not client.is_ready():
            return []

        llm_cfg = config.get("llm_extractor", {})
        example_store_path = Path(
            str(llm_cfg.get("example_store", "./examples/training_examples.jsonl"))
        )
        max_examples = int(llm_cfg.get("max_examples", 3))
        retrieval_mode = str(llm_cfg.get("retrieval_mode", "hybrid"))
        default_confidence = float(llm_cfg.get("default_confidence", 0.95))

        focus_terms: list[str] = []
        for field in schema.fields:
            focus_terms.append(field.name)
            focus_terms.extend(field.aliases)

        workbook_text = serialize_excel_for_llm(
            file_path=file_path,
            max_sheets=int(llm_cfg.get("max_sheets", 5)),
            max_rows_per_sheet=int(llm_cfg.get("max_rows_per_sheet", 80)),
            max_cols_per_sheet=int(llm_cfg.get("max_cols_per_sheet", 20)),
            max_cell_chars=int(llm_cfg.get("max_cell_chars", 120)),
            focus_terms=focus_terms,
        )
        if not workbook_text:
            return []

        examples = ExampleStore(example_store_path).retrieve(
            workbook_text,
            k=max_examples,
            mode=retrieval_mode,
            split="train",
        )

        field_names_csv = ", ".join(f.name for f in schema.fields)

        # Build a compact user prompt: optional examples then the slimmed workbook.
        user_parts: list[str] = []
        for ex in examples:
            user_parts.append(
                f"Example:\n{ex.sheet_markdown}\nOutput: {json.dumps(ex.output)}"
            )
        user_parts.append(f"Spreadsheet:\n{workbook_text}")
        user_prompt = "\n\n".join(user_parts)

        system_prompt = (
            f"Extract these fields from the spreadsheet: {field_names_csv}.\n"
            "Return ONLY a JSON object with three keys:\n"
            '  "fields": {field_name: value_or_null}\n'
            '  "confidence": {field_name: 0.0-1.0}\n'
            '  "evidence": {field_name: cell_ref_or_explanation}\n'
            "Use exact field names. No prose, no markdown fences."
        )

        parsed = client.chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
        if not parsed:
            return []

        extracted_fields = parsed.get("fields", {})
        confidence_map = parsed.get("confidence", {})
        evidence_map = parsed.get("evidence", {})
        if not isinstance(extracted_fields, dict):
            return []

        field_names = {f.name for f in schema.fields}
        candidates: list[ExtractionCandidate] = []

        for field_name, value in extracted_fields.items():
            if field_name not in field_names:
                continue
            if value is None:
                continue
            text_value = str(value).strip()
            if not text_value:
                continue

            confidence = _safe_float(confidence_map.get(field_name), default_confidence)
            confidence = max(0.0, min(1.0, confidence))
            source_ref = (
                str(evidence_map.get(field_name, "llm_inference")).strip()
                or "llm_inference"
            )

            candidates.append(
                ExtractionCandidate(
                    field_name=field_name,
                    value=text_value,
                    confidence=confidence,
                    extractor=self.name,
                    source_ref=f"{file_path.name}:{source_ref}",
                )
            )

        return candidates


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
