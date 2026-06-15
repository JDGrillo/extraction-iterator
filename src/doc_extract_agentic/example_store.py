from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExampleRecord:
    source_file: str
    sheet_markdown: str
    output: dict[str, Any]
    quality_score: float = 1.0
    split: str = "train"
    metadata: dict[str, Any] | None = None


class ExampleStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[ExampleRecord]:
        if not self.path.exists():
            return []

        records: list[ExampleRecord] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                output = raw.get("output")
                if not isinstance(output, dict):
                    continue
                records.append(
                    ExampleRecord(
                        source_file=str(raw.get("source_file", "")),
                        sheet_markdown=str(raw.get("sheet_markdown", "")),
                        output=output,
                        quality_score=_safe_float(raw.get("quality_score", 1.0), 1.0),
                        split=str(raw.get("split", "train") or "train").lower(),
                        metadata=(
                            raw.get("metadata")
                            if isinstance(raw.get("metadata"), dict)
                            else None
                        ),
                    )
                )
        return records

    def retrieve(
        self,
        query_text: str,
        k: int = 3,
        mode: str = "hybrid",
        split: str = "train",
    ) -> list[ExampleRecord]:
        records = self.load()
        if not records:
            return []

        split_l = split.lower()
        split_records = [r for r in records if r.split == split_l]
        if split_records:
            records = split_records

        q_tokens = _tokens(query_text)
        if not q_tokens:
            return records[:k]

        mode_l = mode.lower().strip()
        scored: list[tuple[float, ExampleRecord]] = []

        q_vec = _vectorize_text(query_text)
        for record in records:
            lexical = _jaccard(q_tokens, _tokens(record.sheet_markdown))
            semantic = _cosine_similarity(q_vec, _vectorize_text(record.sheet_markdown))

            if mode_l == "lexical":
                score = lexical
            elif mode_l == "semantic":
                score = semantic
            else:
                # Hybrid mode balances label overlap and structural/text similarity.
                score = (0.35 * lexical) + (0.65 * semantic)

            score *= max(0.05, min(1.5, record.quality_score))
            if score > 0.0:
                scored.append((score, record))

        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            return [r for _, r in scored[:k]]
        return records[:k]

    def append(self, record: ExampleRecord, deduplicate: bool = True) -> None:
        existing = self.load() if deduplicate else []
        if deduplicate:
            for idx, prior in enumerate(existing):
                if _record_key(prior) != _record_key(record):
                    continue

                # Keep the higher quality copy and merge metadata.
                if record.quality_score >= prior.quality_score:
                    existing[idx] = ExampleRecord(
                        source_file=record.source_file,
                        sheet_markdown=record.sheet_markdown,
                        output=record.output,
                        quality_score=record.quality_score,
                        split=record.split,
                        metadata=_merge_metadata(prior.metadata, record.metadata),
                    )
                    self._rewrite(existing)
                return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_file": record.source_file,
            "sheet_markdown": record.sheet_markdown,
            "output": record.output,
            "quality_score": round(record.quality_score, 4),
            "split": (record.split or "train").lower(),
        }
        if record.metadata:
            payload["metadata"] = record.metadata
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def _rewrite(self, records: list[ExampleRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for record in records:
                payload = {
                    "source_file": record.source_file,
                    "sheet_markdown": record.sheet_markdown,
                    "output": record.output,
                    "quality_score": round(record.quality_score, 4),
                    "split": (record.split or "train").lower(),
                }
                if record.metadata:
                    payload["metadata"] = record.metadata
                f.write(json.dumps(payload) + "\n")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _vectorize_text(text: str) -> dict[str, float]:
    tokens = list(_tokens(text))
    if not tokens:
        return {}

    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
        for gram in _char_ngrams(token, n=3):
            key = f"g:{gram}"
            counts[key] = counts.get(key, 0) + 1

    norm = math.sqrt(sum(v * v for v in counts.values()))
    if norm == 0:
        return {}
    return {k: v / norm for k, v in counts.items()}


def _char_ngrams(token: str, n: int) -> set[str]:
    if len(token) < n:
        return {token}
    return {token[i : i + n] for i in range(0, len(token) - n + 1)}


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0

    if len(a) > len(b):
        a, b = b, a
    return sum(val * b.get(key, 0.0) for key, val in a.items())


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _record_key(record: ExampleRecord) -> tuple[str, str]:
    return (record.source_file.strip().lower(), _normalize_text(record.sheet_markdown))


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _merge_metadata(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not left and not right:
        return None
    merged: dict[str, Any] = {}
    if left:
        merged.update(left)
    if right:
        merged.update(right)
    return merged
