# Quick Reference: Feedback Loop Commands

## Installation & Setup

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install package
pip install -e .

# 3. Configure Azure credentials (optional)
setup-env

# 4. Validate Azure setup (if using CU)
test-cu-config --config configs/default.yaml
```

## Three-Step Feedback Loop

### Step 1: Extract (Baseline)
```bash
doc-extract-run \
  --input-dir ./sample_inputs \
  --output-dir ./runs/v1 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

**Output**: `runs/v1/extracted_output.xlsx` + `learning_events.jsonl`

### Step 2: Analyze
```bash
analyze-cu \
  --run-dir ./runs/v1 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

**Output**: `cu_feedback_report.json` with:
- High-priority gaps (fields where CU underperforms)
- Confidence calibration issues
- Recommendations per field

### Step 3: Improve & Rerun
```bash
improve-cu \
  --previous-run ./runs/v1 \
  --input-dir ./sample_inputs \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml \
  --new-run ./runs/v2
```

**Output**: `runs/v2/` with improved extraction + `config_improved.yaml`

## Measure Progress

```bash
# Analyze improved run
analyze-cu --run-dir ./runs/v2 --schema ... --config ...

# Compare success rates between runs
# Look for: success_rate increased? Gaps reduced?
```

## CLI Commands Reference

| Command | Purpose | Key Options |
|---------|---------|------------|
| `doc-extract-run` | Extract from documents | `--input-dir`, `--output-dir`, `--schema`, `--config` |
| `setup-env` | Configure Azure credentials | (interactive) |
| `setup-cu-analyzer` | Generate extraction prompt | `--schema`, `--config` |
| `test-cu-config` | Validate Azure setup | `--config` |
| `analyze-cu` | Performance analysis | `--run-dir`, `--schema`, `--config` |
| `improve-cu` | Improve & rerun | `--previous-run`, `--input-dir`, `--new-run` |

## Configuration

**Main config file**: `configs/default.yaml`

Key sections:
```yaml
pipeline:
  confidence_threshold: 0.5
  missing_marker: "not_found"

azure_content_understanding:
  enabled: true
  endpoint: "https://..."
  api_key: "..."
  mode: "fallback_only"  # or "assistive"

field_aliases:
  vendor_name: ["company", "supplier", "bill from"]
  invoice_number: ["invoice #", "po number"]
```

## Schema

**Schema file**: `schemas/output_schema.example.json`

Structure:
```json
{
  "schema_name": "invoice",
  "fields": [
    {
      "name": "invoice_number",
      "type": "string",
      "required": true,
      "aliases": ["invoice #", "inv #", "po #"]
    }
  ]
}
```

**Key for feedback loop**: Add missing aliases after analyzing discrepancies.

## Understanding Performance Report

Example `cu_feedback_report.json`:

```json
{
  "high_priority_gaps": [
    {
      "field": "vendor_name",
      "cu_success_rate": 0.50,
      "gap_size": 4,
      "other_extractors_beat_cu": "Excel found 4 more",
      "recommendation": "Add more aliases or improve extraction prompt"
    }
  ],
  "cu_performing_well": ["invoice_date", "total_amount"],
  "needs_confidence_calibration": []
}
```

**Interpretation**:
- `cu_success_rate`: % of fields where CU found the value
- `gap_size`: How many times other extractors beat CU
- High-priority gaps: Fix these first

## Typical Iteration Pattern

1. **Run v1**: Baseline extraction
   - Result: 60-70% success on new fields
2. **Analyze v1**: Identify gaps
   - Finding: 4 invoice_number aliases missing
3. **Run v2**: Add aliases, rerun
   - Result: 85% success on invoice_number
4. **Run v3**: Fine-tune thresholds
   - Result: 90%+ success, few gaps remain
5. **Production**: Use v3 config for ongoing extraction

## Common Issues & Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Low success rate | Missing field aliases | Add aliases from `cu_feedback_report.json` |
| CU finds wrong values | Overconfidence | Lower `confidence_threshold` in config |
| CU misses obvious fields | Low confidence threshold | Raise `confidence_threshold` |
| High cost | Too many CU calls | Use `fallback_only` mode instead of `assistive` |

## Key Files for Customization

- `configs/default.yaml`: Aliases, thresholds, credentials
- `schemas/output_schema.example.json`: Field names and aliases
- `src/doc_extract_agentic/extractors/`: Add custom extractors
- `src/doc_extract_agentic/reconciler.py`: Business rules for candidate selection

## Documentation

- **Get started**: [README.md](../README.md)
- **Feedback loop workflow**: [cu-feedback-loop.md](cu-feedback-loop.md)
- **Real example**: [workflow-example.md](workflow-example.md)
- **Full guide**: [FEEDBACK-LOOP-GUIDE.md](FEEDBACK-LOOP-GUIDE.md)
- **Azure setup**: [azure-cu-setup.md](azure-cu-setup.md)
- **Customization**: [customization-guide.md](customization-guide.md)

## Next Steps

1. Create input documents in `sample_inputs/`
2. Update schema with your field names
3. Run: `doc-extract-run ...` (step 1)
4. Run: `analyze-cu ...` (step 2)
5. Run: `improve-cu ...` (step 3)
6. Measure improvement and iterate
