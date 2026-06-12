#!/usr/bin/env python
"""
Analyze Azure Content Understanding performance and suggest improvements.

This script:
1. Loads extraction history from learning_events.jsonl
2. Analyzes which fields CU missed while other extractors found
3. Identifies gaps and provides improvement suggestions
4. Generates performance report

Usage:
    python -m doc_extract_agentic.scripts.analyze_cu_performance \
        --run-dir ./runs/run_001 \
        --schema ./schemas/output_schema.example.json \
        --config ./configs/default.yaml
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..config import load_config, load_schema
from ..cu_feedback_loop import CUFeedbackLoop
from ..cu_performance_analyzer import CUPerformanceAnalyzer

app = typer.Typer(help="Analyze CU performance and suggest improvements")


@app.callback(invoke_without_command=True)
def analyze_cu_performance(
    run_dir: Path = typer.Option(
        ..., exists=True, file_okay=False, help="Path to extraction run output"
    ),
    schema: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to output schema JSON"
    ),
    config: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to config YAML"
    ),
    output_report: Path = typer.Option(
        None, dir_okay=False, help="Output path for performance report"
    ),
) -> None:
    """Analyze CU performance and generate improvement suggestions."""

    if output_report is None:
        output_report = run_dir / "cu_feedback_report.json"

    try:
        typer.echo("Loading schema and config...")
        out_schema = load_schema(schema)
        cfg = load_config(config)

        typer.echo(f"Analyzing run in {run_dir}...")
        feedback_loop = CUFeedbackLoop(run_dir, out_schema, cfg)
        report = feedback_loop.analyze_and_improve()

        # Pretty-print summary
        analysis = report.get("analysis", {})
        summary = analysis.get("summary", {})
        gaps = analysis.get("high_priority_gaps", [])

        typer.echo("\n" + "=" * 60)
        typer.echo("AZURE CONTENT UNDERSTANDING PERFORMANCE REPORT")
        typer.echo("=" * 60)

        typer.echo(f"\nFields Analyzed: {summary.get('total_fields_analyzed')}")
        typer.echo(f"Performing Well (>85%): {summary.get('fields_performing_well')}")
        typer.echo(
            f"Need Improvement (<70%): {summary.get('fields_needing_improvement')}"
        )

        if gaps:
            typer.echo("\n" + "-" * 60)
            typer.echo("HIGH-PRIORITY GAPS (Fields where CU underperforms)")
            typer.echo("-" * 60)
            for i, gap in enumerate(gaps[:5], 1):
                typer.echo(f"\n{i}. {gap['field']}")
                typer.echo(
                    f"   Success Rate: {gap['cu_success_rate']:.1%} "
                    f"(others found {gap['other_extractors_beat_cu']} more times)"
                )
                typer.echo(f"   Action: {gap['recommendation']}")

        improvements = report.get("suggested_improvements", {})
        if improvements.get("priority_fields"):
            typer.echo("\n" + "-" * 60)
            typer.echo("RECOMMENDED ACTIONS")
            typer.echo("-" * 60)
            for item in improvements["priority_fields"]:
                typer.echo(f"- {item['field']}: {item['action']}")

        typer.echo(f"\n✓ Report saved to {output_report}")
        typer.echo("=" * 60 + "\n")

    except Exception as e:
        typer.secho(f"Analysis failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
