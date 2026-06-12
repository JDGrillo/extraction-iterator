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

## 3) Improve Extractors

Start with:
- `extractors/excel_native.py`
- `extractors/pdf_native.py`

Add domain logic for:
- multi-sheet table detection
- section-specific parsing
- regex/normalization rules for dates/currency/IDs

## 4) Implement Azure Content Understanding

Replace `extractors/azure_content_understanding.py` with actual API calls and map CU output to schema fields.

## 5) Strengthen Reconciliation

Update `reconciler.py` to include:
- per-field scoring weights
- cross-field validations
- source precedence rules

## 6) Learning and Evaluation

Use generated artifacts:
- `learning_events.jsonl` for policy learning
- `discrepancies.csv` for error-focused retraining

## 7) Deploy as Service (Next)

Wrap CLI in a lightweight API (FastAPI) for on-demand runs and integrate a job queue if volume grows.
