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

## doc-extract-run Flow (Mermaid, SLM Handoff Focus)

```mermaid
flowchart TD
    A[User runs doc-extract-run] --> B[Load config and schema]
    B --> C[Planner builds per-file extraction plan]

    C --> D1[excel_native deterministic extraction]
    C --> D2[llm_native SLM extraction]
    C --> D3[pdf_native optional deterministic parse]

    D1 --> E[Candidate pool with evidence and confidence]
    D2 --> E
    D3 --> E

    E --> F{SLM handoff check}
    F -->|High overlap, low conflict| G[Allow targeted SLM fills for missing fields]
    F -->|Low overlap or generic-value drift| H[Constrain to deterministic winners]

    G --> I[Reconcile to strict target schema]
    H --> I

    I --> J[Audit and validation summary]
    J --> K[Persist run_trace and learning_events]
    K --> L[Append handoff event history]
    L --> M[Emit extracted output artifacts]
```

Run-path rationale:
- Deterministic extraction anchors row identity and stable field coverage.
- SLM candidates are only promoted when overlap/conflict checks indicate net quality lift.
- Handoff events are persisted so recurring conflict fields feed later learning.

## doc-extract-learn Flow (Mermaid, Proposer/Critic Handoff Focus)

```mermaid
flowchart TD
    A[User runs doc-extract-learn] --> B[Load schema, config, golden file]
    B --> C[Bootstrap rules from schema-keyed cache history]

    C --> D[Normalize input and golden tables]
    D --> E[Auto-map columns and align rows]
    E --> F[Apply active rules and score schema accuracy]

    F --> G[Proposer SLM generates candidate transforms]
    G --> H[Critic SLM adversarial review]
    H --> I{Rule governance gate}

    I -->|Accepted: impact and confidence pass| J[Promote rule set]
    I -->|Rejected: no improvement or low confidence| K[Drop or quarantine rules]

    J --> L[Tag provenance proposer or critic]
    K --> M[Record rejection reason]
    L --> N[Persist learned rules and iteration history]
    M --> N

    N --> O[Append learning handoff event history]
    O --> P{Stop criteria met?}
    P -->|No| D
    P -->|Yes| Q[Emit learning_result and extracted_final artifacts]
```

Learn-path rationale:
- Proposer explores broader transformations; critic compresses to precise, high-confidence rules.
- Acceptance is impact-based, not volume-based, preventing rule-count inflation.
- Shared handoff history closes the loop so repeated run/learn conflicts become explicit prompts in later iterations.

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
