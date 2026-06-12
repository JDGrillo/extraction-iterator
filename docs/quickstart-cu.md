# Quick Start: Using Azure Content Understanding

This example shows how to set up and run extraction with Azure CU enabled.

## 1. Install Optional Dependencies

```bash
pip install -e ".[azure]"
```

Or use the interactive setup:
```bash
python -m doc_extract_agentic.scripts.setup_env
```

## 2. Configure Azure Credentials

Add to `configs/default.yaml`:
```yaml
azure_content_understanding:
  enabled: true
  mode: fallback_only
  endpoint: "https://my-resource.cognitiveservices.azure.com/"
  api_key: "your-api-key-here"
  model: "prebuilt-document"
```

Or set environment variables:
```bash
set AZURE_CU_ENDPOINT=https://my-resource.cognitiveservices.azure.com/
set AZURE_CU_API_KEY=your-api-key-here
```

## 3. Initialize Schema-Based Analyzer

```bash
python -m doc_extract_agentic.scripts.setup_cu_analyzer \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml \
  --output ./cu_analyzer_config.json \
  --verbose
```

This generates an analyzer config and shows the extraction prompt.

## 4. Validate Configuration

```bash
python -m doc_extract_agentic.scripts.test_cu_config \
  --config ./configs/default.yaml
```

## 5. Run Extraction with CU Enabled

```bash
doc-extract-run \
  --input-dir ./sample_inputs \
  --output-dir ./runs/with_cu \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

Output will include:
- `extracted_output.xlsx`: Final extraction results
- `audit_summary.json`: Quality metrics
- `discrepancies.csv`: Comparison vs ground truth (if provided)
- `run_trace.json`: Which extractors were used per file
- `learning_events.jsonl`: Events for continuous learning

## 6. Evaluate Results

Compare runs with and without CU:

```bash
# Run without CU (baseline)
python -c "import yaml; yaml.safe_load(open('configs/default.yaml'))['azure_content_understanding']['enabled'] = False"

doc-extract-run \
  --input-dir ./sample_inputs \
  --output-dir ./runs/baseline \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml

# Then compare with CU results in runs/with_cu
```

## 7. Iterate

- Check `discrepancies.csv` to see where CU helped
- Add more aliases to schema for common field label variations
- Adjust confidence thresholds in `configs/default.yaml`
- For low-confidence fields, switch to `mode: assistive` to always use CU

## Cost Notes

Each page of a document costs ~$0.003 in Azure CU.

For 1,000 pages = ~$3.

Use `fallback_only` mode (default) to minimize costs—CU only runs when needed.
