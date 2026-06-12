# Customization Guide

## 1) Define Your Output Schema

Edit `schemas/output_schema.example.json`:
- add all output fields you care about
- include aliases for each field from expected document labels
- mark optional vs required

## 2) Tune Config

Edit `configs/default.yaml`:
- `confidence_threshold`
- `field_aliases`
- Azure CU flags (`enabled`, `mode`)
- Azure CU endpoint and API key (if using)

## 3) Enable Azure Content Understanding (Optional)

If you want to use Azure CU as a fallback or assistive extractor:

1. Create an Azure Document Intelligence resource
2. Run: `python -m doc_extract_agentic.scripts.setup_cu_analyzer --schema ./schemas/output_schema.example.json --config ./configs/default.yaml`
3. Validate: `python -m doc_extract_agentic.scripts.test_cu_config --config ./configs/default.yaml`
4. Set `enabled: true` in config

See [docs/azure-cu-setup.md](azure-cu-setup.md) for detailed setup.

## 4) Leverage the Feedback Loop for Continuous Improvement

The system automatically analyzes where extractors succeed/fail and suggests improvements:

```bash
# After extraction, analyze performance
analyze-cu --run-dir ./runs/run_001 --schema ./schemas/output_schema.example.json --config ./configs/default.yaml

# Apply improvements and rerun
improve-cu --previous-run ./runs/run_001 --input-dir ./sample_inputs --schema ./schemas/output_schema.example.json --config ./configs/default.yaml --new-run ./runs/run_002

# Compare results to measure improvement
analyze-cu --run-dir ./runs/run_002 --schema ./schemas/output_schema.example.json --config ./configs/default.yaml
```

See [docs/cu-feedback-loop.md](cu-feedback-loop.md) and [docs/workflow-example.md](workflow-example.md) for detailed patterns.

## 5) Improve Extractors

Start with:
- `extractors/excel_native.py`
- `extractors/pdf_native.py`

Add domain logic for:
- multi-sheet table detection
- section-specific parsing
- regex/normalization rules for dates/currency/IDs

Example: detecting invoice sections in PDFs
```python
def extract(self, file_path, schema, config):
    candidates = []
    reader = PdfReader(str(file_path))
    
    for page in reader.pages:
        text = page.extract_text()
        # Look for "INVOICE" header
        if "INVOICE" in text.upper():
            # Parse invoice-specific fields
            ...
    return candidates
```

## 5) Customize Azure Content Understanding Extraction

Edit `src/doc_extract_agentic/cu_client.py` to:
- Add custom field matching logic (regex, fuzzy matching, semantic similarity)
- Adjust confidence scores per field type
- Handle domain-specific extraction rules

Example: custom confidence scoring
```python
def analyze_document(self, file_path, schema, field_aliases):
    candidates = []
    # ... extract key-value pairs ...
    
    for kv in result.key_value_pairs:
        key_text = kv.key.content.lower()
        value_text = kv.value.content
        
        # Higher confidence for exact matches
        if key_text in field_aliases["invoice_number"]:
            confidence = 0.95
        else:
            confidence = 0.70
            
        candidates.append(ExtractionCandidate(
            field_name="invoice_number",
            value=value_text,
            confidence=confidence,
            extractor="azure_cu",
            source_ref=f"{file_path.name}:kv_pair"
        ))
    
    return candidates
```

## 6) Strengthen Reconciliation

Update `reconciler.py` to include:
- per-field scoring weights
- cross-field validations (e.g., date must be before today)
- source precedence rules (prefer Excel over CU)

Example: cross-field validation
```python
def reconcile_candidates(candidates, schema, config):
    results = []
    
    for field in schema.fields:
        best = select_best_candidate(candidates, field.name)
        
        # Validate: if field is date, ensure it's in correct format
        if field.field_type == "date" and best:
            try:
                parse_date(best.value)
            except:
                best.confidence *= 0.5  # penalize invalid dates
        
        results.append(best)
    
    return results
```

## 7) Learning and Evaluation

Use generated artifacts:
- `learning_events.jsonl` for policy learning
- `discrepancies.csv` for error-focused retraining
- `audit_summary.json` for quality trends

Example: analyze discrepancies
```bash
# Find most common extraction errors
grep '"actual"' runs/*/discrepancies.csv | sort | uniq -c | sort -rn
```

## 8) Add More Extractors

Create a new extractor for specialized formats:

```python
# src/doc_extract_agentic/extractors/custom_format.py
from .base import BaseExtractor

class CustomFormatExtractor(BaseExtractor):
    name = "custom_format"
    
    def extract(self, file_path, schema, config):
        candidates = []
        # Your custom extraction logic
        return candidates
```

Then register it in `extractors/registry.py`:
```python
from .custom_format import CustomFormatExtractor

def build_registry():
    extractors = [
        ExcelNativeExtractor(),
        PdfNativeExtractor(),
        AzureContentUnderstandingExtractor(),
        CustomFormatExtractor(),  # Add here
    ]
    return {x.name: x for x in extractors}
```

## 9) Deploy as Service (Next)

Wrap CLI in a lightweight API (FastAPI) for on-demand runs and integrate a job queue if volume grows.
