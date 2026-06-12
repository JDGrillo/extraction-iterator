# Azure Content Understanding Integration Complete

## Summary

I've integrated Azure Content Understanding as a fully-optional, schema-aware extractor plugin with startup scripts and comprehensive documentation.

## New Components

### Core Modules
- **cu_client.py**: Azure Document Intelligence SDK wrapper
  - Analyzes documents using Azure's AI
  - Maps extracted fields to schema aliases
  - Returns ExtractionCandidate objects
  - Gracefully handles missing SDK

- **cu_initialization.py**: Schema-aware setup
  - Builds extraction prompts from schema
  - Generates analyzer configuration
  - Validates Azure credentials

### Extractors
- **extractors/azure_content_understanding.py**: Full implementation
  - Integrated with pipeline's planner
  - Respects config flags (enabled, mode)
  - Lazy-loads Azure client

### Initialization Scripts (CLI Commands)

1. **setup-env** (Interactive)
   - Install optional Azure dependencies
   - Configure Azure credentials (env vars or config file)
   - Guide through next steps

2. **setup-cu-analyzer**
   - Analyzes your schema
   - Creates field extraction prompt
   - Saves analyzer configuration
   - Preview extraction guidelines

3. **test-cu-config**
   - Validates endpoint and API key
   - Tests Azure SDK installation
   - Confirms connectivity (when SDK installed)

### Documentation
- **docs/azure-cu-setup.md**: Complete setup guide
  - Step-by-step Azure resource creation
  - Credential configuration
  - Cost estimation
  - Troubleshooting
  
- **docs/quickstart-cu.md**: Quick start examples
  - Installation with optional dependencies
  - Complete workflow
  - Cost notes
  
- **docs/customization-guide.md**: Enhanced with CU examples
  - How to customize field extraction
  - Custom confidence scoring
  - Integration patterns

## How It Works

### Architecture Integration

```
Pipeline (on-demand) 
  → Planner (picks extractors by file type)
    → Excel Native / PDF Native extractors
    → Reconciler (merges candidates, picks best)
    → Azure CU fallback (if enabled AND confidence low)
    → Final reconciliation
    → Auditor (always produces output + discrepancies)
    → Learner (logs events for continuous learning)
```

### Two Operating Modes

**Fallback-Only (Default)**
- Native extractors run first
- CU only invoked for low-confidence fields
- Minimizes Azure API costs
- Best for: Improving coverage on tricky documents

**Assistive Mode**
- CU runs on every document
- Provides secondary validation
- Higher cost, higher confidence
- Best for: High-value documents requiring double-check

### Configuration

```yaml
azure_content_understanding:
  enabled: false  # set to true to activate
  mode: fallback_only  # or 'assistive'
  endpoint: ""  # e.g., https://resource.cognitiveservices.azure.com/
  api_key: ""   # Get from Azure Portal
  model: "prebuilt-document"  # Azure model to use
```

## Quick Start Checklist

### Without Azure (Baseline Works)
```bash
pip install -e .
doc-extract-run \
  --input-dir ./sample_inputs \
  --output-dir ./runs/baseline \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

### With Azure CU Enabled
```bash
# 1. Interactive setup
python -m doc_extract_agentic.scripts.setup_env

# 2. Initialize analyzer from schema
python -m doc_extract_agentic.scripts.setup_cu_analyzer \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml

# 3. Test configuration
python -m doc_extract_agentic.scripts.test_cu_config \
  --config ./configs/default.yaml

# 4. Enable in config: set azure_content_understanding.enabled: true

# 5. Run extraction
doc-extract-run \
  --input-dir ./sample_inputs \
  --output-dir ./runs/with_cu \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml
```

## What's Preserved

- ✅ Non-blocking extraction (always produces output)
- ✅ Single output schema with `not_found` markers
- ✅ Audit reports and discrepancy tracking
- ✅ Continuous learning events
- ✅ Excel + PDF native extractors (unchanged)
- ✅ Full backward compatibility

## What's New

- ✅ Azure Content Understanding as optional fallback
- ✅ Schema-aware field prompt generation
- ✅ Three new CLI commands for CU management
- ✅ Comprehensive setup and validation scripts
- ✅ Optional Azure SDK dependencies
- ✅ Cost-efficient fallback-only mode by default

## Cost Estimation

**Fallback Mode** (documents with few extraction gaps):
- Example: 100 docs × 1 uncertain field × ~0.5 pages CU average = 50 pages = ~$0.15/run

**Assistive Mode** (all documents):
- Example: 100 docs × 10 pages = 1,000 pages = ~$3/run

**Recommendation**: Start with fallback mode, monitor discrepancies, switch to assistive if ROI justifies cost.

## Files Modified/Created

**New Files:**
- src/doc_extract_agentic/cu_client.py
- src/doc_extract_agentic/cu_initialization.py
- src/doc_extract_agentic/scripts/setup_env.py
- src/doc_extract_agentic/scripts/setup_cu_analyzer.py
- src/doc_extract_agentic/scripts/test_cu_config.py
- src/doc_extract_agentic/scripts/__init__.py
- docs/azure-cu-setup.md
- docs/quickstart-cu.md

**Updated Files:**
- src/doc_extract_agentic/extractors/azure_content_understanding.py (full implementation)
- src/doc_extract_agentic/config.py (added CU validation)
- configs/default.yaml (CU config with docs)
- pyproject.toml (optional Azure dependencies + CLI commands)
- docs/customization-guide.md (CU examples)
- README.md (CU quick reference)

## Next Steps

1. **Test baseline** without Azure (already works)
2. **Create Azure resource** (if using CU)
3. **Run setup-env** to configure
4. **Run setup-cu-analyzer** to generate field prompts
5. **Test with sample documents** to tune schema aliases
6. **Monitor discrepancies** to improve extraction
7. **Iterate** on extractors and reconciliation logic

## Support

See documentation:
- Full setup: [docs/azure-cu-setup.md](docs/azure-cu-setup.md)
- Quick start: [docs/quickstart-cu.md](docs/quickstart-cu.md)
- Customization: [docs/customization-guide.md](docs/customization-guide.md)
