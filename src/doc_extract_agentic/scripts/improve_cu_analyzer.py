#!/usr/bin/env python
"""
Apply improvements to CU analyzer and rerun extraction.

This script:
1. Analyzes CU performance from a previous run
2. Applies suggested improvements to the analyzer
3. Reruns extraction on the same input with improved config
4. Compares results to show improvement

Usage:
    python -m doc_extract_agentic.scripts.improve_cu_analyzer \
        --previous-run ./runs/run_001 \
        --input-dir ./sample_inputs \
        --schema ./schemas/output_schema.example.json \
        --config ./configs/default.yaml \
        --new-run ./runs/run_002_improved
"""

from __future__ import annotations

from pathlib import Path

import typer

from ..config import load_config, load_schema
from ..cu_feedback_loop import CUFeedbackLoop
from ..pipeline import run_pipeline

app = typer.Typer(help="Apply CU improvements and rerun extraction")


@app.callback(invoke_without_command=True)
def improve_and_rerun(
    previous_run: Path = typer.Option(
        ...,
        exists=True,
        file_okay=False,
        help="Path to previous extraction run (contains learning_events.jsonl)",
    ),
    input_dir: Path = typer.Option(
        ..., exists=True, file_okay=False, help="Input documents to re-extract"
    ),
    schema: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to output schema JSON"
    ),
    config: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to config YAML"
    ),
    output_dir: Path = typer.Option(
        None, file_okay=False, help="Output directory for new run"
    ),
) -> None:
    """Analyze prior run, apply improvements, and rerun extraction."""

    if output_dir is None:
        output_dir = Path("runs/improved")

    try:
        typer.echo("Step 1: Loading schema and config...")
        out_schema = load_schema(schema)
        cfg = load_config(config)

        typer.echo("Step 2: Analyzing previous run for improvements...")
        feedback_loop = CUFeedbackLoop(previous_run, out_schema, cfg)
        report = feedback_loop.analyze_and_improve()

        typer.echo("Step 3: Applying improvements to config...")
        improved_config_path = output_dir / "config_improved.yaml"
        output_dir.mkdir(parents=True, exist_ok=True)
        feedback_loop.apply_improvements_to_config(
            report.get("suggested_improvements", {}),
            improved_config_path,
        )

        typer.echo("Step 4: Regenerating analyzer configuration...")
        analyzer_config_path = output_dir / "cu_analyzer_improved.json"
        feedback_loop.generate_improved_analyzer_config(analyzer_config_path)

        typer.echo(f"Step 5: Rerunning extraction with improved config...")
        typer.echo(f"  Input: {input_dir}")
        typer.echo(f"  Output: {output_dir}")

        # Load improved config
        improved_cfg = load_config(improved_config_path)

        # Run pipeline with improved config
        result = run_pipeline(
            input_dir=input_dir,
            output_dir=output_dir,
            schema=out_schema,
            config=improved_cfg,
            ground_truth=None,
        )

        typer.echo("\n" + "=" * 60)
        typer.echo("RERUN COMPLETE")
        typer.echo("=" * 60)
        typer.echo(f"Run ID: {result['run_id']}")
        typer.echo(f"Output: {result['output_path']}")
        typer.echo("\nNext steps:")
        typer.echo("1. Compare discrepancies between original and improved run:")
        typer.echo(
            f"   diff {previous_run}/discrepancies.csv {output_dir}/discrepancies.csv"
        )
        typer.echo("2. Check if CU fields improved:")
        typer.echo(
            f"   python -m doc_extract_agentic.scripts.analyze_cu_performance --run-dir {output_dir} --schema {schema} --config {improved_config_path}"
        )
        typer.echo("=" * 60 + "\n")

    except Exception as e:
        typer.secho(f"Rerun failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
