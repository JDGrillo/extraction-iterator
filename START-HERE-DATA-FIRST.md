# Data-First Extraction System: Quick Start

## What You Have

A **data-first document extraction system** that:
- 📊 **Discovers** what fields are in your documents
- 🔍 **Analyzes** which extractors work best for YOUR data
- 📈 **Learns** from each extraction run
- 🔄 **Iterates** autonomously to improve
- ✅ **Measures** progress with success rates

## The 5-Minute Start

### 1. Get Your Documents Ready
```bash
mkdir -p invoices
# Add your Excel/PDF documents to ./invoices/
```

### 2. Discover What's In Them
```bash
cd /path/to/v2-self-learning
.venv\Scripts\activate  # If using venv
analyze-data --input-dir ./invoices
```

**What you see:**
```
📊 PHASE 1: DISCOVERING DATA PATTERNS...
Discovered 18 potential fields
Found 380 total values
  • Excel: 200 findings
  • PDF: 180 findings

Top discovered fields:
  • invoice_number: found 18 times (18 unique)
      Example: 'INV-2024-001'
  • vendor_name: found 19 times (5 unique)
      Example: 'ACME Corp'
  • total_amount: found 20 times (20 unique)
      Example: '$1,234.56'
```

### 3. Run Extraction
```bash
doc-extract-run \
  --input-dir ./invoices \
  --output-dir ./runs/v1 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

**Output:**
```
runs/v1/
├── extracted_output.xlsx       # Your extracted data
├── audit_summary.json          # Quality metrics
├── learning_events.jsonl       # Detailed logs
└── run_trace.json              # What ran
```

### 4. Analyze Performance
```bash
analyze-data --input-dir ./invoices --run-dir ./runs/v1
```

**What you see:**
```
EXTRACTOR PERFORMANCE SUMMARY
======================================================================

invoice_number: 90.0% ✓ GOOD
  Best: excel_native

vendor_name: 65.0% ⚠ NEEDS IMPROVEMENT
  Best: excel_native
  → Field 'vendor_name' extraction can be improved (current: 65.0%).
  → Try using pdf_native instead (success: 80.0%)

total_amount: 88.0% ⚠ NEEDS IMPROVEMENT
  Best: excel_native
  → Try using pdf_native instead (success: 92.0%)
```

### 5. Improve & Rerun
Based on analysis, update your config or schema:

**Example: Add missing aliases**
```json
{
  "name": "vendor_name",
  "aliases": [
    "vendor",
    "company",
    "company name", 
    "supplier",
    "bill from"
  ]
}
```

Then rerun:
```bash
doc-extract-run --input-dir ./invoices --output-dir ./runs/v2 ...
analyze-data --input-dir ./invoices --run-dir ./runs/v2
```

**Expected:**
```
vendor_name: 65% → 82% (+17 points!)
```

## Seven CLI Commands

```bash
# Data-First Analysis (NEW)
analyze-data --input-dir ./docs [--run-dir ./runs/v1]

# Core Extraction
doc-extract-run --input-dir ./docs --output-dir ./runs/v1 ...

# Azure CU (Optional)
setup-env                              # Configure credentials
setup-cu-analyzer --schema ...         # Generate extraction prompt
test-cu-config --config ...            # Validate setup
analyze-cu --run-dir ./runs/v1 ...     # Analyze CU performance
improve-cu --previous-run ./runs/v1 --new-run ./runs/v2  # Improve & rerun
```

## The Feedback Loop (For All Extractors)

```
1. analyze-data --input-dir ./docs
   ↓ Discover what's there
2. doc-extract-run → Extract
   ↓ Learn what works
3. analyze-data --run-dir ./runs/v1
   ↓ See performance
4. Update config/schema
   ↓ Apply improvements
5. doc-extract-run → Extract again
   ↓ Validate improvements
6. analyze-data --run-dir ./runs/v2
   ↓ Measure progress
7. Repeat 4-6 until satisfied
```

## Key Files

**Documentation:**
- [README.md](README.md) - Overview
- [docs/data-first-extraction.md](docs/data-first-extraction.md) - Complete guide (👈 START HERE)
- [DATA-FIRST-IMPLEMENTATION.md](DATA-FIRST-IMPLEMENTATION.md) - Technical details
- [QUICKSTART.md](QUICKSTART.md) - CLI reference

**Code:**
- `src/doc_extract_agentic/data_discovery.py` - Discover patterns
- `src/doc_extract_agentic/extractor_performance_analyzer.py` - Analyze performance
- `src/doc_extract_agentic/scripts/analyze_data.py` - CLI command

**Configuration:**
- `configs/default.yaml` - Extractor priorities, thresholds
- `schemas/output_schema.example.json` - Field definitions with aliases

## Real Example: Invoices

**Day 1:**
```
vendor_name: 60% (Excel found it, but incomplete)
Invoice extraction baseline done
```

**Day 2:**
```
Add aliases: "company", "supplier", "bill from"
Switch total_amount to PDF (it works better)
vendor_name: 82% (+22 points!)
total_amount: 95%
```

**Day 3:**
```
Fine-tune confidence thresholds
Add custom logic for edge cases
vendor_name: 95%
All fields > 90% success
```

## Why Data-First?

Traditional systems start with **assumptions** about what data looks like.

This system starts with **reality**—your actual documents.

- ✅ Learn from what's actually there
- ✅ Optimize for YOUR specific data patterns
- ✅ Measure improvement each iteration
- ✅ No guessing, only facts
- ✅ Non-blocking, always produces output

## Next Steps

1. **Read** [docs/data-first-extraction.md](docs/data-first-extraction.md)
2. **Run** `analyze-data --input-dir ./your-docs` to discover patterns
3. **Extract** with `doc-extract-run`
4. **Analyze** performance with `analyze-data --run-dir ./runs/v1`
5. **Improve** based on suggestions
6. **Iterate** until satisfied

That's it! The system learns from your data automatically.
