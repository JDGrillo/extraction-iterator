"""Entry point for autonomous learning-based extraction."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .autonomous_learner import AutonomousLearner
from .config import load_config, load_schema

app = typer.Typer(help="Autonomous learning-based document extraction")


@app.command()
def learn(
    input_file: Path = typer.Option(
        ..., "--input-file", exists=True, dir_okay=False, help="Input Excel file"
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", help="Output directory for artifacts"
    ),
    schema: Path = typer.Option(
        ..., "--schema", exists=True, dir_okay=False, help="Output schema file"
    ),
    config: Path = typer.Option(
        ..., "--config", exists=True, dir_okay=False, help="Configuration file"
    ),
    ground_truth: Path = typer.Option(
        ...,
        "--ground-truth",
        exists=True,
        dir_okay=False,
        help="Golden/ground truth data",
    ),
    max_iterations: int = typer.Option(
        6, "--max-iterations", help="Maximum iterations"
    ),
    target_accuracy: float = typer.Option(
        0.95, "--target-accuracy", help="Target accuracy (0.0-1.0)"
    ),
    min_improvement: float = typer.Option(
        0.01, "--min-improvement-delta", help="Minimum improvement threshold"
    ),
) -> None:
    """
    Run autonomous learning loop to discover transformation rules
    and iteratively improve extraction accuracy.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config)
    schema_def = load_schema(schema)
    schema_fields = [field.name for field in schema_def.fields]

    print("\n" + "=" * 72)
    print("AUTONOMOUS LEARNING EXTRACTION LOOP")
    print("=" * 72)
    print(f"Input file: {input_file}")
    print(f"Ground truth: {ground_truth}")
    print(f"Target accuracy: {target_accuracy:.2%}")
    print(f"Max iterations: {max_iterations}")

    learner = AutonomousLearner(cfg)
    result = learner.run_learning_loop(
        input_file=input_file,
        golden_file=ground_truth,
        schema_fields=schema_fields,
        max_iterations=max_iterations,
        target_accuracy=target_accuracy,
        min_improvement_delta=min_improvement,
    )

    # Write results
    result_file = output_dir / "learning_result.json"
    result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")

    rules_file = output_dir / "learned_rules.json"
    rules_file.write_text(
        json.dumps(result["learned_rules"], indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 72)
    print("LEARNING COMPLETE")
    print("=" * 72)
    print(f"Final iteration: {result['final_iteration']}")
    print(f"Best accuracy: {result['best_accuracy']:.2%}")
    print(f"Target reached: {result['target_reached']}")
    print(f"Rules learned: {len(result['learned_rules'].get('rules', []))}")
    print(f"\nResults written to: {output_dir}")
    print(f"  - {result_file.name}")
    print(f"  - {rules_file.name}")


if __name__ == "__main__":
    app()
