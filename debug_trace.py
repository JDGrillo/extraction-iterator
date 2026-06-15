from src.doc_extract_agentic.table_normalizer import (
    normalize_excel_table,
    normalize_golden_data,
)
from src.doc_extract_agentic.column_mapper import auto_map_columns
from src.doc_extract_agentic.rule_applier import RuleApplier
from src.doc_extract_agentic.mapping_learner import LearnedRule
from pathlib import Path
import re

schema = [
    "Location Name",
    "Occupancy Type",
    "Street / Address Text",
    "City",
    "State",
    "ZIP",
    "Building Value",
    "Contents Value",
    "Equipment Value",
    "Business Income Value",
    "Total Insured Value",
]
t = normalize_excel_table(Path("input/extract-test-input.xlsx"))
g = normalize_golden_data(Path("output/extract-test-output.xlsx"))

col_map = auto_map_columns(t.rows, g, schema)
applier = RuleApplier()
rules = [
    LearnedRule(
        field_name=target,
        rule_type="column_alias",
        description="auto",
        rule_config={"source_column": src},
        confidence=0.9,
        iteration=0,
    )
    for src, target in col_map.items()
    if src != target
]
print(f"Auto rules ({len(rules)}):")
for r in rules:
    sc = r.rule_config["source_column"]
    print(f"  {sc} -> {r.field_name}")

applier.load_rules(rules)

raw = [r for r in t.rows if not applier.should_skip_row(r)]
row0 = raw[0]
transformed = applier.apply_to_row(row0, schema)
print("\nTransformed row 0:")
for f in schema:
    print(f"  {f}: {repr(transformed[f])}")

golden_first = list(g.values())[0]
print("\nGolden row 0:")
for f in schema:
    print(f'  {f}: {repr(golden_first.get(f,""))}')


def norm(v):
    return re.sub(r"\s+", " ", str(v).strip().lower())


populated = [f for f in schema if norm(golden_first.get(f, ""))]
matched = sum(
    1
    for f in populated
    if norm(transformed.get(f, "")) == norm(golden_first.get(f, ""))
)
print(
    f"\nMatched {matched}/{len(populated)} populated fields = {matched/len(populated):.0%}"
)
