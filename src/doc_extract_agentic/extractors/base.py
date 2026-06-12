from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import ExtractionCandidate, OutputSchema


class BaseExtractor(ABC):
    name: str

    @abstractmethod
    def extract(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[ExtractionCandidate]:
        raise NotImplementedError
