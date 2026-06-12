# Azure Content Understanding Feedback Loop & Continuous Improvement

## Overview

The system includes a **dynamic feedback loop** that:
1. Analyzes extraction discrepancies after each run
2. Identifies where CU underperforms vs other extractors
3. Suggests improvements to the CU analyzer
4. Reruns extraction with improvements
5. Tracks improvement over time

This enables **continuous learning**—the more you run, the better CU becomes.

## How It Works

### Architecture

```
Run 1: Extract with baseline CU
  ↓
Analyze: Which fields did CU miss?
  ↓
Report: High-priority gaps identified
  ↓
Improve: Update field aliases, confidence thresholds
  ↓
Run 2: Extract with improved CU
  ↓
Compare: Measure improvement
  ↓
Repeat: Iterate until satisfied
```

### Key Metrics Tracked

For each field, the system measures:
- **CU Success Rate**: How often CU found the field (vs not_found)
- **Gap Size**: Times other extractors found it but CU missed
- **Confidence When Wrong**: Is CU overconfident in bad extractions?
- **Confidence When Right**: Is CU appropriately confident in good extractions?
- **Extractor Wins**: Which extractors beat CU per field

## Usage: Three-Step Feedback Loop

### Step 1: Run Initial Extraction

```bash
doc-extract-run \
  --input-dir ./sample_inputs \
  --output-dir ./runs/baseline \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

Output files:
- `extracted_output.xlsx`: Extracted fields
- `learning_events.jsonl`: Detailed per-field results + which extractor found each
- `audit_summary.json`: Quality summary

### Step 2: Analyze CU Performance

```bash
analyze-cu \
  --run-dir ./runs/baseline \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

This generates `cu_feedback_report.json` with:

```json
{
  "analysis": {
    "high_priority_gaps": [
      {
        "field": "invoice_number",
        "cu_success_rate": 0.45,
        "gap_size": 8,
        "recommendation": "Add more aliases or adjust extraction prompt"
      }
    ],
    "cu_performing_well": ["total_amount", "invoice_date"],
    "needs_confidence_calibration": [
      {
        "field": "vendor_name",
        "confidence_when_wrong": 0.82,
        "confidence_when_right": 0.75,
        "recommendation": "Lower confidence threshold for this field"
      }
    ],
    "summary": {
      "total_fields_analyzed": 3,
      "fields_needing_improvement": 1,
      "fields_performing_well": 2
    }
  },
  "suggested_improvements": {
    "schema_alias_additions": {},
    "confidence_thresholds": {
      "invoice_number": {
        "suggested": 0.60,
        "reason": "CU unreliable for this field; lower threshold to trigger fallback"
      }
    },
    "priority_fields": [...]
  }
}
```

### Step 3: Apply Improvements & Rerun

```bash
improve-cu \
  --previous-run ./runs/baseline \
  --input-dir ./sample_inputs \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml \
  --new-run ./runs/improved_v1
```

This script:
1. Analyzes the baseline run
2. Applies suggested improvements (updated confidence thresholds, aliases)
3. Saves improved config to `runs/improved_v1/config_improved.yaml`
4. Reruns extraction with the improved config
5. Outputs results to `runs/improved_v1/`

Compare results:
```bash
# Check if CU improved
analyze-cu --run-dir ./runs/improved_v1 --schema ./schemas/output_schema.example.json --config ./configs/default.yaml
```

## Example: Improving Invoice Extraction

**Baseline Run (Run 1)**
- CU found invoice_number only 50% of the time
- Excel native extractor found it 85% of the time
- Gap: CU missed 8 invoices that Excel found

**Analysis Report**
```
HIGH-PRIORITY GAPS
1. invoice_number
   Success Rate: 50.0% (Excel found 8 more times)
   Action: Review and add missing aliases
```

**Improvements Applied**
- Analyzed discrepancies, added new aliases: ["inv #", "po #", "order number"]
- Lowered confidence threshold from 0.75 to 0.60 for invoice_number (force CU to try harder)

**Improved Run (Run 2)**
- CU now finds invoice_number 78% of the time
- Gap reduced from 8 to 2 (only 2 edge cases Excel still finds)

**Iteration**
- Continue refining aliases or switch vendor-specific documents to assistive mode

## Customizing the Feedback Loop

### 1. Add Domain-Specific Alias Suggestions

Edit `cu_feedback_loop.py` to suggest aliases based on document patterns:

```python
def suggest_aliases_from_documents(self, events: list[dict]) -> dict[str, list[str]]:
    """Analyze actual labels found in documents and suggest new aliases."""
    # Extract all unique field labels from documents
    # Cross-reference against schema aliases
    # Suggest adding new ones
```

### 2. Adjust Confidence Calibration Strategy

Modify how CU confidence thresholds are computed:

```python
def calibrate_confidence_per_field(self, events: list[dict]) -> dict[str, float]:
    """
    Per-field confidence calibration.
    
    Fields where CU is overconfident when wrong → lower threshold
    Fields where CU is underconfident when right → raise threshold
    """
```

### 3. Add A/B Testing Framework

Compare two CU configurations on the same data:

```bash
# Run with Config A
doc-extract-run ... --config config_a.yaml --output-dir runs/config_a

# Run with Config B
doc-extract-run ... --config config_b.yaml --output-dir runs/config_b

# Compare
python -c "
import pandas as pd
a = pd.read_excel('runs/config_a/extracted_output.xlsx')
b = pd.read_excel('runs/config_b/extracted_output.xlsx')
matches = (a == b).sum().sum()
print(f'Config A vs B: {matches} fields match')
"
```

## Key Files Generated

After feedback loop analysis:

- `cu_feedback_report.json`: Performance analysis + improvement suggestions
- `cu_analyzer_improved.json`: Updated extraction prompt + field aliases
- `config_improved.yaml`: Updated confidence thresholds
- New run outputs: `extracted_output.xlsx`, `learning_events.jsonl`, etc.

## Metrics & Reports

The system creates detailed reports for each run:

1. **audit_summary.json** — High-level quality (found/inferred/not_found counts)
2. **learning_events.jsonl** — Per-field extraction detail (value, confidence, extractor, source)
3. **cu_feedback_report.json** — CU-specific performance (where it wins/loses vs others)
4. **extractor_metrics.jsonl** — Per-extractor field-level performance

Use these to:
- Track improvement trends over iterations
- Identify fields that need manual review
- Decide when to add more training data or switch to different extraction approach

## Best Practices

1. **Start with fallback mode** — Let other extractors do the heavy lifting, use CU only for gaps
2. **Analyze each run** — Always run `analyze-cu` after extraction to identify improvement areas
3. **Iterate quickly** — Rerun with improved config to validate changes
4. **Track metrics over time** — Build a dashboard of success rates per field across runs
5. **Manual review for hard cases** — Some fields may need human labeling to improve further

## Cost Notes

Each rerun with improved CU config will cost the same as the initial run (one API call per page).

To minimize cost:
- Use `fallback_only` mode (default)
- Only rerun on failing documents, not full corpus
- Batch improvements (apply multiple fixes at once, rerun once)

## Example: Full Continuous Improvement Workflow

```bash
# Day 1: Baseline
doc-extract-run --input-dir ./docs --output-dir ./runs/day1 \
  --schema ./schema.json --config ./config.yaml

analyze-cu --run-dir ./runs/day1 --schema ./schema.json --config ./config.yaml

# Review feedback_report.json, identify top improvement

# Day 2: First improvement
improve-cu --previous-run ./runs/day1 --input-dir ./docs \
  --schema ./schema.json --config ./config.yaml --new-run ./runs/day2

analyze-cu --run-dir ./runs/day2 --schema ./schema.json --config ./config.yaml

# Day 3: Second improvement
improve-cu --previous-run ./runs/day2 --input-dir ./docs \
  --schema ./schema.json --config ./config.yaml --new-run ./runs/day3

# Compare results
grep "invoice_number" runs/day1/cu_feedback_report.json
grep "invoice_number" runs/day2/cu_feedback_report.json
grep "invoice_number" runs/day3/cu_feedback_report.json
```

Expected trend: Success rate increases, gap decreases with each iteration.
