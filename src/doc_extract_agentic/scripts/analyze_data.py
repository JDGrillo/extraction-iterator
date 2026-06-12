"""Data-first extraction analysis: discover patterns, measure performance, self-correct."""
from __future__ import annotations

import json as _json
from pathlib import Path

import typer

from ..config import load_config
from ..data_discovery import DataDiscoverer
from ..extractor_performance_analyzer import ExtractorPerformanceAnalyzer
from ..extractors.excel_native import ExcelNativeExtractor
from ..extractors.pdf_native import PdfNativeExtractor
from ..llm_improvement import LLMImprovementSuggester

app = typer.Typer(help="Analyze extraction performance using data-first approach")


@app.command()
def analyze_data(
    input_dir: str = typer.Option("./input_data/batch_001", "--input-dir"),
    run_dir: str = typer.Option(None, "--run-dir"),
    config: str = typer.Option("./configs/default.yaml", "--config"),
    output_dir: str = typer.Option("./data_analysis", "--output-dir"),
    schema: str = typer.Option(
        None,
        "--schema",
        help="Schema JSON. Enables LLM self-correction when combined with --run-dir.",
    ),
    auto_correct: bool = typer.Option(
        False,
        "--auto-correct",
        help="Apply LLM alias suggestions directly back into the schema file.",
    ),
) -> None:
    """
    Analyze input data, measure extractor performance, and optionally self-correct.

    Phase 1 (always): Discover patterns in input documents.
    Phase 2 (with --run-dir): Measure extractor success rates per field.
    Phase 3 (--run-dir + --schema + LLM enabled): Propose missing aliases from
    actual document labels and optionally apply them back into the schema.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    schema_path = Path(schema) if schema else None
    run_path = Path(run_dir) if run_dir else None
    cfg = load_config(Path(config))
    output_path.mkdir(parents=True, exist_ok=True)

    sep = "=" * 70
    print(f"\n{sep}\nDATA-FIRST EXTRACTION ANALYSIS\n{sep}")

    # Phase 1 ----------------------------------------------------------------
    print("\n[1/3] DISCOVERING DATA PATTERNS ...")
    print(f"  Scanning: {input_path}")
    discoverer = DataDiscoverer(input_path)
    discovery_result = discoverer.discover()
    discoverer.write_discovery_report(output_path)
    summary = discovery_result["summary"]
    print(f"  Fields discovered: {summary['total_unique_fields']}")
    print(
        f"  Excel: {summary['excel_findings_count']} findings  |  "
        f"PDF: {summary['pdf_findings_count']} findings"
    )
    sorted_fields = sorted(
        discovery_result.get("field_patterns", {}).items(),
        key=lambda x: x[1]["count"],
        reverse=True,
    )
    if sorted_fields:
        print("\n  Top fields found in documents:")
        for field_name, pattern in sorted_fields[:10]:
            example = (pattern.get("examples") or [""])[0]
            print(f"    {field_name}: {pattern['count']} occurrences  (e.g. '{example}')")

    if not (run_path and run_path.exists()):
        print("\n  Tip: add --run-dir <run_folder> after an extraction run for performance analysis.")
        print(sep + "\n")
        return

    # Phase 2 ----------------------------------------------------------------
    print("\n[2/3] ANALYSING EXTRACTOR PERFORMANCE ...")
    print(f"  Run: {run_path}")
    llm_suggester = LLMImprovementSuggester.from_config(cfg)
    perf_analyzer = ExtractorPerformanceAnalyzer(run_path)
    perf_analyzer.write_performance_report(
        output_path, discovery_result, llm_suggester=llm_suggester
    )
    events = perf_analyzer.load_learning_events()
    performance = perf_analyzer.analyze_all_extractors(events)
    strategies = perf_analyzer.identify_best_strategies(performance)
    low_fields = [f for f, s in strategies.items() if s.get("improvement_needed", False)]
    if low_fields:
        print(f"\n  {len(low_fields)} field(s) below quality threshold:")
        for field in sorted(low_fields)[:5]:
            st = strategies[field]
            print(f"    {field}: {st['success_rate']:.1%}  (best: {st['best_extractor']})")
    print("\n  Reports written to:", output_path)

    # Phase 3 ----------------------------------------------------------------
    if not (schema_path and llm_suggester.is_ready()):
        if schema_path and not llm_suggester.is_ready():
            print("\n  [3/3] LLM self-correction skipped (llm_improvement.enabled = false)")
        print(sep + "\n")
        return

    not_found = [f for f, s in strategies.items() if s.get("success_rate", 1.0) == 0.0]
    low_success = [
        f for f, s in strategies.items() if 0.0 < s.get("success_rate", 1.0) < 0.6
    ]
    correction_targets = list(dict.fromkeys(not_found + low_success))

    print("\n[3/3] LLM SELF-CORRECTION ...")
    if not correction_targets:
        print("  All fields above threshold — no correction needed.")
        print(sep + "\n")
        return

    print(f"  Targeting: {correction_targets}")

    excel_ext = ExcelNativeExtractor()
    pdf_ext = PdfNativeExtractor()
    raw_keys_by_file: dict[str, list[str]] = {}
    for fpath in list(input_path.glob("**/*.xlsx")) + list(input_path.glob("**/*.xls")):
        raw_keys_by_file[fpath.name] = excel_ext.collect_raw_keys(fpath)
    for fpath in input_path.glob("**/*.pdf"):
        raw_keys_by_file[fpath.name] = pdf_ext.collect_raw_keys(fpath)

    try:
        schema_fields = _json.loads(schema_path.read_text(encoding="utf-8")).get("fields", [])
    except Exception:
        schema_fields = []

    alias_suggestions = llm_suggester.suggest_aliases(
        schema_fields=schema_fields,
        raw_keys_by_file=raw_keys_by_file,
        not_found_fields=correction_targets,
    )

    if not alias_suggestions:
        print("  LLM found no new alias candidates in the document labels.")
        print(sep + "\n")
        return

    print(f"\n  LLM suggested aliases for {len(alias_suggestions)} field(s):")
    for fname, aliases in alias_suggestions.items():
        print(f"    {fname}: {aliases}")

    suggestions_path = output_path / "alias_suggestions.json"
    suggestions_path.write_text(_json.dumps(alias_suggestions, indent=2), encoding="utf-8")

    if auto_correct:
        updated = llm_suggester.apply_alias_suggestions(schema_path, alias_suggestions)
        if updated:
            print(f"\n  Applied aliases to {updated} field(s) in {schema_path}")
            print("  Re-run doc-extract-run to pick up the updated aliases.")
        else:
            print("\n  Suggestions already present in schema — nothing to apply.")
    else:
        print(f"\n  Saved to {suggestions_path}")
        print("  Re-run with --auto-correct to apply, or edit the schema manually.")

    print(sep + "\n")


if __name__ == "__main__":
    app()
