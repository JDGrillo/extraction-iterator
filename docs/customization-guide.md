# Customization Guide

## 0) Drop-In Usage Pattern

Canonical docs for this repository:
- `docs/PRD.md`
- `docs/architecture.md`
- `docs/customization-guide.md`

This repository is designed around two primary workflows:

1. Place source files in an input folder (nested folders supported)
2. Run extraction with `doc-extract-run`
3. Improve extraction behavior with `doc-extract-learn` using a golden file
4. Re-run `doc-extract-run` on new documents using cached learning

## 1) Define the Target Schema

Edit schemas/output_schema.example.json:
- add fields you need in output
- add aliases for label/header variants
- mark required fields

## 2) Keep PDF Parsing Enabled

PDF extraction is part of the active runtime path through pdf_native. Keep these in place:
- src/doc_extract_agentic/extractors/pdf_native.py
- pypdf dependency in pyproject.toml

PDF files are routed by planner and executed by the extractor registry.

## 3) Tune Local Extraction Settings

Edit configs/default.yaml:
- pipeline.confidence_threshold
- pipeline.deterministic_fallback_enabled
- llm_extractor.max_examples
- llm_extractor.retrieval_mode (lexical, semantic, hybrid)
- local_llm.* model/runtime settings

## 4) Primary Command: Run Extraction

Use this for day-to-day extraction over folders:

doc-extract-run --input-dir ./input --output-dir ./output/run_001 --schema ./schemas/extract-sov.schema.json --config ./configs/default.yaml

Optional: include `--ground-truth` to emit discrepancy reports for scoring.

## 5) Primary Command: Learn Rules

Use this to iteratively learn rules from one source file + one golden output file:

doc-extract-learn --input-file ./input/extract-test-input.xlsx --ground-truth ./output/extract-test-output.xlsx --schema ./schemas/extract-sov.schema.json --config ./configs/default.yaml --output-dir ./output/learn_001 --max-iterations 6

Behavior:
- aligns extracted rows to golden rows
- learns transformation rules from discrepancies
- reapplies rules across iterations
- persists learned rules under `.cache/rules` for reuse

Learn output includes `learning_result.json`, `learned_rules.json`, `extracted_final.xlsx`, and `extracted_final.csv`.

## 6) Strengthen Reconciliation

If needed, customize src/doc_extract_agentic/reconciler.py for:
- per-field weighting
- cross-field validation
- source precedence between extractors

## 7) Add New Extractors

Add new extractors under src/doc_extract_agentic/extractors and register in src/doc_extract_agentic/extractors/registry.py.

For any new extractor, ensure it emits:
- field_name
- value
- confidence
- extractor
- source_ref
