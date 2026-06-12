# Azure Content Understanding Setup & Initialization

## Overview

Azure Content Understanding (Document Intelligence) is an optional plugin that enhances extraction for complex documents. It uses AI to:
- Extract key-value pairs from unstructured documents
- Parse tables and structured regions
- Understand semantic field relationships

This baseline implements CU as a **fallback extractor** by default—it only runs when deterministic extractors (Excel/PDF native) find low-confidence fields.

## Prerequisites

1. **Azure Subscription** with Document Intelligence resource.
2. **Python SDK** (optional, but needed if you want to use CU):
   ```bash
   pip install azure-ai-documentintelligence
   ```

## Setup Steps

### Step 1: Create Azure Document Intelligence Resource

1. Go to [Azure Portal](https://portal.azure.com)
2. Create a new "Document Intelligence" resource
3. Choose region and pricing tier (Standard S0 is recommended for exploration)
4. After creation, note:
   - **Endpoint URL**: e.g., `https://my-resource.cognitiveservices.azure.com/`
   - **API Key**: Found under "Keys and Endpoint"

### Step 2: Configure Credentials

Add your credentials to `configs/default.yaml`:

```yaml
azure_content_understanding:
  enabled: true
  mode: fallback_only  # or 'assistive' to always run CU
  endpoint: "https://my-resource.cognitiveservices.azure.com/"
  api_key: "your-api-key-here"
  model: "prebuilt-document"
```

Or use **environment variables** (recommended for security):

```bash
set AZURE_CU_ENDPOINT=https://my-resource.cognitiveservices.azure.com/
set AZURE_CU_API_KEY=your-api-key-here
```

Then leave endpoint/api_key empty in config; the client will read from env vars.

### Step 3: Initialize Schema-Based Analyzer

Run the setup script to analyze your schema and create an extraction prompt:

```bash
python -m doc_extract_agentic.scripts.setup_cu_analyzer \
  --schema ./schemas/output_schema.example.json \
  --config ./configs/default.yaml \
  --output ./cu_analyzer_config.json \
  --verbose
```

This generates:
- `cu_analyzer_config.json`: Configuration including field aliases and extraction prompt
- Console output: Preview of the extraction prompt that guides CU

Example output:
```
Extract the following fields from the document:
- document_id: document id, reference number, id (optional)
- document_date: date, issued date, created date (optional)
- total_value: total, amount, final value (optional)
```

### Step 4: Validate Configuration

Test your Azure CU setup:

```bash
python -m doc_extract_agentic.scripts.test_cu_config \
  --config ./configs/default.yaml
```

This checks:
- Endpoint and API key are configured
- Azure SDK is installed
- Credentials are valid (optional, if SDK is installed)
- Configuration summary

## CU Extraction Modes

### Fallback-Only (Default)

CU only runs when:
- Deterministic extractors (native Excel/PDF) find fields with confidence < threshold
- You want to recover missing or uncertain fields

**Best for**: Reducing manual review, improving coverage on tricky documents

**Cost**: Lower—CU runs only when needed

### Assistive Mode

CU runs on every document, even if deterministic extractors succeed.

**Best for**: Getting secondary candidates to validate against primary extraction

**Cost**: Higher—every document incurs CU API calls

Enable by setting `mode: assistive` in config.

## Field Mapping

CU extracts key-value pairs and tables, then maps them to your schema using **field aliases**. 

For example, if your schema has:
```json
{
  "name": "document_id",
  "aliases": ["document id", "reference number", "id"]
}
```

CU will look for any of those aliases in the extracted key text and map matches to `document_id`.

## Cost Estimation

Azure Document Intelligence is charged per page analyzed:
- **Standard tier**: ~$3 per 1,000 pages
- Documents up to 2,000 pages per call

**Cost = (document page count) × (pages per document) × (0.003 per page)**

For example:
- 100 documents × 10 pages each = 1,000 pages = ~$3

## Troubleshooting

### "Azure SDK not installed"
Install the SDK:
```bash
pip install azure-ai-documentintelligence
```

### "Invalid credentials"
- Verify endpoint URL format (should end with `/`)
- Check API key in Azure Portal
- Ensure resource is in the same region as configured

### "Endpoint not configured"
Set `enabled: true` and populate `endpoint` and `api_key` in config.

### Low extraction quality
- Check that your schema aliases match document labels (run setup script to preview)
- Add more aliases to schema for common variations
- Consider switching to `assistive` mode for secondary validation

## Advanced: Custom Field Extraction

To customize how CU maps fields:

1. Edit `src/doc_extract_agentic/cu_client.py`, method `analyze_document()`
2. Add custom field matching logic (regex, semantic similarity, etc.)
3. Adjust confidence scores based on field type

## Next Steps

1. After setup, run a test extraction:
   ```bash
   doc-extract-run \
     --input-dir ./input_data/batch_001 \
     --output-dir ./output_data/run_cu_001 \
     --schema ./schemas/output_schema.example.json \
     --config ./configs/default.yaml
   ```

2. Check `discrepancies.csv` to see where CU helped vs. native extractors.

3. Iterate on schema aliases based on discrepancies.
