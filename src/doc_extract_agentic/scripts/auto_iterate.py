"""CLI: Autonomous extraction iteration until success criteria met."""

from __future__ import annotations

from pathlib import Path

import typer

from ..auto_iterator import AutoIterateConfig, AutoIterator
from ..config import load_config

app = typer.Typer(help="Autonomous extraction iteration and improvement")


@app.command()
def auto_iterate(
    input_dir: str = typer.Option("./input_data/batch_001", "--input-dir"),
    schema: str = typer.Option(
        "./schemas/output_schema.example.json",
        "--schema",
        help="Path to output schema JSON file.",
    ),
    output_dir: str = typer.Option(
        "./output_data/auto_iterate",
        "--output-dir",
        help="Base directory for iteration runs (will create iter_01, iter_02, etc.)",
    ),
    config: str = typer.Option(
        "./configs/default.yaml",
        "--config",
        help="Path to configuration YAML file.",
    ),
    max_iterations: int = typer.Option(
        5,
        "--max-iterations",
        help="Maximum number of iterations to attempt.",
    ),
    target_success_rate: float = typer.Option(
        0.85,
        "--target-success-rate",
        help="Target success rate (0.0-1.0) for convergence.",
    ),
    min_improvement_delta: float = typer.Option(
        0.05,
        "--min-improvement-delta",
        help="Minimum improvement per iteration before stopping.",
    ),
    target_confidence: float = typer.Option(
        0.75,
        "--target-confidence",
        help="Confidence threshold for 'found' field.",
    ),
) -> None:
    """
    Run autonomous extraction improvement loop.

    Starts with a baseline extraction, then repeatedly:
    1. Analyzes performance to identify weak fields
    2. Proposes missing aliases from document labels
    3. Applies approved aliases to schema
    4. Reruns extraction with updated schema
    5. Compares results; repeats if improvement is sufficient

    Stops when:
    - All fields reach target_success_rate, OR
    - Improvement falls below min_improvement_delta, OR
    - Max iterations reached

    Example:
        doc-extract-auto-iterate \\
            --input-dir ./docs \\
            --schema ./schema.json \\
            --output-dir ./iterations \\
            --target-success-rate 0.90 \\
            --max-iterations 10
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    schema_path = Path(schema)
    config_path = Path(config)

    if not input_path.exists():
        typer.echo(f"Error: input directory not found: {input_path}", err=True)
        raise typer.Exit(1)

    if not schema_path.exists():
        typer.echo(f"Error: schema file not found: {schema_path}", err=True)
        raise typer.Exit(1)

    if not config_path.exists():
        typer.echo(f"Error: config file not found: {config_path}", err=True)
        raise typer.Exit(1)

    auto_cfg = AutoIterateConfig(
        max_iterations=max_iterations,
        target_success_rate=target_success_rate,
        min_improvement_delta=min_improvement_delta,
        target_confidence=target_confidence,
    )

    iterator = AutoIterator(
        input_dir=input_path,
        output_base_dir=output_path,
        schema_path=schema_path,
        config_path=config_path,
        auto_cfg=auto_cfg,
    )

    result = iterator.run()
    if result["iterations"] > 0:
        typer.echo(f"\n✓ Completed {result['iterations']} iteration(s)")
        typer.echo(f"✓ Report: {result['report_path']}")


if __name__ == "__main__":
    app()
