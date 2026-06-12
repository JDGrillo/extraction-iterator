# Complete Feedback Loop Workflow Example

This example demonstrates the autonomous, self-improving extraction system with a real invoice extraction scenario.

## Scenario: Invoice Data Extraction

**Goal**: Extract invoice data from 20 mixed Excel/PDF documents

**Target Fields**:
- invoice_number
- invoice_date
- total_amount
- vendor_name

**Available Extractors**:
- Excel native (works well for structured spreadsheets)
- PDF native (works for text PDFs)
- Azure Content Understanding (fallback for tricky cases)

## Day 1: Baseline Extraction

### Step 1: Run Initial Extraction

```bash
# Create a test directory
mkdir -p sample_inputs runs

# Put 20 invoice documents in sample_inputs/ (mix of Excel and PDF)

# Run extraction with default config
doc-extract-run \
  --input-dir sample_inputs \
  --output-dir runs/day1_baseline \
  --schema schemas/output_schema.example.json \
  --config configs/default.yaml
```

Output files:
```
runs/day1_baseline/
├── extracted_output.xlsx          # Final extracted data
├── audit_summary.json             # Quality metrics
├── learning_events.jsonl          # Detailed per-field extraction history
├── run_trace.json                 # Which extractors were used per file
└── extractor_metrics.jsonl        # Per-extractor performance
```

### Step 2: Review Results

Check audit summary:
```bash
cat runs/day1_baseline/audit_summary.json
```

Example output:
```json
{
  "run_id": "abc123",
  "field_status_counts": {
    "found": 62,
    "inferred": 12,
    "not_found": 6
  },
  "total_fields": 80
}
```

Interpretation:
- 62/80 fields found with high confidence (77.5%)
- 12/80 inferred (low confidence but best effort)
- 6/80 completely missing

### Step 3: Analyze CU Performance

```bash
analyze-cu \
  --run-dir runs/day1_baseline \
  --schema schemas/output_schema.example.json \
  --config configs/default.yaml
```

Output: `cu_feedback_report.json` with detailed breakdown:

```json
{
  "analysis": {
    "high_priority_gaps": [
      {
        "field": "invoice_number",
        "cu_success_rate": 0.50,
        "gap_size": 4,
        "other_extractors_beat_cu": "Excel found 4 more",
        "recommendation": "Add more aliases or improve extraction prompt"
      },
      {
        "field": "vendor_name",
        "cu_success_rate": 0.30,
        "gap_size": 6,
        "other_extractors_beat_cu": "Excel found 6 more",
        "recommendation": "Add more aliases or improve extraction prompt"
      }
    ],
    "cu_performing_well": ["total_amount", "invoice_date"],
    "needs_confidence_calibration": [
      {
        "field": "vendor_name",
        "confidence_when_wrong": 0.82,
        "confidence_when_right": 0.70,
        "recommendation": "Lower confidence threshold for this field"
      }
    ],
    "summary": {
      "total_fields_analyzed": 4,
      "fields_needing_improvement": 2,
      "fields_performing_well": 2
    }
  }
}
```

**Key Insight**: 
- `invoice_number`: CU only found 50% (Excel found 4 more) → Missing aliases
- `vendor_name`: CU only found 30% + overconfident → Serious gap
- Good news: `total_amount` and `invoice_date` working well (>85%)

## Day 2: First Improvement Iteration

### Step 1: Understand the Gaps

Manually inspect discrepancies:
```bash
# Look at a document CU missed
# Check: what label was used for vendor name that CU didn't recognize?
# Example in document: "Company Name: ...", "Business: ...", "Bill From: ..."
```

### Step 2: Update Schema with Missing Aliases

Edit `schemas/output_schema.example.json`:

```json
{
  "name": "vendor_name",
  "type": "string",
  "aliases": [
    "vendor name",
    "vendor",
    "company name",
    "business",
    "bill from",
    "sold by",
    "supplier"
  ]
}
```

Also for `invoice_number`:
```json
{
  "name": "invoice_number",
  "type": "string",
  "aliases": [
    "invoice number",
    "invoice #",
    "inv no",
    "invoice id",
    "po number",
    "order number"
  ]
}
```

### Step 3: Apply Improvements and Rerun

```bash
improve-cu \
  --previous-run runs/day1_baseline \
  --input-dir sample_inputs \
  --schema schemas/output_schema.example.json \
  --config configs/default.yaml \
  --new-run runs/day2_v1
```

This script:
1. Analyzes baseline run performance
2. Applies confidence threshold adjustments for problematic fields
3. Runs extraction again with the improved setup
4. Saves new run to `runs/day2_v1/`

### Step 4: Compare Results

```bash
# Check improved performance
analyze-cu \
  --run-dir runs/day2_v1 \
  --schema schemas/output_schema.example.json \
  --config configs/default.yaml
```

Expected improvement:
```json
{
  "analysis": {
    "high_priority_gaps": [
      {
        "field": "invoice_number",
        "cu_success_rate": 0.85,  // ← Improved from 0.50!
        "gap_size": 1,            // ← Gap reduced from 4
      },
      {
        "field": "vendor_name",
        "cu_success_rate": 0.65,  // ← Improved from 0.30!
        "gap_size": 2,            // ← Gap reduced from 6
      }
    ],
    "cu_performing_well": ["total_amount", "invoice_date", "invoice_number"]
  }
}
```

**Result**: 
- invoice_number success rate: 50% → 85% (35 percentage point improvement!)
- vendor_name success rate: 30% → 65% (35 percentage point improvement!)

## Day 3: Second Iteration (Fine-tuning)

### Review Remaining Gaps

Analyze why vendor_name still misses 2 documents:
- Maybe they use unusual labels: "From:", "Billed By:", "Service Provider:"
- Or these are special document types (purchase orders vs invoices)

### Update Strategy

```bash
# Add more granular aliases
# OR: Switch vendor_name to "assistive" mode (always use CU, not just fallback)
```

Edit `configs/default.yaml`:
```yaml
cu_field_thresholds:
  vendor_name: 0.65  # Lower threshold, be more inclusive
  invoice_number: 0.75  # Confident enough, keep default
```

### Rerun with New Config

```bash
improve-cu \
  --previous-run runs/day2_v1 \
  --input-dir sample_inputs \
  --schema schemas/output_schema.example.json \
  --config configs/default.yaml \
  --new-run runs/day3_v2
```

### Final Results

```bash
analyze-cu --run-dir runs/day3_v2 --schema schemas/output_schema.example.json --config configs/default.yaml
```

Expected: 90%+ success rate on all fields

## Track Improvement Over Time

### Create a Trend Report

```bash
# Collect metrics from all runs
python << 'EOF'
import json
import pandas as pd

runs = ["runs/day1_baseline", "runs/day2_v1", "runs/day3_v2"]

for run_dir in runs:
    with open(f"{run_dir}/cu_feedback_report.json") as f:
        report = json.load(f)
    
    analysis = report["analysis"]
    print(f"\n{run_dir}:")
    for gap in analysis.get("high_priority_gaps", [])[:3]:
        print(f"  {gap['field']}: {gap['cu_success_rate']:.1%}")
EOF
```

Output showing improvement trend:
```
runs/day1_baseline:
  invoice_number: 50.0%
  vendor_name: 30.0%

runs/day2_v1:
  invoice_number: 85.0%
  vendor_name: 65.0%

runs/day3_v2:
  vendor_name: 90.0%
  (invoice_number removed from gaps—now performing well!)
```

## Production Handoff

Once satisfied with extraction quality:

1. **Save final schema**: `schemas/output_schema_v1_final.json` (with all the improved aliases)
2. **Save final config**: `configs/default_v1_final.yaml` (with tuned thresholds)
3. **Document improvements**: List all changes made from baseline
4. **Archive learning events**: Save all `learning_events.jsonl` files for future reference

Example production setup:
```bash
# Copy final artifacts
cp runs/day3_v2/config_improved.yaml configs/production.yaml
cp schemas/output_schema.example.json schemas/production.json

# Run production extraction
doc-extract-run \
  --input-dir ./incoming_invoices \
  --output-dir ./processed_invoices \
  --schema schemas/production.json \
  --config configs/production.yaml
```

## Key Insights from This Workflow

1. **Feedback Loop Works**: Success rates improved 50%→85%+ in 3 iterations
2. **Minimal Effort**: Only needed to add aliases, no code changes
3. **Autonomous**: System identified gaps automatically
4. **Measurable**: Each iteration shows clear improvement metrics
5. **Scalable**: Same pattern works for 20 documents or 20,000

## What Happened Under the Hood

**Day 1 Baseline**:
- Excel extractor: Found invoice_number in 8/10 Excel docs (80%)
- PDF native: Struggled with vendor names in 6/10 PDFs (40%)
- CU (fallback): Only invoked for low-confidence fields, found 50% of vendor_names

**Day 2 Improvement**:
- Added aliases that matched actual document labels
- CU now recognizes more vendor name variations
- Success rate jumped because CU candidates now matched schema aliases

**Day 3 Fine-tuning**:
- Lowered confidence thresholds for tricky fields
- CU invoked more aggressively for vendor_name
- Captured edge cases other extractors missed

## Next Steps

1. Continue iterating if needed
2. Add more document types (POs, receipts, contracts)
3. Build a validation UI for human review of edge cases
4. Track cost vs. improvement ROI
5. Consider training a custom extraction model with collected data
