# Foundry Local Document Extraction

This repository runs offline extraction for messy Excel files using a local LLM (Phi-4-mini via Foundry Local) with deterministic fallback and learning loops.

## Documentation Map

Documentation is consolidated into the core set below to keep requirements, architecture, and operator guidance in sync.

- Product requirements and scope: `docs/PRD.md`
- Architecture and run/learn diagrams: `docs/architecture.md`
- Tuning and extension points: `docs/customization-guide.md`
- Empirical findings and lessons: `docs/SKILL_repo_findings.md`

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

Warm the model with the GA Python package path:

```powershell
setup-env --model-alias phi-4-mini
```

If you use the OpenAI-compatible REST endpoint (`local_llm.provider: openai_compatible`),
install/start the Foundry Local CLI separately. For the default SDK mode
(`local_llm.provider: foundry_local_sdk`), CLI setup is not required by this project.

Run extraction (inference):

```powershell
doc-extract-run `
  --input-dir .\input `
  --output-dir .\output\run_001 `
  --schema .\schemas\extract-sov.schema.json `
  --config .\configs\default.yaml `
  --ground-truth .\output\extract-test-output.xlsx
```

Run learning (with ground truth):

```powershell
doc-extract-learn `
  --input-file .\input\extract-test-input.xlsx `
  --ground-truth .\output\extract-test-output.xlsx `
  --schema .\schemas\extract-sov.schema.json `
  --config .\configs\default.yaml `
  --output-dir .\output\learn_001 `
  --max-iterations 6
```

Run batch learning across `source` + `target` directories (sequential):

```powershell
doc-extract-learn learn-batch `
  --source-dir .\source `
  --target-dir .\target `
  --schema .\schemas\extract-sov.schema.json `
  --config .\configs\default.yaml `
  --output-dir .\output\learn_batch `
  --max-iterations 6
```

For similarly named files/directories, tune matching behavior:

```powershell
doc-extract-learn learn-batch `
  --source-dir .\source `
  --target-dir .\target `
  --min-match-score 180 `
  --allow-source-reuse
```

- `--min-match-score`: raises the confidence threshold before a source/target pair is accepted.
- `--allow-source-reuse`: allows one source file to be paired with multiple targets.

## Commands

- `doc-extract-run`
  - Input: directory of Excel files
  - Output: extraction artifacts (`extracted_output.xlsx`, traces, audit files)
  - Ground truth is optional; when provided, discrepancy reports are produced.
- `doc-extract-learn`
  - Input: one source Excel file + one golden Excel file
  - Output: `learning_result.json`, `learned_rules.json`, extracted final xlsx/csv
  - Supports rule caching (`.cache/rules`) to improve future runs with the same schema.
  - Includes `learn-batch` subcommand for sequential training over `source`/`target` folders.

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
