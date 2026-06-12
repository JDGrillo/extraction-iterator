#!/usr/bin/env python
"""
Interactive setup script for Azure Content Understanding.

This script guides you through:
1. Installing optional dependencies
2. Configuring Azure credentials
3. Initializing the CU analyzer

Usage:
    python -m doc_extract_agentic.scripts.setup_env
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer

app = typer.Typer(help="Interactive setup for Azure CU")


def prompt_azure_creds() -> dict:
    """Prompt user for Azure credentials."""
    typer.echo("\n=== Azure Content Understanding Setup ===\n")
    typer.echo(
        "To use Azure CU, you need a Document Intelligence resource in Azure.\n"
        "If you don't have one yet:\n"
        "1. Go to https://portal.azure.com\n"
        "2. Create a new 'Document Intelligence' resource\n"
        "3. Copy your endpoint and API key\n"
    )

    endpoint = typer.prompt(
        "Enter your Azure CU endpoint (e.g., https://my-resource.cognitiveservices.azure.com/)",
        default="",
    ).strip()

    api_key = typer.prompt(
        "Enter your Azure CU API key",
        default="",
        hide_input=True,
    ).strip()

    return {"endpoint": endpoint, "api_key": api_key}


@app.callback(invoke_without_command=True)
def setup_env(
    install_azure: bool = typer.Option(True, help="Install Azure SDK dependencies"),
    config_creds: bool = typer.Option(True, help="Configure Azure credentials"),
) -> None:
    """Set up environment for Azure Content Understanding."""

    typer.secho("=== Document Extraction Setup ===\n", fg=typer.colors.BLUE, bold=True)

    # Step 1: Install optional dependencies
    if install_azure:
        typer.echo("Step 1: Installing Azure SDK dependencies...")
        try:
            subprocess.check_call(
                ["pip", "install", "-e", ".[azure]"],
                cwd=Path(__file__).parent.parent.parent.parent,
            )
            typer.secho("  ✓ Azure dependencies installed\n", fg=typer.colors.GREEN)
        except subprocess.CalledProcessError as e:
            typer.secho(
                f"  ✗ Installation failed: {e}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

    # Step 2: Configure credentials
    if config_creds:
        typer.echo("Step 2: Configuring Azure credentials...\n")

        creds = prompt_azure_creds()

        if creds["endpoint"] and creds["api_key"]:
            # Option to save to environment or config
            save_method = typer.prompt(
                "\nHow to save credentials?",
                type=typer.Choice(["env", "config"]),
                default="env",
            )

            if save_method == "env":
                typer.echo("\nSet these environment variables:")
                typer.echo(f'  set AZURE_CU_ENDPOINT={creds["endpoint"]}')
                typer.echo(f'  set AZURE_CU_API_KEY={creds["api_key"]}')
                typer.echo("\nOr add to your .env file:")
                typer.echo(f'AZURE_CU_ENDPOINT={creds["endpoint"]}')
                typer.echo(f'AZURE_CU_API_KEY={creds["api_key"]}')
            elif save_method == "config":
                config_path = Path("configs/default.yaml")
                if config_path.exists():
                    content = config_path.read_text()
                    # Replace placeholders
                    content = content.replace(
                        'endpoint: ""', f'endpoint: "{creds["endpoint"]}"'
                    )
                    content = content.replace(
                        'api_key: ""', f'api_key: "{creds["api_key"]}"'
                    )
                    config_path.write_text(content)
                    typer.secho(
                        f"  ✓ Credentials saved to {config_path}",
                        fg=typer.colors.GREEN,
                    )
        else:
            typer.secho(
                "  Skipped (you can configure later)",
                fg=typer.colors.YELLOW,
            )

    typer.echo("\nStep 3: Next steps:")
    typer.echo("  1. Set your schema in schemas/output_schema.example.json")
    typer.echo("  2. Run: python -m doc_extract_agentic.scripts.setup_cu_analyzer \\")
    typer.echo("           --schema ./schemas/output_schema.example.json \\")
    typer.echo("           --config ./configs/default.yaml")
    typer.echo("  3. Enable CU: set 'enabled: true' in config")
    typer.echo("  4. Run extraction: doc-extract-run ...")

    typer.secho("\n✓ Setup complete!", fg=typer.colors.GREEN, bold=True)


if __name__ == "__main__":
    app()
