# Foundry Local Document Extraction

This repository runs offline extraction for messy Excel files using a local LLM (Phi-4 via Foundry Local) with deterministic fallback and learning loops.

## Primary Workflows

- `doc-extract-run`: run extraction on a folder of input files and write normalized output artifacts.
- `doc-extract-learn`: run iterative learning against a golden dataset and cache learned rules for reuse.
- Uses `llm_native` as primary strategy and `excel_native` deterministic extraction for robustness.

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

Run extraction (inference):

```powershell
doc-extract-run `
  --input-dir .\input `
  --output-dir .\output\run_001 `
  --schema .\schemas\extract-test-output.schema.json `
  --config .\configs\default.yaml `
  --ground-truth .\output\extract-test-output.xlsx
```

Run learning (with ground truth):

```powershell
doc-extract-learn `
  --input-file .\input\extract-test-input.xlsx `
  --ground-truth .\output\extract-test-output.xlsx `
  --schema .\schemas\extract-test-output.schema.json `
  --config .\configs\default.yaml `
  --output-dir .\output\learn_001 `
  --max-iterations 6
```

## Commands

- `doc-extract-run`
  - Input: directory of Excel files
  - Output: extraction artifacts (`extracted_output.xlsx`, traces, audit files)
  - Ground truth is optional; when provided, discrepancy reports are produced.
- `doc-extract-learn`
  - Input: one source Excel file + one golden Excel file
  - Output: `learning_result.json`, `learned_rules.json`, extracted final xlsx/csv
  - Supports rule caching (`.cache/rules`) to improve future runs with the same schema.

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

`doc-extract-run` output directory:

- `extracted_output.xlsx`
- `run_trace.json`
- `learning_events.jsonl`
- `audit_summary.json`
- `discrepancies.csv` (if ground truth supplied)

`doc-extract-learn` output directory:

- `learning_result.json`
- `learned_rules.json`
- `extracted_final.xlsx`
- `extracted_final.csv`

## Learning Behavior

- `doc-extract-learn` iteratively compares extracted rows to golden rows, learns transformation rules, and reapplies them.
- Learned rules are persisted in `.cache/rules` and can be reused for future documents with compatible schema.
- Final extracted rows are filtered to keep meaningful data rows (requires at least two populated fields).
- The LLM extractor can use retrieval from `examples/training_examples.jsonl` (`lexical`, `semantic`, or `hybrid`).

## Legacy / Optional Tools

- `doc-extract-auto-iterate` and `doc-extract-bootstrap-examples` remain available for advanced experimentation.
- The recommended day-to-day path is `doc-extract-run` for extraction and `doc-extract-learn` for iterative improvement.
