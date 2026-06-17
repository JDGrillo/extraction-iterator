from __future__ import annotations

import difflib
import re
from pathlib import Path

import pandas as pd

from ..models import ExtractionCandidate, OutputSchema
from .base import BaseExtractor

_SEEN_KEY_LIMIT = 200  # cap how many unmatched keys we record per file
_HEADER_SCAN_LIMIT = 20
_HEADER_FUZZY_CUTOFF = 0.7
_COMMON_HEADER_TOKENS = {
    "location",
    "location name",
    "occupancy",
    "occupancy type",
    "street address",
    "address",
    "city",
    "state",
    "zip",
    "building",
    "building value",
    "contents",
    "contents value",
    "business income",
    "business income value",
    "total insured value",
    "tiv",
}

# Common SOV header normalizations that do not appear in schema aliases.
_HEADER_SYNONYMS = {
    "community entity": "location_name",
    "community": "location_name",
    "location name": "location_name",
    "location occupancy": "occupancy_type",
    "address": "street_address_text",
    "street address": "street_address_text",
    "property address": "street_address_text",
    "st": "state",
    "bldg": "building_value",
    "bldg value": "building_value",
    "contents": "contents_value",
    "equipment": "equipment_value",
    "contents mach equip": "equipment_value",
    "contents mach and equip": "equipment_value",
    "machinery eq": "equipment_value",
    "business income": "business_income_value",
    "100 business income 2026": "business_income_value",
    "bus income": "business_income_value",
    "ap rce building value": "building_value",
    "carrier s quoted building value": "building_value",
    "bus income ee": "business_income_value",
    "business income ee": "business_income_value",
    "total value": "total_insured_value",
    "2026 total": "total_insured_value",
    "tiv": "total_insured_value",
}


class ExcelNativeExtractor(BaseExtractor):
    name = "excel_native"

    def extract(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[ExtractionCandidate]:
        _ = config
        candidates: list[ExtractionCandidate] = []

        try:
            sheets = pd.read_excel(file_path, sheet_name=None, header=None)
        except (OSError, ValueError):
            return candidates

        alias_lookup: dict[str, str] = {}
        alias_terms: list[str] = []
        for field in schema.fields:
            for alias in field.aliases + [field.name]:
                normalized_alias = _normalize_text(alias)
                alias_lookup[normalized_alias] = field.name
                alias_terms.append(normalized_alias)

        for sheet_name, df in sheets.items():
            # Prefer tabular extraction for SOV-style sheets with header rows.
            table_candidates = self._extract_tabular_candidates(
                file_path=file_path,
                sheet_name=sheet_name,
                df=df,
                alias_lookup=alias_lookup,
                alias_terms=alias_terms,
            )
            if table_candidates:
                candidates.extend(table_candidates)
                continue

            # Fallback heuristic: key/value pairs in adjacent cells.
            for row_idx in range(len(df)):
                for col_idx in range(max(0, len(df.columns) - 1)):
                    left = df.iat[row_idx, col_idx]
                    right = df.iat[row_idx, col_idx + 1]
                    if pd.isna(left) or pd.isna(right):
                        continue
                    key = _normalize_text(str(left))
                    if key in alias_lookup:
                        value = _clean_value(right)
                        if not value:
                            continue
                        candidates.append(
                            ExtractionCandidate(
                                field_name=alias_lookup[key],
                                value=value,
                                confidence=0.65,
                                extractor=self.name,
                                source_ref=f"{file_path.name}:{sheet_name}!R{row_idx + 1}C{col_idx + 1}",
                            )
                        )

        return candidates

    def _extract_tabular_candidates(
        self,
        file_path: Path,
        sheet_name: str,
        df: pd.DataFrame,
        alias_lookup: dict[str, str],
        alias_terms: list[str],
    ) -> list[ExtractionCandidate]:
        if df.empty:
            return []

        # 1) Detect the most likely header row in top portion of sheet.
        best_header_idx = None
        best_mapping: dict[int, tuple[str, float]] = {}
        best_score = 0.0
        scan_limit = min(len(df), _HEADER_SCAN_LIMIT)

        for row_idx in range(scan_limit):
            row_mapping: dict[int, tuple[str, float]] = {}
            for col_idx in range(len(df.columns)):
                cell = df.iat[row_idx, col_idx]
                if pd.isna(cell):
                    continue
                field_match = _match_header_to_field(
                    str(cell), alias_lookup, alias_terms
                )
                if not field_match:
                    continue
                field_name, score = field_match

                existing = row_mapping.get(col_idx)
                if existing is None or score > existing[1]:
                    row_mapping[col_idx] = (field_name, score)

            unique_fields = {field for field, _ in row_mapping.values()}
            row_score = sum(score for _, score in row_mapping.values())
            if len(unique_fields) >= 3 and row_score > best_score:
                best_header_idx = row_idx
                best_mapping = row_mapping
                best_score = row_score

        if best_header_idx is None:
            return []

        # 2) Find first likely data row below the header.
        data_row_idx = None
        mapped_cols = list(best_mapping.keys())
        for row_idx in range(best_header_idx + 1, len(df)):
            populated = 0
            for col_idx in mapped_cols:
                if col_idx >= len(df.columns):
                    continue
                cell = df.iat[row_idx, col_idx]
                if _clean_value(cell):
                    populated += 1
            if populated >= 3:
                data_row_idx = row_idx
                break

        if data_row_idx is None:
            return []

        # 3) Emit candidates from mapped header columns using best field per column.
        per_field: dict[str, ExtractionCandidate] = {}
        for col_idx, (field_name, match_score) in best_mapping.items():
            if col_idx >= len(df.columns):
                continue
            value = _clean_value(df.iat[data_row_idx, col_idx])
            if not value:
                continue
            confidence = 0.7 if match_score < 0.95 else 0.8
            candidate = ExtractionCandidate(
                field_name=field_name,
                value=value,
                confidence=confidence,
                extractor=self.name,
                source_ref=(
                    f"{file_path.name}:{sheet_name}!R{data_row_idx + 1}C{col_idx + 1}"
                ),
            )

            # If multiple columns map to same field, keep higher-confidence candidate.
            existing = per_field.get(field_name)
            if existing is None or candidate.confidence > existing.confidence:
                per_field[field_name] = candidate

        return list(per_field.values())

    def extract_all_rows(
        self, file_path: Path, schema: OutputSchema, config: dict
    ) -> list[dict[str, str]]:
        """
        Extract every data row from tabular sheets as a list of dicts keyed by
        schema field name. Rows with fewer than 2 populated fields are excluded
        (catches trailing notes/comments).
        """
        _ = config
        rows: list[dict[str, str]] = []

        try:
            sheets = pd.read_excel(file_path, sheet_name=None, header=None)
        except (OSError, ValueError):
            return rows

        alias_lookup: dict[str, str] = {}
        alias_terms: list[str] = []
        for field in schema.fields:
            for alias in field.aliases + [field.name]:
                normalized = _normalize_text(alias)
                alias_lookup[normalized] = field.name
                alias_terms.append(normalized)

        best_rows: list[dict[str, str]] = []
        best_score = -1.0

        for sheet_name, df in sheets.items():
            table_rows = self._extract_all_tabular_rows(
                file_path=file_path,
                sheet_name=sheet_name,
                df=df,
                alias_lookup=alias_lookup,
                alias_terms=alias_terms,
                schema_fields=[f.name for f in schema.fields],
            )
            if not table_rows:
                continue

            # Prefer SOV-like sheets: many rows with total_insured_value populated.
            tiv_rows = sum(
                1
                for r in table_rows
                if str(r.get("total_insured_value", "")).strip()
            )
            score = (tiv_rows * 10.0) + len(table_rows)
            if score > best_score:
                best_score = score
                best_rows = table_rows

        if best_rows:
            return best_rows

        return rows

    def _extract_all_tabular_rows(
        self,
        file_path: Path,
        sheet_name: str,
        df: pd.DataFrame,
        alias_lookup: dict[str, str],
        alias_terms: list[str],
        schema_fields: list[str],
    ) -> list[dict[str, str]]:
        if df.empty:
            return []

        # Detect header row (same logic as tabular candidate extraction).
        best_header_idx = None
        best_mapping: dict[int, str] = {}
        best_score = 0.0
        scan_limit = min(len(df), _HEADER_SCAN_LIMIT)

        for row_idx in range(scan_limit):
            row_mapping: dict[int, tuple[str, float]] = {}
            for col_idx in range(len(df.columns)):
                cell = df.iat[row_idx, col_idx]
                if pd.isna(cell):
                    continue
                field_match = _match_header_to_field(
                    str(cell), alias_lookup, alias_terms
                )
                if not field_match:
                    continue
                field_name, score = field_match
                existing = row_mapping.get(col_idx)
                if existing is None or score > existing[1]:
                    row_mapping[col_idx] = (field_name, score)

            unique_fields = {f for f, _ in row_mapping.values()}
            row_score = sum(s for _, s in row_mapping.values())
            if len(unique_fields) >= 3 and row_score > best_score:
                best_header_idx = row_idx
                best_mapping = {col: fname for col, (fname, _) in row_mapping.items()}
                best_score = row_score

        if best_header_idx is None:
            return []

        # Build normalized header-token hints per mapped field for repeated-header detection.
        field_header_tokens: dict[str, set[str]] = {}
        for col_idx, field_name in best_mapping.items():
            if col_idx >= len(df.columns):
                continue
            header_cell = _clean_value(df.iat[best_header_idx, col_idx])
            token = _normalize_text(header_cell)
            if not token:
                continue
            field_header_tokens.setdefault(field_name, set()).add(token)

        # Collect columns that didn't match any schema alias so that downstream
        # column_alias rules (learned and loaded in the pipeline) can remap them.
        unmatched_cols: dict[int, str] = {}
        for col_idx in range(len(df.columns)):
            if col_idx in best_mapping:
                continue
            cell = df.iat[best_header_idx, col_idx]
            if not pd.isna(cell):
                raw_header = str(cell).strip()
                if raw_header:
                    unmatched_cols[col_idx] = raw_header

        # Iterate every data row below the header.
        results: list[dict[str, str]] = []
        mapped_schema_fields = set(best_mapping.values())
        for row_idx in range(best_header_idx + 1, len(df)):
            row_dict: dict[str, str] = {}
            for col_idx, field_name in best_mapping.items():
                if col_idx >= len(df.columns):
                    continue
                value = _clean_value(df.iat[row_idx, col_idx])
                if value:
                    row_dict[field_name] = value

            # Preserve unmatched columns by raw header name so column_alias
            # rules (loaded in the pipeline) can remap them to schema fields.
            for col_idx, raw_header in unmatched_cols.items():
                if col_idx >= len(df.columns):
                    continue
                value = _clean_value(df.iat[row_idx, col_idx])
                if value:
                    row_dict[raw_header] = value

            # Require at least 2 populated schema fields to exclude note rows,
            # AND at least one identity field (location name, address, or occupancy)
            # must be present to exclude totals rows and other non-location data.
            _IDENTITY_FIELDS = {
                "location_name",
                "street_address_text",
                "occupancy_type",
            }
            # Count only schema fields (not raw header columns) for the threshold
            schema_field_count = sum(1 for f in schema_fields if f in row_dict)
            has_enough_fields = schema_field_count >= 2
            has_identity = bool(row_dict.keys() & _IDENTITY_FIELDS)

            # Drop repeated section headers where values mirror column titles.
            if _is_header_like_row(row_dict, field_header_tokens):
                continue

            # If location_name is missing but row has address context, synthesize a stable label.
            if not row_dict.get("location_name"):
                synthesized = _synthesize_location_name(row_dict)
                if synthesized:
                    row_dict["location_name"] = synthesized
                    has_identity = True

            if not _passes_sov_row_gate(row_dict, mapped_schema_fields):
                continue

            if has_enough_fields and has_identity:
                # Include raw-header keys for unmatched columns alongside schema
                # field keys. apply_to_row in the pipeline will apply column_alias
                # rules and then filter down to schema fields.
                results.append(row_dict)

        return results

    def collect_raw_keys(self, file_path: Path) -> list[str]:
        """Return all unique non-empty cell-label keys seen in the file."""
        seen: set[str] = set()
        try:
            sheets = pd.read_excel(file_path, sheet_name=None, header=None)
        except (OSError, ValueError):
            return []
        for df in sheets.values():
            for row_idx in range(len(df)):
                for col_idx in range(max(0, len(df.columns) - 1)):
                    left = df.iat[row_idx, col_idx]
                    right = df.iat[row_idx, col_idx + 1]
                    if pd.isna(left) or pd.isna(right):
                        continue
                    key = _normalize_text(str(left))
                    if key:
                        seen.add(key)
                    if len(seen) >= _SEEN_KEY_LIMIT:
                        return list(seen)
        return list(seen)


def _normalize_text(value: str) -> str:
    text = str(value).replace("\n", " ").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = " ".join(text.split())
    return text


def _match_header_to_field(
    header_text: str,
    alias_lookup: dict[str, str],
    alias_terms: list[str],
) -> tuple[str, float] | None:
    key = _normalize_text(header_text)
    if not key:
        return None

    # Exact schema alias match.
    if key in alias_lookup:
        return alias_lookup[key], 1.0

    # Domain-specific SOV synonyms.
    if key in _HEADER_SYNONYMS:
        return _HEADER_SYNONYMS[key], 0.95

    # Fuzzy match against known aliases.
    match = difflib.get_close_matches(
        key, alias_terms, n=1, cutoff=_HEADER_FUZZY_CUTOFF
    )
    if not match:
        return None
    matched_alias = match[0]
    score = difflib.SequenceMatcher(None, key, matched_alias).ratio()
    field_name = alias_lookup.get(matched_alias)
    if not field_name:
        return None
    return field_name, score


def _clean_value(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def _is_positive_number(value: str) -> bool:
    """Return True if value is parseable and > 0."""
    if not value:
        return False
    cleaned = value.replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned) > 0
    except ValueError:
        return False


def _passes_sov_row_gate(row_dict: dict[str, str], mapped_fields: set[str]) -> bool:
    """
    Stricter filter for SOV-like layouts to drop subtotal/summary rows.
    Applies only when core SOV fields are present in the mapped header.
    """
    required = {"total_insured_value", "street_address_text", "city", "state"}
    if not required.issubset(mapped_fields):
        return True

    tiv = row_dict.get("total_insured_value", "")
    street = row_dict.get("street_address_text", "").strip()
    city = row_dict.get("city", "").strip()
    state = row_dict.get("state", "").strip()
    location_name = row_dict.get("location_name", "").strip().lower()

    if not _is_positive_number(str(tiv)):
        return False
    if not street or street == "*":
        return False
    if not city or city == "*":
        return False
    if len(state) != 2 or not state.isalpha():
        return False
    if location_name.startswith("total "):
        return False

    return True


def _is_header_like_row(
    row_dict: dict[str, str], field_header_tokens: dict[str, set[str]]
) -> bool:
    """Detect repeated section-header rows that were misread as data."""
    if not row_dict:
        return True

    token_hits = 0
    checked = 0
    for field_name, value in row_dict.items():
        norm_val = _normalize_text(value)
        if not norm_val:
            continue
        checked += 1

        if norm_val in _COMMON_HEADER_TOKENS:
            token_hits += 1
            continue

        field_tokens = field_header_tokens.get(field_name, set())
        if norm_val in field_tokens:
            token_hits += 1
            continue

        if norm_val == _normalize_text(field_name):
            token_hits += 1

    if checked == 0:
        return True

    # Header-like rows usually have many cells matching schema/header tokens.
    return token_hits >= 2 and token_hits / checked >= 0.5


def _synthesize_location_name(row_dict: dict[str, str]) -> str:
    """Build a fallback location name when source lacks a dedicated name column."""
    street = row_dict.get("street_address_text", "").strip()
    city = row_dict.get("city", "").strip()
    state = row_dict.get("state", "").strip()
    occupancy = row_dict.get("occupancy_type", "").strip()

    if not street:
        return ""

    base = street
    if city and state:
        base = f"{street}, {city}, {state}"
    elif city:
        base = f"{street}, {city}"
    elif state:
        base = f"{street}, {state}"

    occ_norm = _normalize_text(occupancy)
    if occupancy and occ_norm and occ_norm not in _COMMON_HEADER_TOKENS:
        return f"{base} ({occupancy})"

    return base

