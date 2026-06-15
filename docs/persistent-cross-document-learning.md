# Persistent Cross-Document Learning

This autonomous learning system **accumulates knowledge across multiple documents**. After training on golden datasets, the learned rules automatically transfer to new documents with the same schema, continuously improving extraction quality.

## How It Works

### 1. **Learning Phase** (Per Golden Dataset)

When you run the autonomous learner on a golden dataset:

```bash
doc-extract-learn \
  --input-file ./data/messy_batch_1.xlsx \
  --ground-truth ./data/golden_batch_1.xlsx \
  --schema ./schemas/sov_risk.schema.json \
  --config ./configs/default.yaml \
  --output-dir ./output/batch_1 \
  --use-cached-rules
```

The system:
1. ✅ Loads any **previously learned rules** for this schema from cache
2. ✅ Bootstraps extraction with cached rules (iteration 1 starts with advantage)
3. ✅ Learns **new rules** from misalignments
4. ✅ **Saves all learned rules** to persistent cache indexed by schema
5. ✅ Outputs rules to JSON artifacts

### 2. **Knowledge Transfer** (Subsequent Documents)

When you run on a new document:

```bash
doc-extract-learn \
  --input-file ./data/new_messy_file.xlsx \
  --ground-truth ./data/new_golden.xlsx \
  --schema ./schemas/sov_risk.schema.json \
  --config ./configs/default.yaml \
  --output-dir ./output/new_batch
```

The system:
1. ✅ **Loads all cached rules** for `sov_risk.schema.json` from cache
2. ✅ Applies them as **starting point** (not iteration 1 from scratch)
3. ✅ Learns additional rules for this document's unique patterns
4. ✅ Merges new rules with cached rules
5. ✅ **Updates cache** with combined rule set

**Result**: Better starting accuracy → Faster convergence → Fewer iterations needed

## Cache Structure

Rules are stored in `.cache/rules/` indexed by **schema fingerprint**:

```
.cache/rules/
├── rules_location_name_occupancy_type_street_address_text_city_state_zip_building_value_contents_value_equipment_value_business_income_value_total_insured_value.json
└── rules_other_schema.json
```

Each cache file maintains:
- **Latest** rules (used for new documents)
- **History** of all learned rule sets (for traceability)
- **Metadata** (source golden files, iteration counts)

## Example: Multi-Batch Learning

### Batch 1: Initial Learning
```bash
# First golden dataset (extract-test-output.xlsx)
doc-extract-learn \
  --input-file ./input/extract-test-input.xlsx \
  --ground-truth ./output/extract-test-output.xlsx \
  --schema ./schemas/extract-test-output.schema.json \
  --config ./configs/default.yaml \
  --output-dir ./output/batch_1 \
  --max-iterations 6
```

**Iteration History**:
- Iter 1: 20% accuracy (no cached rules exist yet)
- Iter 2: 45% accuracy (learns column aliases)
- Iter 3: 70% accuracy (learns value transforms)
- Iter 4: 92% accuracy (learns row skip rules)
- **Cache saved with 4 rules**

### Batch 2: Transfer Learning
```bash
# Different messy data, same schema
doc-extract-learn \
  --input-file ./input/batch_2_messy.xlsx \
  --ground-truth ./output/batch_2_golden.xlsx \
  --schema ./schemas/extract-test-output.schema.json \
  --config ./configs/default.yaml \
  --output-dir ./output/batch_2 \
  --max-iterations 6 \
  --use-cached-rules  # Default is true
```

**Iteration History**:
- Iter 1: 60% accuracy ✨ **Boosted by 4 cached rules!**
- Iter 2: 75% accuracy (learns 2 new rules specific to batch_2)
- Iter 3: 95% accuracy (target reached)
- **Cache updated with 6 total rules (4 old + 2 new)**

### Batch 3: Further Accumulation
```bash
doc-extract-learn \
  --input-file ./input/batch_3_messy.xlsx \
  --ground-truth ./output/batch_3_golden.xlsx \
  --schema ./schemas/extract-test-output.schema.json \
  --config ./configs/default.yaml \
  --output-dir ./output/batch_3 \
  --max-iterations 6
```

**Iteration History**:
- Iter 1: 75% accuracy ✨ **Boosted by 6 cached rules!**
- Iter 2: 90% accuracy
- **Cache updated with 7 total rules (6 old + 1 new)**

**Trend**: Each batch starts with higher baseline, learns fewer new rules, converges faster.

## CLI Options

### Disable Caching
If you want to learn fresh (e.g., testing a hypothesis):

```bash
doc-extract-learn \
  --input-file ./data/messy.xlsx \
  --ground-truth ./data/golden.xlsx \
  --schema ./schemas/my_schema.json \
  --skip-cached-rules  # Don't load previous rules
```

The system will still **save new rules** to cache.

### Custom Cache Directory
```bash
doc-extract-learn \
  --input-file ./data/messy.xlsx \
  --ground-truth ./data/golden.xlsx \
  --schema ./schemas/my_schema.json \
  --rules-cache-dir ./my/custom/cache
```

## Inspecting Cached Rules

### View Cache Statistics
```python
from pathlib import Path
from src.doc_extract_agentic.rule_cache import RuleCache

cache = RuleCache(Path(".cache/rules"))
stats = cache.get_cache_stats()
print(f"Total schemas: {stats['total_schemas']}")
print(f"Total rules cached: {stats['total_rules']}")
for schema_fp, info in stats['schemas'].items():
    print(f"  {schema_fp}: {info['rule_count']} rules ({info['history_entries']} versions)")
```

### Load Cached Rules for a Schema
```python
from pathlib import Path
from src.doc_extract_agentic.rule_cache import RuleCache

cache = RuleCache(Path(".cache/rules"))
schema_fields = ["Location Name", "Occupancy Type", "Street Address", ...]
cached = cache.load_rules(schema_fields)
print(f"Loaded {len(cached['rules'])} cached rules")
for rule in cached['rules']:
    print(f"  - {rule['field_name']}: {rule['description']}")
```

## Understanding Rule Deduplication

When rules are cached, duplicates are automatically removed:

```python
rules = [
    {"field_name": "state", "rule_type": "value_transform", "description": "uppercase", "confidence": 0.8},
    {"field_name": "state", "rule_type": "value_transform", "description": "uppercase", "confidence": 0.9},  # Higher confidence
]
deduped = cache.deduplicate_rules(rules)
# Result: Only the 0.9 confidence rule is kept
```

This prevents rule bloat and ensures the highest-confidence version of each rule is used.

## Merging Rule Sets

When a new run learns rules:

```python
merged = cache.merge_rule_sets(
    cached_rules=[...],        # From previous runs
    new_rules=[...]            # Just learned
)
# Result: Newest rules override older ones for same (field_name, rule_type)
```

## Practical Workflow

### For Production Use
1. **Start**: Run on first golden dataset with `--use-cached-rules` (no existing cache, so fresh start)
2. **Accumulate**: Run on additional golden datasets with `--use-cached-rules` enabled
3. **Apply**: Use accumulated rules for new documents with the same schema
4. **Monitor**: Check accuracy trends to verify continuous improvement

### Example Production Scenario
```bash
# Month 1: Learn from 5 golden datasets
for batch in 1 2 3 4 5; do
  doc-extract-learn \
    --input-file ./data/batch_$batch/messy.xlsx \
    --ground-truth ./data/batch_$batch/golden.xlsx \
    --schema ./schemas/sov_risk.schema.json \
    --output-dir ./output/batch_$batch
done

# Month 2: Extract new documents with accumulated knowledge
doc-extract-batch-apply \
  --input-dir ./data/new_documents \
  --schema ./schemas/sov_risk.schema.json \
  --rules-cache-dir ./.cache/rules  # Uses rules from 5 batches!
  --output-dir ./output/new_extractions
```

## Key Benefits

| Aspect | Without Caching | With Caching |
|--------|-----------------|--------------|
| **Batch 1** | Learns from scratch, 5-6 iterations | Same, fresh start |
| **Batch 2** | Learns from scratch again, 5-6 iterations | Starts with Batch 1 rules, 2-3 iterations |
| **Batch 3** | Learns from scratch again | Starts with Batch 1+2 rules, 1-2 iterations |
| **Total work** | 15-18 iterations | 8-11 iterations (45% reduction!) |
| **New documents** | Accuracy = 0% on iteration 1 | Accuracy = 60%+ on iteration 1 (bootstrap) |

## Troubleshooting

### "Rules aren't being loaded"
Check that:
1. Schema field names match exactly (fingerprint must be identical)
2. Cache file exists: `ls .cache/rules/rules_*.json`
3. Not using `--skip-cached-rules` flag

### "Cache seems stale"
The cache is versioned by schema. If you change the schema:
```bash
# Old schema (e.g., 10 fields)
# Generates cache: rules_field1_field2_..._field10.json

# New schema (e.g., 12 fields)  
# Generates NEW cache: rules_field1_field2_..._field10_field11_field12.json
```
The system treats them as separate schemas (correct behavior).

### "Want to reset cache for a schema"
```bash
rm .cache/rules/rules_SCHEMA_FINGERPRINT.json
```

Then run again with `--use-cached-rules` (will start fresh, but save to cache).
