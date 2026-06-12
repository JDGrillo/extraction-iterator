# Data-First Extraction: Discover, Learn, Improve

## The Paradigm Shift: From Schema-First to Data-Driven

**Schema-First (Traditional):**
```
Define schema → Build extractors → Run extraction → Hope it works
```

**Data-First (This System):**
```
Scan data → Discover patterns → Optimize extractors → Validate results → Iterate
```

## Why Data-First?

You said it perfectly:
> "There is a lot of good data and I want the system to be data-first, reviewing what is given and build the system around that"

**Data-First means:**
1. ✅ **System discovers what fields actually exist** in your documents (not assumptions)
2. ✅ **Learns extraction patterns** from real data (not pre-defined rules)
3. ✅ **Tries different strategies** (Excel, PDF, CU) and learns which work best
4. ✅ **Iterates autonomously** - each run feeds back to improve the next
5. ✅ **Builds configuration from data** - not the other way around

## Three-Phase Workflow

### Phase 1: Discover What's In Your Data

```bash
analyze-data --input-dir ./invoices
```

**What it does:**
- Scans all Excel files, looking for key:value patterns
- Scans all PDFs, extracting structured text
- Identifies potential fields and values
- Creates a **data profile** showing what exists

**Output:**
```json
{
  "invoice_number": {
    "count": 18,
    "unique_count": 18,
    "examples": ["INV-2024-001", "INV-2024-002"],
    "value_types": ["text"]
  },
  "vendor_name": {
    "count": 19,
    "unique_count": 5,
    "examples": ["ACME Corp", "TechFlow Inc"],
    "value_types": ["text"]
  }
}
```

**What it tells you:**
- `invoice_number` appears in 18/20 documents (90% presence)
- `vendor_name` appears in 19/20 documents but only 5 unique vendors
- Total 19 discovered fields from actual data

This **data profile** is your ground truth—it shows exactly what's in your files.

### Phase 2: Run Extraction with Learning

Now that you know what data exists, run extraction:

```bash
doc-extract-run \
  --input-dir ./invoices \
  --output-dir ./runs/v1 \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

**System logs:**
- Which extractor found each field
- Confidence for each extraction
- All candidates (before reconciliation)
- Timestamp and document reference

**Output:** `learning_events.jsonl` with complete extraction history:

```json
{
  "file": "invoice_001.xlsx",
  "extractor_plan": ["excel_native", "pdf_native"],
  "candidates": [
    {"field_name": "invoice_number", "value": "INV-2024-001", "extractor": "excel_native", "confidence": 0.95},
    {"field_name": "vendor_name", "value": "ACME Corp", "extractor": "excel_native", "confidence": 0.92}
  ],
  "results": [
    {"field_name": "invoice_number", "value": "INV-2024-001", "status": "found", "extractor": "excel_native"}
  ]
}
```

### Phase 3: Analyze & Optimize

Now analyze which extractors work best for your specific data:

```bash
analyze-data --input-dir ./invoices --run-dir ./runs/v1
```

**Output: Performance Report**

```
EXTRACTOR PERFORMANCE SUMMARY
======================================================================

invoice_number: 90.0% ✓ GOOD
  Best: excel_native
  Alternatives: pdf_native

vendor_name: 65.0% ⚠ NEEDS IMPROVEMENT
  Best: excel_native
  Alternatives: pdf_native
  → Field 'vendor_name' extraction can be improved (current: 65.0%).
    Likely issue: field labels vary or data format changes.

total_amount: 85.0% ⚠ NEEDS IMPROVEMENT
  Best: excel_native
  → Try using pdf_native instead (success: 88.0%)
```

**What this tells you:**
- `excel_native` best for invoice_number (90%)
- `pdf_native` actually better for total_amount (88% vs 85%)
- `vendor_name` needs improvement (only 65%)

## Four Ways to Improve

### 1. Add Aliases (For Better Pattern Matching)

If `vendor_name` is found 65% of the time, the system might be looking for "vendor_name" but documents use "company", "supplier", "bill from", etc.

**Before:**
```json
{
  "name": "vendor_name",
  "type": "string",
  "aliases": ["vendor name"]
}
```

**After discovering the pattern:**
```json
{
  "name": "vendor_name",
  "type": "string",
  "aliases": [
    "vendor name",
    "vendor",
    "company",
    "company name",
    "business",
    "bill from",
    "supplier",
    "sold by"
  ]
}
```

Then **rerun extraction**:
```bash
doc-extract-run --input-dir ./invoices --output-dir ./runs/v2 ...
analyze-data --input-dir ./invoices --run-dir ./runs/v2
```

**Expected result:** vendor_name success jumps from 65% → 85%+

### 2. Switch Best Extractors Per Field

Performance analysis shows `pdf_native` actually works better for some fields:

**Before:**
```yaml
extractor_priors:
  excel: 0.9
  pdf_native: 0.7
  azure_cu: 0.5
```

**After discovering patterns:**
```yaml
# For fields like total_amount, PDF extraction is actually more reliable
field_extractors:
  total_amount: ["pdf_native", "excel_native"]  # Try PDF first
  vendor_name: ["excel_native", "pdf_native"]   # Try Excel first
```

### 3. Add Custom Extraction Logic

If a field extraction is still < 70% after optimization, you might need custom logic:

```python
# src/doc_extract_agentic/extractors/custom_logic.py

class VendorNameExtractor(BaseExtractor):
    """Custom extraction for vendor_name with specific business logic."""
    
    def extract(self, file_path, schema, config):
        # Try multiple extraction strategies
        candidates = []
        
        # Strategy 1: Key-value patterns
        candidates.extend(self._extract_from_key_value(file_path))
        
        # Strategy 2: Fixed positions (if you know vendor is always in row 5)
        candidates.extend(self._extract_from_position(file_path))
        
        # Strategy 3: Domain-specific patterns (e.g., must match known vendors)
        candidates.extend(self._extract_with_domain_knowledge(file_path))
        
        return candidates
```

Register in `extractors/registry.py`:
```python
def build_registry():
    return {
        "excel_native": ExcelNativeExtractor(),
        "pdf_native": PdfNativeExtractor(),
        "vendor_custom": VendorNameExtractor(),  # NEW
        "azure_cu": AzureContentUnderstandingExtractor(),
    }
```

Then use in config:
```yaml
extractor_priors:
  vendor_custom: 0.9  # Try custom first
  excel_native: 0.8
  pdf_native: 0.7
```

### 4. Enable Azure CU for Tough Cases

If native extractors plateau, use Azure Content Understanding on just the problematic fields:

```yaml
azure_content_understanding:
  enabled: true
  mode: "field_specific"
  use_for_fields: ["vendor_name", "total_amount"]  # Only these
```

CU will analyze just those fields, without the cost of analyzing everything.

## The Feedback Loop for Excel/PDF Extraction

This works for **all extractors**, not just CU:

```
Run v1 (Excel/PDF baseline)
    ↓
Analyze: What did each extractor find?
    ↓
Discover: Which extractors work best per field?
    ↓
Improve: Update aliases, switch extractors, add custom logic
    ↓
Run v2 (with improvements)
    ↓
Analyze: Success rates improved?
    ↓
Iterate
```

## Real Example: Your Invoice System

**Day 1: Discovery & Baseline**
```bash
# Discover data
analyze-data --input-dir ./invoices
# Result: Found 18 fields, including invoice_number, vendor_name, etc.

# Extract with baseline (all native)
doc-extract-run --input-dir ./invoices --output-dir ./runs/v1 --config configs/default.yaml

# Analyze performance
analyze-data --input-dir ./invoices --run-dir ./runs/v1
# Result: 
#   invoice_number: 85% (excel_native)
#   vendor_name: 60% (excel_native)
#   total_amount: 88% (pdf_native!)
```

**Day 2: First Optimization**
```bash
# Update schema with discovered aliases
# Update config to use pdf_native for total_amount
# Rerun

doc-extract-run --input-dir ./invoices --output-dir ./runs/v2 --config configs/improved.yaml

# Analyze again
analyze-data --input-dir ./invoices --run-dir ./runs/v2
# Result:
#   invoice_number: 85% (unchanged)
#   vendor_name: 70% (+10%)
#   total_amount: 92% (+4% by using pdf_native)
```

**Day 3: Targeted Improvement**
```bash
# vendor_name still at 70%, add custom extraction
# Create vendor_custom extractor
# Use it as primary for vendor_name

doc-extract-run --input-dir ./invoices --output-dir ./runs/v3 --config configs/final.yaml

# Analyze final
analyze-data --input-dir ./invoices --run-dir ./runs/v3
# Result:
#   invoice_number: 92% (+7%)
#   vendor_name: 92% (+22%!)
#   total_amount: 95% (+3%)
```

**Improvement over 3 days:**
- 60% → 92% on vendor_name (32 percentage point gain)
- All improvements from learning what works in YOUR data
- No pre-built "vendor extraction module"
- System built from ground up on your actual files

## Key Insight: The System Becomes Domain-Specific

You don't build generic extractors. You:

1. **Discover** what YOUR data looks like
2. **Learn** what works for YOUR files
3. **Optimize** for YOUR specific patterns
4. **Iterate** until YOUR extraction is perfect

This is why data-first beats schema-first—every business has different document formats, field names, and data patterns.

## New CLI Command

```bash
# Discover what's in your input files
analyze-data --input-dir ./invoices

# Also analyze extractor performance from a previous run
analyze-data --input-dir ./invoices --run-dir ./runs/v1

# Full output
analyze-data \
  --input-dir ./invoices \
  --run-dir ./runs/v1 \
  --output-dir ./analysis_report
```

**Outputs:**
- `data_profile.json`: What fields exist in your documents
- `field_patterns.json`: How often each field appears, examples
- `extractor_performance.json`: Success rates per extractor per field
- `field_extraction_strategy.json`: Best extractors for each field
- `improvement_suggestions.json`: Specific actions to improve extraction

## Next Steps

1. **Run discovery**: `analyze-data --input-dir ./your_documents`
2. **Review what's there**: Check `data_profile.json`
3. **Extract baseline**: `doc-extract-run --input-dir ./your_documents --output-dir ./runs/v1`
4. **Analyze performance**: `analyze-data --input-dir ./your_documents --run-dir ./runs/v1`
5. **Apply improvements**: Update schema/config based on suggestions
6. **Rerun**: Extract again with improvements
7. **Measure**: Check if success rates improved
8. **Iterate**: Repeat steps 4-7 until satisfied

This is **data-driven extraction**—you let the system learn from YOUR data, not from generic assumptions.
