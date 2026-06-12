"""
Data-first extraction analysis: Discover what's in your data, optimize extractors.

This script shows you:
1. What data actually exists in your input files
2. How well each extractor finds that data
3. Which extraction strategies work best
4. What needs improvement and how
"""
from __future__ import annotations

from pathlib import Path

import typer

from .config import load_config
from .data_discovery import DataDiscoverer
from .extractor_performance_analyzer import ExtractorPerformanceAnalyzer

app = typer.Typer(help="Analyze extraction performance using data-first approach")


@app.command()
def analyze_data(
    input_dir: str = typer.Option(
        "./sample_inputs",
        "--input-dir",
        help="Directory with input documents to analyze",
    ),
    run_dir: str = typer.Option(
        None,
        "--run-dir",
        help="Run directory with learning_events.jsonl (for performance analysis)",
    ),
    config: str = typer.Option(
        "./configs/default.yaml",
        "--config",
        help="Configuration file",
    ),
    output_dir: str = typer.Option(
        "./data_analysis",
        "--output-dir",
        help="Where to write analysis reports",
    ),
):
    """
    Analyze your input data to discover what extractors should find.
    
    This shows:
    - What fields/values exist in your documents
    - Which extractors find them
    - Success rates and patterns
    - How to improve extraction
    
    Usage:
        # Discover what's in your input files
        analyze-data --input-dir ./invoices
        
        # Also analyze extractor performance
        analyze-data --input-dir ./invoices --run-dir ./runs/v1
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    if run_dir:
        run_path = Path(run_dir)
    else:
        run_path = None

    output_path.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("DATA-FIRST EXTRACTION ANALYSIS")
    print("=" * 70)

    # Phase 1: Discover what's in the data
    print("\n📊 PHASE 1: DISCOVERING DATA PATTERNS...")
    print(f"Scanning input files in {input_path}...")

    discoverer = DataDiscoverer(input_path)
    discovery_result = discoverer.discover()

    discoverer.write_discovery_report(output_path)

    # Print discovery summary
    summary = discovery_result["summary"]
    print(f"\nDiscovered {summary['total_unique_fields']} potential fields")
    print(f"Found {summary['total_discovered_values']} total values")
    print(f"  • Excel: {summary['excel_findings_count']} findings")
    print(f"  • PDF: {summary['pdf_findings_count']} findings")

    if discovery_result["field_patterns"]:
        print("\nTop discovered fields:")
        sorted_fields = sorted(
            discovery_result["field_patterns"].items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )
        for field_name, pattern in sorted_fields[:10]:
            count = pattern["count"]
            unique = pattern["unique_count"]
            examples = pattern["examples"]
            print(f"  • {field_name}: found {count} times ({unique} unique)")
            for example in examples[:1]:
                print(f"      Example: '{example}'")

    # Phase 2: Analyze extractor performance (if run_dir provided)
    if run_path and run_path.exists():
        print("\n" + "=" * 70)
        print("📈 PHASE 2: ANALYZING EXTRACTOR PERFORMANCE...")
        print(f"Analyzing extraction run in {run_path}...")

        perf_analyzer = ExtractorPerformanceAnalyzer(run_path)
        perf_analyzer.write_performance_report(output_path, discovery_result)

        # Print improvement suggestions
        events = perf_analyzer.load_learning_events()
        performance = perf_analyzer.analyze_all_extractors(events)
        strategies = perf_analyzer.identify_best_strategies(performance)
        suggestions = perf_analyzer.generate_improvement_suggestions(strategies)

        low_performing_fields = [
            f
            for f, s in strategies.items()
            if s.get("improvement_needed", False)
        ]

        if low_performing_fields:
            print(f"\n⚠️  {len(low_performing_fields)} fields need improvement:")
            for field in sorted(low_performing_fields)[:5]:
                strategy = strategies[field]
                print(
                    f"  • {field}: {strategy['success_rate']:.1%} "
                    f"(using {strategy['best_extractor']})"
                )

        print("\n✅ Reports written to:")
        print(f"  • {output_path / 'extractor_performance.json'}")
        print(f"  • {output_path / 'field_extraction_strategy.json'}")
        print(f"  • {output_path / 'improvement_suggestions.json'}")

    else:
        print("\n💡 Tip: To analyze extractor performance, run your extraction first:")
        print("  doc-extract-run --input-dir ./invoices --output-dir ./runs/v1 ...")
        print("  Then run: analyze-data --input-dir ./invoices --run-dir ./runs/v1")

    print("\n" + "=" * 70)
    print("📁 Full analysis reports saved to:", output_path)
    print("=" * 70 + "\n")


if __name__ == "__main__":
    app()
