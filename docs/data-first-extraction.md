# Data-First Extraction

Use this starter as a data-first pipeline: observe your source documents, extract into a target schema, review quality, and iterate.

## Why Data-First

Data-first means your configuration and extractor strategy are guided by observed document patterns.

Typical loop:

```text
Discover patterns -> Run extraction -> Review artifacts -> Improve config/extractors -> Repeat
```

## Recommended Workflow

### Manual Iteration (Full Control)

1. Drop a batch of files into an input folder
2. Discover patterns in that folder
3. Run extraction into a run-specific output folder
4. Review artifacts and apply targeted improvements
5. Rerun to a new output folder and compare

### Autonomous Iteration (Recommended for Most)

Let the system iterate automatically:

```bash
doc-extract-auto-iterate \
  --input-dir ./input_data/batch_001 \
  --schema ./schemas/output_schema.example.json \
  --output-dir ./output_data/auto_iterate \
  --config ./configs/default.yaml \
  --ground-truth ./output_data/golden_labels.xlsx \
  --target-accuracy 0.90 \
  --max-iterations 10
```

The system will automatically:
- Run extraction and analyze performance
- Identify failing fields and propose aliases
- Apply approved aliases to schema
- Rerun extraction with updated schema
- Measure validation and holdout improvement and decide whether to continue
- Stop when target is reached or improvement plateaus

Output: `iteration_report.json` shows complete iteration history and final metrics.

**When to use autonomous iteration:**
- You have a clear target success rate in mind
- You want to avoid manual parameter tuning
- You have golden labels for evaluation
- You want a simple one-command workflow

**When to use manual iteration:**
- You need to understand why a field is failing
- You want to implement custom extractor logic
- You're testing new extraction strategies
- You need human review at each step

## Commands

Extraction run:

```bash
doc-extract-run \
  --input-dir ./input_data/batch_001 \
  --output-dir ./output_data/run_001 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

Bootstrap labeled examples into the training store:

```bash
doc-extract-bootstrap-examples \
  --input-dir ./input_data/batch_001 \
  --labels-xlsx ./output_data/golden_labels.xlsx \
  --schema ./schemas/output_schema.example.json \
  --output-store ./examples/training_examples.jsonl
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

### PDF Extraction

PDF parsing is part of the default extractor set and remains enabled through pdf_native.

### Local LLM Suggestions

Alias and example improvements are generated locally and promotion-gated by validation performance and field-level regression rules.
