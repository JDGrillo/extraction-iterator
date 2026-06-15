# Foundry Local Autonomous Extraction

This repository runs an offline extraction workflow for messy Excel files using a local LLM (Phi-4 via Foundry Local) plus deterministic evaluation gates.

## What It Does

- Uses a local LLM extractor (`llm_native`) as primary strategy for Excel files.
- Supports deterministic fallback (`excel_native`) when enabled.
- Scores every run against ground truth spreadsheets.
- Iteratively proposes alias updates using the local LLM.
- Promotes updates only when validation improves accuracy and does not regress.
- Uses split-aware scoring (train/validation/holdout) when the example store includes split metadata.
- Auto-promotes validated training examples back into the example store for continuous improvement.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[foundry]
```

Install Foundry Local CLI and warm the model:

```powershell
winget install Microsoft.FoundryLocal
setup-env --model-alias phi-4
```

Run one extraction pass:

```powershell
doc-extract-run `
  --input-dir .\input `
  --output-dir .\output\run_001 `
  --schema .\schemas\extract-test-output.schema.json `
  --config .\configs\default.yaml `
  --ground-truth .\output\extract-test-output.xlsx
```

Bootstrap golden labels into example store (recommended first step for large datasets):

```powershell
doc-extract-bootstrap-examples `
  --input-dir .\input `
  --labels-xlsx .\output\extract-test-output.xlsx `
  --schema .\schemas\extract-test-output.schema.json `
  --output-store .\examples\training_examples.jsonl `
  --validation-ratio 0.1 `
  --holdout-ratio 0.1
```

Run autonomous iteration loop:

```powershell
doc-extract-auto-iterate `
  --input-dir .\input `
  --schema .\schemas\extract-test-output.schema.json `
  --config .\configs\default.yaml `
  --output-dir .\output\autonomous_run `
  --ground-truth .\output\extract-test-output.xlsx `
  --max-iterations 6 `
  --target-accuracy 0.97
```

## Example Store

Few-shot examples are read from:

- `examples/training_examples.jsonl`

Each JSONL record should look like:

```json
{
  "source_file": "example.xlsx",
  "sheet_markdown": "Workbook: ...",
  "quality_score": 1.0,
  "split": "train",
  "output": {
    "location_name": "Main Plant",
    "city": "Denver"
  }
}
```

## Output Artifacts

Per run directory:

- `extracted_output.xlsx`
- `run_trace.json`
- `learning_events.jsonl`
- `audit_summary.json`
- `discrepancies.csv` (if ground truth supplied)
- `evaluation_report.json` (iteration loop)

Top-level iteration directory:

- `working_schema.json`
- `staging_schema.json`
- `final_schema.json`
- `iteration_report.json`

## Self-Improvement Behavior

- Use `doc-extract-bootstrap-examples` to ingest your labeled corpus into `examples/training_examples.jsonl`.
- The LLM extractor retrieves examples using `llm_extractor.retrieval_mode` (`lexical`, `semantic`, or `hybrid`).
- Autonomous iteration evaluates candidate and staged schema updates on validation split by default.
- Field-level regression gates can block promotion if configured under `auto_learning.field_promotion`.
- Holdout accuracy is tracked in `iteration_report.json` for overfitting detection.
- When alias updates are promoted, validated training rows can be auto-promoted into the example store.
