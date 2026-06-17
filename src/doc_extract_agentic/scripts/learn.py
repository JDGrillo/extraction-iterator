"""CLI: Autonomous learning-based extraction with rule discovery."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..autonomous_learner import AutonomousLearner
from ..config import load_config, load_schema

app = typer.Typer(help="Autonomous learning-based document extraction")


def _find_matching_input(
    golden_path: Path,
    input_dir: Path,
) -> Path | None:
    stem = golden_path.stem.lower()
    candidates = [
        p
        for p in list(input_dir.glob("*.xlsx")) + list(input_dir.glob("*.xls"))
        if p.stem.lower() == stem
    ]
    if candidates:
        return candidates[0]

    # Fallback: prefix overlap for files with slight naming differences.
    relaxed = [
        p
        for p in list(input_dir.glob("*.xlsx")) + list(input_dir.glob("*.xls"))
        if stem in p.stem.lower() or p.stem.lower() in stem
    ]
    return relaxed[0] if relaxed else None


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
        schema_fields=schema_fields,
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

    analysis_file = output_path / "learn_run_analysis.json"
    analysis_file.write_text(
        json.dumps(result.get("learn_run_analysis", {}), indent=2), encoding="utf-8"
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
    print(f"  - {analysis_file.name}")
    if result.get("rules_cached"):
        print(f"\nRules cached in: {rules_cache_dir}")
        print("  Rules will be reused for new documents with this schema.")


@app.command("learn-batch")
def learn_batch(
    input_dir: str = typer.Option(
        "input", "--input-dir", help="Directory containing input Excel files"
    ),
    ground_truth_dir: str = typer.Option(
        ..., "--ground-truth-dir", help="Directory with golden/ground truth files"
    ),
    output_dir: str = typer.Option(
        "output/learn_batch", "--output-dir", help="Batch output directory"
    ),
    schema: str = typer.Option(
        "schemas/extract-sov.schema.json", "--schema", help="Schema file"
    ),
    config: str = typer.Option("configs/default.yaml", "--config", help="Config file"),
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
    input_path = Path(input_dir)
    gt_dir = Path(ground_truth_dir)
    output_path = Path(output_dir)
    schema_path = Path(schema)
    config_path = Path(config)

    for path, label in [
        (input_path, "input directory"),
        (gt_dir, "ground truth directory"),
        (schema_path, "schema file"),
        (config_path, "config file"),
    ]:
        if not path.exists():
            typer.echo(f"Error: {label} not found: {path}", err=True)
            raise typer.Exit(1)

    output_path.mkdir(parents=True, exist_ok=True)
    cfg = load_config(config_path)
    schema_def = load_schema(schema_path)
    schema_fields = [field.name for field in schema_def.fields]

    cache_dir = Path(rules_cache_dir)
    learner = AutonomousLearner(cfg, rules_cache_dir=cache_dir)

    golden_files = sorted(
        list(gt_dir.glob("*.xlsx")) + list(gt_dir.glob("*.xls"))
    )
    if not golden_files:
        typer.echo(f"Error: no golden files found in {gt_dir}", err=True)
        raise typer.Exit(1)

    summary: list[dict[str, object]] = []
    for gt_file in golden_files:
        input_file = _find_matching_input(gt_file, input_path)
        if input_file is None:
            summary.append(
                {
                    "golden_file": str(gt_file),
                    "status": "skipped_no_matching_input",
                }
            )
            continue

        dataset_out = output_path / gt_file.stem
        dataset_out.mkdir(parents=True, exist_ok=True)

        typer.echo(f"\n[learn-batch] Training on {input_file.name} vs {gt_file.name}")
        result = learner.run_learning_loop(
            input_file=input_file,
            golden_file=gt_file,
            schema_fields=schema_fields,
            max_iterations=max_iterations,
            target_accuracy=target_accuracy,
            min_improvement_delta=min_improvement_delta,
            use_cached_rules=use_cached_rules,
        )

        (dataset_out / "learning_result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        (dataset_out / "learned_rules.json").write_text(
            json.dumps(result.get("learned_rules", {}), indent=2), encoding="utf-8"
        )
        (dataset_out / "learn_run_analysis.json").write_text(
            json.dumps(result.get("learn_run_analysis", {}), indent=2),
            encoding="utf-8",
        )

        summary.append(
            {
                "golden_file": str(gt_file),
                "input_file": str(input_file),
                "status": "completed",
                "best_accuracy": result.get("best_accuracy", 0.0),
                "best_row_count_accuracy": result.get("best_row_count_accuracy", 0.0),
                "rules_count": len(result.get("learned_rules", {}).get("rules", [])),
                "target_reached": result.get("target_reached", False),
                "output_dir": str(dataset_out),
            }
        )

    batch_report = {
        "datasets": summary,
        "completed": sum(1 for s in summary if s.get("status") == "completed"),
        "skipped": sum(1 for s in summary if s.get("status") != "completed"),
    }
    report_path = output_path / "batch_learning_result.json"
    report_path.write_text(json.dumps(batch_report, indent=2), encoding="utf-8")
    typer.echo(f"\nBatch learning complete. Report: {report_path}")


if __name__ == "__main__":
    app()
