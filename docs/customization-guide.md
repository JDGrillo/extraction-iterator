# Customization Guide

## 0) Drop-In Usage Pattern

This repository is designed for folder-based processing with local self-improvement:

1. Place source files in an input folder (nested folders supported)
2. Run extraction to a new output folder
3. Evaluate against golden labels
4. Iterate with the autonomous loop

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
- auto_learning.* gates for promotion safety

## 4) Bootstrap Golden Data for Learning

Use the bootstrap command to ingest labeled examples into the example store:

doc-extract-bootstrap-examples --input-dir ./input --labels-xlsx ./output/extract-test-output.xlsx --schema ./schemas/extract-test-output.schema.json --output-store ./examples/training_examples.jsonl --validation-ratio 0.1 --holdout-ratio 0.1

This creates split-aware examples for train, validation, and holdout evaluation.

## 5) Run Autonomous Improvement

Run split-aware autonomous iteration:

doc-extract-auto-iterate --input-dir ./input --schema ./schemas/extract-test-output.schema.json --config ./configs/default.yaml --output-dir ./output/auto_iterate --ground-truth ./output/extract-test-output.xlsx --max-iterations 6 --target-accuracy 0.97

Behavior:
- proposes alias updates from failures
- validates updates against validation split
- blocks promotion on configured field regressions
- tracks holdout accuracy
- auto-promotes validated train rows to example store

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
