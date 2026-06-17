# Product Requirements Document

## Product

Foundry Local Document Extraction is an offline utility for extracting structured rows from messy spreadsheets using a hybrid approach: deterministic extraction plus local SLM reasoning.

## Problem Statement

Spreadsheet layouts vary by source, and static mapping logic breaks when headers, row structures, or value formats drift. Manual correction is slow and does not scale across repeated document batches.

## Objectives

1. Provide reliable day-to-day extraction with a strict target schema.
2. Improve extraction quality over time through iterative learning.
3. Reuse learned rules across future documents with the same schema.
4. Keep execution local-first for privacy and reproducibility.

## Primary Workflows

### Run Workflow

`doc-extract-run` processes a folder of files and emits normalized outputs plus quality artifacts.

Core behavior:
- Build a per-file extraction plan.
- Run deterministic and SLM extractors.
- Reconcile candidates into one schema row model.
- Emit run artifacts and handoff telemetry.

### Learn Workflow

`doc-extract-learn` compares extracted rows to a golden file, proposes rule improvements, critiques them, and applies accepted rules iteratively.

Core behavior:
- Normalize and align extracted vs golden rows.
- Generate candidate rules with proposer profile.
- Filter rules with critic profile and governance thresholds.
- Reapply accepted rules and measure accuracy trends.
- Persist learned rules and learning history.

## Improvement Over Time

The product improves at two levels:

1. Within-run improvement:
- Each iteration learns from current discrepancies.
- Rules that do not improve quality are rejected.

2. Cross-document improvement:
- Rules are cached by schema fingerprint in `.cache/rules`.
- New documents with matching schema bootstrap from prior learning.
- Handoff events are persisted to guide future conflict handling.

## Dataset Requirements For Better Future Runs

High-quality golden datasets are the main quality multiplier.

Preferred characteristics:
- Accurate row-level ground truth.
- Stable schema column naming.
- Coverage of edge patterns (totals, merged headers, sparse rows, unusual value formats).
- Representative variety across vendors/templates.

Expected impact:
- Higher starting accuracy on future documents.
- Faster convergence (fewer learn iterations).
- Fewer brittle one-off rules and better transfer quality.

## Success Metrics

Track all three together:
- `schema_accuracy` (primary quality metric)
- `row_count_accuracy` (shape/volume metric)
- Fill-rate and field coverage (operational completeness)

## Non-Goals

- Fully replacing schema governance with free-form extraction.
- Treating row-count alone as a success condition.
- Depending on cloud-only inference as the default path.

## Canonical Documentation Map

- Product and requirements: `docs/PRD.md`
- System behavior and flow diagrams: `docs/architecture.md`
- Operator tuning and extension points: `docs/customization-guide.md`
- Empirical run/learn findings: `docs/SKILL_repo_findings.md`