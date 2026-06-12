# Data-First Extraction

Use this starter as a data-first pipeline: observe your source documents, extract into a target schema, review quality, and iterate.

## Why Data-First

Data-first means your configuration and extractor strategy are guided by observed document patterns.

Typical loop:

```text
Discover patterns -> Run extraction -> Review artifacts -> Improve config/extractors -> Repeat
```

## Recommended Workflow

1. Drop a batch of files into an input folder
2. Discover patterns in that folder
3. Run extraction into a run-specific output folder
4. Review artifacts and apply targeted improvements
5. Rerun to a new output folder and compare

## Commands

Pattern discovery and strategy analysis:

```bash
analyze-data --input-dir ./input_data/batch_001
analyze-data --input-dir ./input_data/batch_001 --run-dir ./output_data/run_001
```

Extraction run:

```bash
doc-extract-run \
  --input-dir ./input_data/batch_001 \
  --output-dir ./output_data/run_001 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

## What to Improve Between Runs

- Field aliases in the schema
- Extractor priorities and thresholds in config
- Extractor logic for difficult fields
- Reconciliation behavior for conflicting candidates

## Useful Artifacts

- `extracted_output.xlsx`
- `audit_summary.json`
- `discrepancies.csv` (if ground truth exists)
- `run_trace.json`
- `learning_events.jsonl`

## Optional Components

### Azure Content Understanding

Enable `azure_content_understanding` in [configs/default.yaml](../configs/default.yaml) to add CU as an optional extractor.

### LLM Improvement Suggestions

Enable `llm_improvement` in [configs/default.yaml](../configs/default.yaml) for optional LLM-generated tuning suggestions.

If unavailable, deterministic suggestions remain in place.
