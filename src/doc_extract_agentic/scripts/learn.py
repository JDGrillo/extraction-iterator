"""CLI: Autonomous learning-based extraction with rule discovery."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..autonomous_learner import AutonomousLearner
from ..config import load_config, load_schema

app = typer.Typer(help="Autonomous learning-based document extraction")


@app.command()
def learn(
    input_file: str = typer.Option(
        "input/extract-test-input.xlsx", "--input-file", help="Input Excel file"
    ),
    output_dir: str = typer.Option(
        "output/learn", "--output-dir", help="Output directory"
    ),
    schema: str = typer.Option(
        "schemas/extract-test-output.schema.json", "--schema", help="Schema file"
    ),
    config: str = typer.Option("configs/default.yaml", "--config", help="Config file"),
    ground_truth: str = typer.Option(
        ..., "--ground-truth", help="Golden/ground truth data file"
    ),
    max_iterations: int = typer.Option(6, "--max-iterations"),
    target_accuracy: float = typer.Option(0.95, "--target-accuracy"),
    min_improvement_delta: float = typer.Option(0.01, "--min-improvement-delta"),
    use_cached_rules: bool = typer.Option(
        True,
        "--use-cached-rules/--skip-cached-rules",
        help="Bootstrap from cached rules",
    ),
    rules_cache_dir: str = typer.Option(
        ".cache/rules", "--rules-cache-dir", help="Directory for rule cache"
    ),
) -> None:
    """
    Autonomous learning loop: discover and apply transformation rules
    to improve extraction quality without human intervention.
    """
    input_path = Path(input_file)
    output_path = Path(output_dir)
    schema_path = Path(schema)
    config_path = Path(config)
    gt_path = Path(ground_truth)

    # Validate inputs
    for path, label in [
        (input_path, "input file"),
        (schema_path, "schema file"),
        (config_path, "config file"),
        (gt_path, "ground truth file"),
    ]:
        if not path.exists():
            typer.echo(f"Error: {label} not found: {path}", err=True)
            raise typer.Exit(1)

    output_path.mkdir(parents=True, exist_ok=True)

    # Load config and schema
    cfg = load_config(config_path)
    schema_def = load_schema(schema_path)
    schema_fields = [field.name for field in schema_def.fields]

    # Derive display names from golden file if available (golden columns are the
    # human-readable field names that match the extracted data; schema field names
    # are snake_case identifiers used internally).
    import pandas as pd

    try:
        golden_df = pd.read_excel(gt_path)
        golden_schema_fields = list(golden_df.columns)
    except Exception:
        golden_schema_fields = schema_fields

    print("\n" + "=" * 72)
    print("AUTONOMOUS LEARNING EXTRACTION LOOP")
    print("=" * 72)
    print(f"Input file: {input_path}")
    print(f"Ground truth: {gt_path}")
    print(f"Target accuracy: {target_accuracy:.2%}")
    print(f"Max iterations: {max_iterations}")
    print(f"Use cached rules: {use_cached_rules}")
    print(f"Rules cache: {rules_cache_dir}")

    # Run autonomous learner
    cache_dir = Path(rules_cache_dir)
    learner = AutonomousLearner(cfg, rules_cache_dir=cache_dir)
    result = learner.run_learning_loop(
        input_file=input_path,
        golden_file=gt_path,
        schema_fields=golden_schema_fields,
        max_iterations=max_iterations,
        target_accuracy=target_accuracy,
        min_improvement_delta=min_improvement_delta,
        use_cached_rules=use_cached_rules,
    )

    # Write results
    result_file = output_path / "learning_result.json"
    result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")

    rules_file = output_path / "learned_rules.json"
    rules_file.write_text(
        json.dumps(result["learned_rules"], indent=2), encoding="utf-8"
    )

    # Write extracted data to Excel and CSV
    if result.get("final_extracted_rows") and result.get("schema_fields"):
        import pandas as pd

        df = pd.DataFrame(
            result["final_extracted_rows"], columns=result["schema_fields"]
        )

        xlsx_file = output_path / "extracted_final.xlsx"
        df.to_excel(xlsx_file, index=False)
        print(f"  - {xlsx_file.name}")

        csv_file = output_path / "extracted_final.csv"
        df.to_csv(csv_file, index=False)
        print(f"  - {csv_file.name}")

    # Print summary
    print("\n" + "=" * 72)
    print("LEARNING COMPLETE")
    print("=" * 72)
    print(f"Final iteration: {result['final_iteration']}")
    print(f"Best accuracy: {result['best_accuracy']:.2%}")
    print(f"Target reached: {result['target_reached']}")
    rules_count = len(result["learned_rules"].get("rules", []))
    print(f"Rules learned: {rules_count}")
    print(f"Rules cached: {result.get('rules_cached', False)}")

    if result["history"]:
        print("\nIteration history:")
        for h in result["history"]:
            print(
                f"  Iter {h['iteration']}: {h['accuracy']:.2%} "
                f"({h['rows_correct']}/{h['total_rows']}) - "
                f"{h['rules_count']} rules"
            )

    print(f"\nResults written to: {output_path}")
    print(f"  - {result_file.name}")
    print(f"  - {rules_file.name}")
    if result.get("rules_cached"):
        print(f"\nRules cached in: {rules_cache_dir}")
        print("  Rules will be reused for new documents with this schema.")


if __name__ == "__main__":
    app()
