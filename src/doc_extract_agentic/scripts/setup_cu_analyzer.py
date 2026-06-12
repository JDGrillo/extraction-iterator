#!/usr/bin/env python
"""
Initialize Azure Content Understanding analyzer based on schema.

This script:
1. Loads your schema
2. Validates Azure CU configuration
3. Builds the field extraction prompt
4. Saves analyzer configuration for runtime use

Usage:
    python -m doc_extract_agentic.scripts.setup_cu_analyzer \
        --schema ./schemas/output_schema.example.json \
        --config ./configs/default.yaml \
        --output ./cu_analyzer_config.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from ..config import ConfigError, load_config, load_schema
from ..cu_initialization import build_cu_analyzer_config, validate_cu_config

logger = logging.getLogger(__name__)
app = typer.Typer(help="Set up Azure Content Understanding analyzer")


@app.callback(invoke_without_command=True)
def setup_analyzer(
    schema: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to output schema JSON"
    ),
    config: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to config YAML"
    ),
    output: Path = typer.Option(
        "cu_analyzer_config.json",
        dir_okay=False,
        help="Output path for analyzer configuration",
    ),
    verbose: bool = typer.Option(False, help="Enable verbose logging"),
) -> None:
    """Initialize and validate Azure Content Understanding analyzer."""

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    try:
        # Load schema and config
        typer.echo(f"Loading schema from {schema}...")
        out_schema = load_schema(schema)
        typer.echo(f"  Found {len(out_schema.fields)} fields")

        typer.echo(f"Loading config from {config}...")
        cfg = load_config(config)

        # Validate CU config
        typer.echo("Validating Azure CU configuration...")
        is_valid, error_msg = validate_cu_config(cfg)
        if not is_valid:
            typer.secho(f"  WARNING: {error_msg}", fg=typer.colors.YELLOW)
            typer.echo("  Azure CU will be disabled at runtime.")
            typer.echo("  To enable, set endpoint and api_key in config.")
        else:
            typer.secho("  ✓ Azure CU configuration is valid", fg=typer.colors.GREEN)

        # Build analyzer config
        typer.echo("Building analyzer configuration...")
        analyzer_cfg = build_cu_analyzer_config(out_schema, cfg)

        # Save to file
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as f:
            json.dump(analyzer_cfg, f, indent=2)

        typer.echo(f"\n✓ Analyzer configuration saved to {output}")
        typer.echo(f"\nField extraction prompt:")
        typer.echo("-" * 60)
        typer.echo(analyzer_cfg["prompt"])
        typer.echo("-" * 60)

    except ConfigError as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Setup failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
