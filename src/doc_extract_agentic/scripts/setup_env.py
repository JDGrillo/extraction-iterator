#!/usr/bin/env python
"""Interactive setup script for Foundry Local model extraction."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

app = typer.Typer(help="Interactive setup for Foundry Local extraction")


def _run(cmd: list[str]) -> bool:
    try:
        subprocess.check_call(cmd)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _sdk_is_available() -> bool:
    try:
        import foundry_local_sdk  # noqa: F401

        return True
    except ModuleNotFoundError:
        return False


def _warm_model_with_sdk(model_alias: str, app_name: str) -> bool:
    try:
        from foundry_local_sdk import Configuration, FoundryLocalManager
    except ModuleNotFoundError:
        return False

    try:
        FoundryLocalManager.initialize(Configuration(app_name=app_name))
        manager = FoundryLocalManager.instance
        model = manager.catalog.get_model(model_alias)
        if model is None:
            typer.secho(
                f"  ✗ Model alias not found in catalog: {model_alias}",
                fg=typer.colors.RED,
            )
            return False

        is_cached = True
        if hasattr(model, "is_cached"):
            try:
                is_cached = bool(model.is_cached())
            except Exception:  # pylint: disable=broad-exception-caught
                is_cached = True

        if not is_cached and hasattr(model, "download"):
            typer.echo(f"  Downloading model alias: {model_alias}")
            model.download(lambda _pct: None)

        if hasattr(model, "load"):
            model.load()

        typer.secho(
            f"  ✓ Model is ready in Foundry Local: {model_alias}",
            fg=typer.colors.GREEN,
        )
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        typer.secho(f"  ✗ Foundry Local SDK warmup failed: {exc}", fg=typer.colors.RED)
        return False


@app.callback(invoke_without_command=True)
def setup_env(
    install_sdk: bool = typer.Option(
        True,
        help="Install Foundry Local Python SDK (Windows package)",
    ),
    pull_model: bool = typer.Option(
        True,
        help="Download/warm model alias via Foundry Local SDK",
    ),
    model_alias: str = typer.Option("phi-4-mini", help="Foundry Local model alias"),
    write_examples_file: bool = typer.Option(
        True,
        help="Create empty example store file if missing",
    ),
) -> None:
    typer.secho(
        "=== Foundry Local Extraction Setup ===\n",
        fg=typer.colors.BLUE,
        bold=True,
    )

    typer.echo("Step 1: Checking Foundry Local Python SDK...")
    if _sdk_is_available():
        typer.secho("  ✓ Foundry Local Python SDK detected", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "  ! Foundry Local Python SDK not detected yet",
            fg=typer.colors.YELLOW,
        )

    if install_sdk:
        typer.echo("\nStep 2: Installing Foundry Local Python SDK...")
        if _run(["pip", "install", "foundry-local-sdk-winml"]):
            typer.secho("  ✓ Installed foundry-local-sdk-winml", fg=typer.colors.GREEN)
        else:
            typer.secho(
                "  ✗ SDK install failed. Run manually: pip install foundry-local-sdk-winml",
                fg=typer.colors.RED,
            )

    if not _sdk_is_available():
        typer.secho(
            "  ✗ Foundry Local Python SDK is required. Install with: pip install foundry-local-sdk-winml",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    if pull_model:
        typer.echo("\nStep 3: Warming Foundry Local model...")
        _warm_model_with_sdk(model_alias=model_alias, app_name="doc-extract-agentic")

    if write_examples_file:
        typer.echo("\nStep 4: Preparing example store...")
        examples_path = Path("examples/training_examples.jsonl")
        examples_path.parent.mkdir(parents=True, exist_ok=True)
        if not examples_path.exists():
            examples_path.write_text("", encoding="utf-8")
            typer.secho(f"  ✓ Created {examples_path}", fg=typer.colors.GREEN)
        else:
            typer.secho(f"  ✓ Exists: {examples_path}", fg=typer.colors.GREEN)

    typer.echo("\nNext steps:")
    typer.echo(
        "  1. Confirm local_llm.provider is 'foundry_local_sdk' in configs/default.yaml"
    )
    typer.echo("  2. Add labeled examples to examples/training_examples.jsonl")
    typer.echo("  3. Run doc-extract-auto-iterate with --ground-truth")

    typer.secho("\n✓ Setup complete", fg=typer.colors.GREEN, bold=True)


if __name__ == "__main__":
    app()
