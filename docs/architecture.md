# Architecture Details

## Design Principles

1. Always emit output.
2. Keep one strict target schema.
3. Track evidence and confidence for each field.
4. Use extractor ensembles, not a single model.
5. Learn continuously from discrepancies and corrections.

## Primary Commands

1. `doc-extract-run`: batch extraction from an input directory into normalized output artifacts.
2. `doc-extract-learn`: iterative rule learning from one input file and one golden file, with persistent rule caching.

`doc-extract-auto-iterate` remains available as an optional advanced/legacy workflow and is not required for the primary run/learn path.

## doc-extract-run Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User/Caller
    participant C as CLI (doc-extract-run)
    participant P as Pipeline
    participant L as Planner
    participant X as Extractors
    participant R as Reconciler
    participant A as Auditor
    participant M as Learner

    U->>C: Submit input folder + schema + config
    C->>P: Start run
    P->>L: Build extraction plan per file
    L->>X: Execute selected extractors
    X-->>P: Candidate values + confidence + evidence
    P->>R: Map candidates to target schema
    R-->>P: Final schema row + field statuses
    P->>A: Validate and compare against ground truth
    A-->>P: Audit summary + discrepancies
    P->>M: Persist run trajectory
    M-->>P: Learning artifacts updated
    P-->>U: extracted_output.xlsx + trace/audit files
```

## doc-extract-learn Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User/Caller
    participant C as CLI (doc-extract-learn)
    participant AL as AutonomousLearner
    participant N as TableNormalizer
    participant CA as ColumnMapper
    participant RA as RowAligner
    participant ML as MappingLearner
    participant AP as RuleApplier
    participant RC as RuleCache

    U->>C: Submit input file + golden file + schema + config
    C->>AL: run_learning_loop(...)
    AL->>RC: Load cached rules (optional)
    loop per iteration
        AL->>N: Normalize input and golden tables
        AL->>CA: Auto-map columns to schema fields
        AL->>RA: Align extracted rows to golden rows
        AL->>AP: Apply active rules and score row accuracy
        AL->>ML: Learn new rules from discrepancies
        ML-->>AL: Learned rules
        AL->>AP: Reload rules for next iteration
    end
    AL->>RC: Persist learned rules
    AL-->>C: History + best_accuracy + final_extracted_rows
    C-->>U: learning_result.json + learned_rules.json + extracted_final.xlsx/csv
```

## Output Artifacts

`doc-extract-run` emits:
- `extracted_output.xlsx`: normalized output rows
- `audit_summary.json`: high-level quality and counts
- `discrepancies.csv`: expected vs actual (if ground truth provided)
- `run_trace.json`: plan decisions and selected extractors
- `learning_events.jsonl`: append-only learning records

`doc-extract-learn` emits:
- `learning_result.json`: iteration history and final accuracy summary
- `learned_rules.json`: learned rule set
- `extracted_final.xlsx`: final learned extraction output
- `extracted_final.csv`: final learned extraction output (CSV)

## Extractor Ensemble

Current baseline extractors:
- llm_native for spreadsheet reasoning with few-shot examples
- excel_native as deterministic extraction for spreadsheets (including all-rows extraction path)
- pdf_native for colon-delimited key-value parsing in PDF text (optional path)

The reconciliation layer maps extractor candidates into one strict output schema.

## Learning Components

`doc-extract-learn` composes these components:
- `table_normalizer`: canonicalizes input and golden tables for alignment
- `column_mapper`: discovers deterministic source-column to schema-field mappings
- `row_aligner`: matches extracted rows to golden rows and summarizes discrepancies
- `mapping_learner`: uses local LLM to propose transformation rules
- `rule_applier`: applies learned rules and row filtering gates
- `rule_cache`: persists reusable rules across runs for schema-compatible inputs
