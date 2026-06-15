"""CLI: Offline autonomous local-LLM extraction loop."""

from __future__ import annotations

from pathlib import Path

import typer

from ..auto_iterator import AutoIterateConfig, AutoIterator

app = typer.Typer(help="Autonomous local-LLM extraction loop with regression gates")


@app.command()
def auto_iterate(
    input_dir: str = typer.Option("./input", "--input-dir"),
    schema: str = typer.Option("./schemas/extract-test-output.schema.json", "--schema"),
    output_dir: str = typer.Option("./output/auto_iterate", "--output-dir"),
    config: str = typer.Option("./configs/default.yaml", "--config"),
    ground_truth: str = typer.Option(
        ..., "--ground-truth", help="Ground truth xlsx for scoring."
    ),
    max_iterations: int = typer.Option(6, "--max-iterations"),
    target_accuracy: float = typer.Option(0.97, "--target-accuracy"),
    min_improvement_delta: float = typer.Option(0.002, "--min-improvement-delta"),
) -> None:
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    schema_path = Path(schema)
    config_path = Path(config)
    gt_path = Path(ground_truth)

    for path, label in [
        (input_path, "input directory"),
        (schema_path, "schema file"),
        (config_path, "config file"),
        (gt_path, "ground truth file"),
    ]:
        if not path.exists():
            typer.echo(f"Error: {label} not found: {path}", err=True)
            raise typer.Exit(1)

    iterator = AutoIterator(
        input_dir=input_path,
        output_base_dir=output_path,
        schema_path=schema_path,
        config_path=config_path,
        ground_truth_path=gt_path,
        auto_cfg=AutoIterateConfig(
            max_iterations=max_iterations,
            target_accuracy=target_accuracy,
            min_improvement_delta=min_improvement_delta,
        ),
    )

    report = iterator.run()
    history = report.get("history", [])
    if history:
        typer.echo(
            "Final validation accuracy: "
            f"{history[-1].get('validation_accuracy', 0.0):.2%}"
        )
        typer.echo(
            "Final holdout accuracy: " f"{history[-1].get('holdout_accuracy', 0.0):.2%}"
        )
    typer.echo(f"Report: {output_path / 'iteration_report.json'}")


if __name__ == "__main__":
    app()
