# Agentic Document Extraction Starter (Python)

A generic starter template for building data extraction workflows over Excel and PDF documents.

## What This Starter Provides

- A modular extraction pipeline with pluggable extractors
- A reconciliation step to map candidates into one output schema
- Audit artifacts for quality checks and troubleshooting
- Optional add-ons for Azure Content Understanding and LLM-assisted suggestions

## Core Workflow

1. Define your output schema in [schemas/output_schema.example.json](schemas/output_schema.example.json)
2. Configure behavior in [configs/default.yaml](configs/default.yaml)
3. Run extraction over an input folder
4. Review output and audit artifacts
5. Iterate on aliases, extractor logic, and thresholds

## Quick Start

Drop your documents into an input folder and point the pipeline at an output folder.

Example folder layout:

```text
./input_data/
  batch_001/
    file1.pdf
    file2.xlsx
./output_data/
```

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .

doc-extract-run \
  --input-dir ./input_data/batch_001 \
  --output-dir ./output_data/run_001 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

Optional data profiling and strategy analysis:

```bash
analyze-data --input-dir ./input_data/batch_001 --run-dir ./output_data/run_001
```

Run iterative passes by writing each pass to a new output folder:

```bash
doc-extract-run --input-dir ./input_data/batch_001 --output-dir ./output_data/run_002 --schema ./schemas/output_schema.example.json --config ./configs/default.yaml
analyze-data --input-dir ./input_data/batch_001 --run-dir ./output_data/run_002
```

## CLI Commands

| Command | Purpose |
|---------|---------|
| `doc-extract-run` | Run extraction pipeline |
| `analyze-data` | Analyze data patterns and extractor performance |
| `setup-cu-analyzer` | Generate Azure CU analyzer config |
| `test-cu-config` | Validate Azure CU configuration |
| `analyze-cu` | Analyze CU-specific performance |
| `improve-cu` | Apply CU-focused improvement cycle |

## Optional Components

### Azure Content Understanding

Optional and disabled by default. Enable under `azure_content_understanding` in [configs/default.yaml](configs/default.yaml).

### LLM Improvement Suggestions

Optional and disabled by default. Enable under `llm_improvement` in [configs/default.yaml](configs/default.yaml).

If unavailable or misconfigured, the pipeline continues with deterministic behavior.

## Output Artifacts

Typical run outputs in your run directory:

- `extracted_output.xlsx`
- `audit_summary.json`
- `run_trace.json`
- `learning_events.jsonl`
- `discrepancies.csv` (when ground truth is provided)

These are written to whatever folder you pass with `--output-dir`, so you can keep one folder per run/batch.

## Documentation

- [docs/architecture.md](docs/architecture.md)
- [docs/customization-guide.md](docs/customization-guide.md)
- [docs/data-first-extraction.md](docs/data-first-extraction.md)
- [docs/azure-cu-setup.md](docs/azure-cu-setup.md)
