#!/usr/bin/env python
"""
Validate Azure Content Understanding configuration and test connectivity.

Usage:
    python -m doc_extract_agentic.scripts.test_cu_config \
        --config ./configs/default.yaml
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from ..config import ConfigError, load_config
from ..cu_client import AzureContentUnderstandingClient
from ..cu_initialization import validate_cu_config

logger = logging.getLogger(__name__)
app = typer.Typer(help="Test Azure Content Understanding configuration")


@app.callback(invoke_without_command=True)
def test_cu_config(
    config: Path = typer.Option(
        ..., exists=True, dir_okay=False, help="Path to config YAML"
    ),
) -> None:
    """Validate and test Azure CU configuration."""

    logging.basicConfig(level=logging.INFO)

    try:
        typer.echo("Loading config...")
        cfg = load_config(config)

        typer.echo("\n1. Validating configuration schema...")
        is_valid, error_msg = validate_cu_config(cfg)
        if not is_valid:
            typer.secho(f"   ✗ {error_msg}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho("   ✓ Configuration is valid", fg=typer.colors.GREEN)

        cu_cfg = cfg.get("azure_content_understanding", {})

        typer.echo("\n2. Testing Azure endpoint connectivity...")
        client = AzureContentUnderstandingClient(
            endpoint=cu_cfg.get("endpoint", ""),
            api_key=cu_cfg.get("api_key", ""),
            model=cu_cfg.get("model", "prebuilt-document"),
        )

        # Try to get the client (this validates credentials)
        cu_client = client._get_client()
        if cu_client is None:
            typer.secho(
                "   ✗ Azure SDK not installed (optional for baseline)",
                fg=typer.colors.YELLOW,
            )
            typer.echo("\n   To install: pip install azure-ai-documentintelligence")
        else:
            typer.secho(
                "   ✓ Azure client initialized successfully", fg=typer.colors.GREEN
            )

        typer.echo("\n3. Configuration summary:")
        typer.echo(f"   Endpoint: {cu_cfg.get('endpoint', 'not set')}")
        typer.echo(f"   Model: {cu_cfg.get('model', 'prebuilt-document')}")
        typer.echo(f"   Enabled: {cu_cfg.get('enabled', False)}")
        typer.echo(f"   Mode: {cu_cfg.get('mode', 'fallback_only')}")

        typer.secho(
            "\n✓ Azure CU configuration test complete",
            fg=typer.colors.GREEN,
        )

    except ConfigError as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Test failed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
