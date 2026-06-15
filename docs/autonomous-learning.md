# Autonomous Learning Extraction System

This system iteratively discovers and applies transformation rules to improve extraction accuracy **without human intervention**. The LLM learns from mismatches between extracted and golden data, then applies learned rules to subsequent extractions.

## Architecture

### Four-Stage Learning Loop

1. **Table Normalization (Extract)**
   - Extract raw dataframe from messy Excel with structure preserved
   - Detect header rows, preserve row/column positions
   - Module: `table_normalizer.py`

2. **Row Alignment (Analyze)**
   - Match extracted rows to golden rows using similarity scoring
   - Classify discrepancies by type (missing, column_shift, value_mismatch, etc.)
   - Module: `row_aligner.py`

3. **Rule Discovery (Learn)**
   - Summarize misalignment patterns
   - Prompt LLM to propose transformation rules from discrepancies
   - Rules include: column_alias, value_transform, row_skip, header_row
   - Module: `mapping_learner.py`

4. **Rule Application (Transform & Repeat)**
   - Apply learned rules to extracted data
   - Re-extract with transformed schema
   - Measure improvement
   - If improvement > threshold and accuracy < target: go to step 1
   - Module: `rule_applier.py`

### Orchestrator

`autonomous_learner.py` ties all stages together in a loop that:
- Runs: extract → align → learn → apply → measure
- Stops when: target accuracy reached OR improvement plateaus OR max iterations exceeded
- Returns: final accuracy, iteration history, all learned rules

## Key Differences from Old System

| Aspect | Old (Proposal-Based) | New (Learning-Based) |
|--------|---------------------|---------------------|
| **LLM Role** | Proposes alias suggestions | Learns transformation rules |
| **Gating** | Human review of proposals | Automatic application of rules |
| **Loop** | Extract → propose → gate → apply | Extract → align → learn → apply |
| **Output** | Static schema improvements | Dynamic rule set |
| **Scalability** | Limited by proposal quality | Improves with each iteration |
| **Autonomy** | Semi-autonomous (proposals still gated) | Fully autonomous |

## Usage

### Basic Usage

```bash
doc-extract-learn \
  --input-file ./input/extract-test-input.xlsx \
  --ground-truth ./output/extract-test-output.xlsx \
  --schema ./schemas/extract-test-output.schema.json \
  --config ./configs/default.yaml \
  --output-dir ./output/learn \
  --target-accuracy 0.95 \
  --max-iterations 6
```

### Parameters

- `--input-file`: Source Excel file (messy data)
- `--ground-truth`: Golden/reference data (correct answers)
- `--schema`: Target schema definition
- `--config`: Configuration with LLM settings
- `--output-dir`: Where to save artifacts
- `--target-accuracy`: Stop when accuracy reaches this (0.0-1.0)
- `--max-iterations`: Maximum iterations to try
- `--min-improvement-delta`: Minimum accuracy gain per iteration to continue (default 0.01)

### Output Artifacts

- `learning_result.json`: Complete iteration history and metrics
- `learned_rules.json`: Final rule set that can be reused

## Example Flow

### Iteration 1
- Extract messy data → 10 rows
- Compare to golden data → 2 rows correct (20% accuracy)
- Identify problems: location_name mapped wrong column, occupancy_type missing
- LLM learns: "location_name → use col_2", "occupancy_type → extract from col_3 header"
- Apply rules

### Iteration 2
- Re-extract with learned rules → 7 rows correct (70% accuracy)
- New problems: state/zip columns swapped
- LLM learns: "zip and state are reversed in header"
- Apply rules

### Iteration 3
- Re-extract with all rules → 9 rows correct (90% accuracy)
- Remaining issues: value normalization (e.g., "NY" vs "new york")
- LLM learns: "state → convert to abbreviation"
- Apply rules

### Iteration 4
- Re-extract with all rules → 10/10 rows correct (100% accuracy)
- **Target reached → Stop**

## Rule Types

### column_alias
Maps a source column to a target schema field.
```json
{
  "field_name": "location_name",
  "rule_type": "column_alias",
  "config": {"source_column": "col_2"}
}
```

### value_transform
Transforms extracted values (normalize, extract, reformat).
```json
{
  "field_name": "state",
  "rule_type": "value_transform",
  "config": {"type": "uppercase"}
}
```

Options: `uppercase`, `lowercase`, `strip`, `extract_number`, `extract_alpha`, `replace`, `split_first`

### row_skip
Marks rows to skip (empty rows, subtotals, etc.).
```json
{
  "field_name": "",
  "rule_type": "row_skip",
  "config": {"condition": "all_empty"}
}
```

### header_row
Specifies which row contains headers.
```json
{
  "field_name": "",
  "rule_type": "header_row",
  "config": {"row_index": 1}
}
```

## Configuration

Relevant config settings in `configs/default.yaml`:

```yaml
local_llm:
  enabled: true
  provider: "foundry_local_sdk"
  model: "phi-4-mini"
  timeout_seconds: 600          # Increase for complex learning prompts
  app_name: "foundry"
  auto_download_model: true

pipeline:
  confidence_threshold: 0.75
```

## Monitoring & Debugging

### During Learning

The system prints iteration-by-iteration progress:

```
=== Iteration 1/6 ===
Iteration 1: 20.00% (2/10 rows correct)
Learning rules from 8 misaligned rows
Learned 3 rules in iteration 1
Loaded 3 total rules for next iteration
```

### Artifacts

Each run generates:
- `learning_result.json`: Metrics per iteration
- `learned_rules.json`: All discovered rules

### Inspect Rules

```python
import json
with open("output/learn/learned_rules.json") as f:
    rules = json.load(f)
    for rule in rules["rules"]:
        print(f"{rule['field_name']}: {rule['rule_type']} - {rule['description']}")
```

## Convergence Criteria

The loop stops when ANY of these is true:

1. **Target Reached**: `accuracy >= target_accuracy` (default 0.95)
2. **Improvement Plateaus**: `improvement < min_improvement_delta` (default 0.01) for 2+ consecutive iterations
3. **Max Iterations**: Reached `max_iterations` (default 6)
4. **No Rules Learned**: LLM couldn't propose any new rules

## Tips for Best Results

1. **Provide Quality Golden Data**
   - Ground truth must be accurate for learning
   - Ensure schema fields match golden data columns

2. **Start Conservative**
   - Set `target_accuracy` to 0.90 or 0.95, not 1.0
   - Set `min_improvement_delta` to 0.01 (1%)

3. **Use Appropriate Model**
   - phi-4-mini works well for this task
   - Larger timeouts help complex learning: `timeout_seconds: 600`

4. **Inspect Failed Iterations**
   - Check `learning_result.json` for accuracy trend
   - If accuracy flat after iteration 2, learning may be stuck

5. **Reuse Learned Rules**
   - Save `learned_rules.json` for future runs
   - Can be integrated into schema/config for cold starts
