# Foundry Local Extraction Autoresearch Loop - Findings and Learnings

## Overview
Autonomous extraction and self-improving rule learning for messy insurance SOV spreadsheets
using a local LLM (Phi-4) plus deterministic Excel extraction.

Primary goals observed in this repo:
- Improve schema-aligned extraction quality over iterations (`doc-extract-learn`)
- Improve production extraction coverage and row quality (`doc-extract-run`)
- Persist learned rules across runs via schema-keyed cache

## System Update (June 2026)

Recent code changes shifted the learning system toward stronger proposer/critic separation
and better cross-document iteration:

- **Proposer and critic are now intentionally different**:
  - Proposer uses higher exploration (`temperature: 0.2`) and larger rule budget
  - Critic uses stricter confidence gate, smaller rule budget, and adversarial review prompt
  - Final rule descriptions are tagged (`[proposer]` / `[critic]`) for traceability
- **Rule cache bootstrap now aggregates history**, not only latest run:
  - Rules from historical entries are merged then deduplicated by key
  - This improves transfer learning across new documents with same schema
- **Handoff signals are now persisted as iterative events**:
  - Pipeline appends model handoff events to `.cache/handoff/handoff_events.jsonl`
  - Mapping learner consumes recent handoff history hints when proposing rules
  - This creates a feedback loop from observed handoff failures into future rule proposals

### Demonstration Artifact (Proposer vs Critic Behavior)

Because live Foundry calls intermittently hang in this environment, proposer/critic behavior was
demonstrated through a controlled learning-step harness using the real `MappingLearner` flow.

Artifact:
- `output/learn_compare_mock_001/proposer_critic_demo.json`

Observed proposer/critic delta in that run:
- Proposer input: 5 candidate rules
- Critic output: 3 stricter rules
- Final retained rules: 3 (`[critic]` tagged)

This confirms the logical role split and filtering path is active end-to-end.

## Current Best Snapshot

### A) Best Schema-Match Learning Accuracy (strict, apples-to-apples)
- **15.91% (7/44 rows correct)** on Dataset A-style schema
- Seen repeatedly in `learn_001`, `learn_003`, `learn_004`, `learn_005`, `learn_006`
- Indicates extraction still misses semantic field-level alignment on many rows

### B) Best Operational Extraction Coverage (run mode)
- **80.99% fields found (392/484)** in `run_004` and `run_005`
- Tabular row quality reached **0.8099 avg fill ratio per row**
- Output stabilized at **44 rows** after SOV row gating and filtering

## Key Breakthroughs in This Repo

### 1) SOV Row Gate + Identity Gating (largest practical gain)
Implemented in Excel deterministic extraction path:
- Require positive `total_insured_value`
- Require non-empty address/city and 2-letter alpha state
- Exclude obvious summary rows (for example, total-style location rows)
- Require minimum populated schema fields + identity fields

Observed impact in run trajectory:
- Row volume reduced from noisy 90-95 rows to 44 high-signal rows
- Fill ratio improved from 0.4576-0.5455 to 0.8099
- Found-field rate improved from 45.76%-54.55% to 80.99%

### 2) Header Detection and Sheet Selection Favoring SOV-Like Data
Extractor scores sheets by SOV signal (rows with `total_insured_value`) and row count,
then applies header-mapping with fuzzy alias support.

Observed impact:
- Better sheet selection on multi-sheet files
- Better suppression of repeated header rows and note rows

### 3) Rule Caching and Bootstrap Across Matching Schemas
Rule cache stores historical learned rule sets keyed by schema fingerprint.
Runs can start with cached rules and avoid full cold-start learning.

Observed in artifacts:
- History accumulates per schema cache file
- Repeated automatic column aliases and default transforms are reused

Updated behavior:
- Cache loading now aggregates **latest + historical** rules and deduplicates them
- New documents can bootstrap from a broader memory of prior runs

## Progress Timeline (Measured Artifacts)

| Phase | Metric | Result | Key Change | Lesson |
|------|--------|--------|------------|--------|
| run_001 | Found fields | 54.55% (570/1045) | Baseline mixed extraction | Baseline had many sparse/misaligned rows |
| run_002 | Found fields | 45.76% (453/990) | Early config/sheet mismatch | Regression exposed need for stronger row filtering |
| run_003 | Found fields | 74.96% (437/583) | Improved row-quality filtering | Quality gates matter more than raw row count |
| run_004 | Found fields | 80.99% (392/484) | Stricter SOV row gate + identity checks | High-signal rows drive strong coverage lift |
| run_005 | Found fields | 80.99% (392/484) | Stabilization repeat | Improvements are reproducible |

## Learning-Loop Timeline (`doc-extract-learn`)

| Learn Run | Validation Mode | Best Accuracy | Schema Accuracy | Notes |
|----------|------------------|---------------|-----------------|-------|
| learn_001 | schema_match(default) | 0.1591 | 0.1591 | 2 iterations, no net improvement |
| learn_003 | schema_match(default) | 0.1591 | 0.1591 | 2 iterations, plateau |
| learn_004 | schema_match(default) | 0.1591 | 0.1591 | 2 iterations, plateau |
| learn_005 | schema_match(default) | 0.1591 | 0.1591 | 1 iteration, early stop |
| learn_006 | schema_match(default) | 0.1591 | 0.1591 | 1 iteration, early stop |
| learn_rowcount_002 | row_count | 0.4318 | 0.1591 | Row-count metric diverges from schema truth |
| learn_adapt_001 | row_count | 1.0000 | 0.1591 | Target reached on row count only |
| learn_adapt_002 | row_count | 1.0000 | 0.1591 | Again perfect row-count with low schema match |
| learn_dataset_b_01 | schema_match | 0.0000 | 0.0000 | 95/95 row count matched but no schema row matches |
| learn_dataset_b_02 | schema_match | 0.0000 | 0.0000 | Same pattern as learn_dataset_b_01 |

## Key Architectural Decisions (Observed)

### Source and Extraction Stack
- Ensemble strategy: `llm_native` + `excel_native` (and optional `pdf_native`)
- Deterministic extractor handles tabular normalization and row gating
- Reconciliation maps candidates into one strict target schema

### Validation Strategy
- Supports `schema_match` and `row_count` validation modes
- `schema_match` is strict quality signal
- `row_count` is useful for shape control but can overstate correctness

### Guidance Strategy
- Golden-guidance options are enabled in learning configuration
- During learning runs, aligned golden rows can influence adaptation/validation behavior
- Strongly useful for diagnosis, but should be interpreted carefully in score reporting

### Rule Governance
- Candidate rules are filtered by measured impact (`accepted` vs `no_improvement`)
- Unknown/low-impact rules are blocked from promotion
- Cache persists latest plus history per schema fingerprint

Updated behavior:
- Proposer and critic now have distinct rule-count and confidence thresholds
- Critic prompt is explicitly adversarial/reductive (prefers precision, drops uncertain rules)
- Rule provenance is now explicit in descriptions (`[proposer]`, `[critic]`)

### Handoff Governance
- Pipeline now emits richer handoff diagnostics, including:
  - `fields_safe_for_global_fill`
  - `per_field_overlap`
- Run-mode and learning-mode handoff events are appended to a shared history log
- Mapping learner reads handoff history hints to prioritize recurring conflict fields

## Structural Blockers in This Repo (Current)

### 1) Metric Mismatch: Row Count Success vs Schema Truth
- Multiple runs hit row-count accuracy of 1.0 while schema accuracy remains 0.1591
- This can trigger early stop/target reached without true field-level correctness

### 2) Field Blind Spots Persist Across Runs
Dataset B outputs show chronic zero coverage for:
- `occupancy_type`, `city`, `state`, `zip`, `equipment_value`

Dataset A outputs still show chronic gaps in:
- `contents_value` (0% fill in best run snapshots)
- `business_income_value` remains sparse

### 3) LLM Handoff Conflict Patterns
Model handoff diagnostics repeatedly show:
- Secondary model proposing generic values (for example one repeated address/zip)
- Conflicts against deterministic multi-row location values
- Limited net lift from secondary candidates

### 4) Rule Learning Stagnation on Hard Cases
Dataset B rule diagnostics show many proposed rules rejected as `no_improvement`.
This suggests current rule types/prompts are not resolving core semantic mismatches.

### 5) Runtime Reliability Blocker (Current)
- In this environment, live Foundry SDK proposer calls can hang/time out during iteration 1
- This blocks completion of some full `doc-extract-learn` experiments
- Mitigation used for validation: controlled proposer/critic harness artifact for logic verification

## Failed or Risky Experiment Patterns

1. **Row-count-first validation for success gating**
- Produced apparent 100% success while strict schema accuracy stayed low
- Good for row-shape checks, risky as primary quality target

2. **Over-reliance on auto-mapped aliases alone**
- Column alias bootstrapping helps coverage but does not solve semantic normalization
- Value-level transforms remain insufficient in hard datasets

3. **High rule count interpreted as progress**
- Some runs show larger rule sets (including repeated patterns)
- Rule count growth did not correlate with schema-match gains

## Comparison vs Colleague SKILL (What Is Similar / Different)

### Similarities
- Both systems are iterative and artifact-driven
- Both rely on defaults/aliases/normalization to gain early improvements
- Both reveal that structural issues dominate once basic mapping is solved

### Differences
- Colleague file tracks **field-level validation accuracy progression** deeply (24 PST fields) with many targeted heuristic fixes.
- This repo currently shows stronger progress in **row quality and extraction coverage** than in strict schema-match learning accuracy.
- Colleague loop demonstrates many micro-fixes improving true validation score; this repo currently demonstrates stronger extractor hardening and filtering than final schema alignment gains.
- This repo exposes explicit **row_count vs schema_match divergence** as a major methodological lesson.

## Key Lessons Learned

1. Row quality gates can produce large and repeatable practical gains.
2. Coverage improvements do not automatically translate to schema-match correctness.
3. Validation mode selection can dominate apparent progress; strict mode must remain the north-star metric.
4. Distinct proposer/critic roles improve controllability and auditability of learned rules.
5. Historical rule aggregation improves cross-document bootstrap potential.
6. Handoff event memory can turn recurring model conflicts into targeted learning hints.
7. Rule caching is useful for bootstrap speed, but semantic transform quality remains the core bottleneck.
8. Handoff diagnostics are critical to detect when secondary model candidates introduce generic-value drift.
9. Plateau detection should consider schema accuracy trend, not only row-count trend.

## Path to Higher True Accuracy (Schema-Match)

### Near-Term (Likely 3-8 point gain)
- Keep `schema_match` as primary stop metric
- Add field-specific deterministic parsers for chronic blind spots:
  - city/state/zip from multiline addresses
  - occupancy extraction from location text tails
  - equipment/contents disambiguation rules
- Expand anti-generic conflict guards in model handoff
- Add optional gated handoff fusion: only fill primary-missing fields when overlap/validator checks pass

### Medium-Term (Likely larger gains)
- Add stronger value-normalization library for insurance-specific variants
- Improve rule proposal prompts with field constraints + concrete before/after examples
- Add per-field acceptance tests before promoting learned transforms

### Longer-Term
- Introduce multi-row semantic alignment by address/location identity
- Add richer cross-document retrieval for harder value transforms
- Add benchmark dashboard splitting row-shape, field coverage, and schema-match metrics

## Suggested Reporting Standard Going Forward
Always report all three together:
1. `schema_accuracy` (primary truth metric)
2. `row_count_accuracy` (shape metric)
3. Field coverage/fill-rate profile (operational completeness)

This prevents false convergence and keeps improvements interpretable.
