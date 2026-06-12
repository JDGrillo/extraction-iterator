from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SchemaField:
    name: str
    field_type: str
    required: bool = False
    aliases: list[str] = field(default_factory=list)


@dataclass
class OutputSchema:
    schema_name: str
    fields: list[SchemaField]


@dataclass
class DocumentInfo:
    path: Path
    doc_type: str


@dataclass
class ExtractionCandidate:
    field_name: str
    value: Any
    confidence: float
    extractor: str
    source_ref: str


@dataclass
class FieldResult:
    field_name: str
    value: Any
    status: str
    confidence: float
    extractor: str
    source_ref: str


@dataclass
class RunContext:
    run_id: str
    input_dir: Path
    output_dir: Path
