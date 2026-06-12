from __future__ import annotations

from pathlib import Path

import typer

from .config import load_config, load_schema
from .pipeline import run_pipeline

app = typer.Typer(help="Run agentic document extraction baseline")


@app.callback(invoke_without_command=True)
def app_run(
    input_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output_dir: Path = typer.Option(..., file_okay=False),
    schema: Path = typer.Option(..., exists=True, dir_okay=False),
    config: Path = typer.Option(..., exists=True, dir_okay=False),
    ground_truth: Path | None = typer.Option(None, exists=True, dir_okay=False),
) -> None:
    cfg = load_config(config)
    out_schema = load_schema(schema)
    result = run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        schema=out_schema,
        config=cfg,
        ground_truth=ground_truth,
    )
    typer.echo(f"Run complete: {result['run_id']}")
    typer.echo(f"Output: {result['output_path']}")


if __name__ == "__main__":
    app()
