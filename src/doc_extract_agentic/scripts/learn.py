"""CLI: Autonomous learning-based extraction with rule discovery."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer

from ..autonomous_learner import AutonomousLearner
from ..config import load_config, load_schema

app = typer.Typer(help="Autonomous learning-based document extraction")


def _discover_excel_files(root_dir: Path, recursive: bool) -> list[Path]:
    patterns = ("*.xlsx", "*.xls")
    if recursive:
        files: list[Path] = []
        for pattern in patterns:
            files.extend(root_dir.rglob(pattern))
        return sorted(files)

    files = []
    for pattern in patterns:
        files.extend(root_dir.glob(pattern))
    return sorted(files)


def _build_target_output_dir(
    base_output_dir: Path, target_file: Path, target_root: Path
) -> Path:
    rel = target_file.relative_to(target_root)
    # Keep nested structure and use file stem as the terminal output directory.
    return base_output_dir / rel.parent / rel.stem


def _tokenize_path_text(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _relative_stem(path: Path) -> str:
    no_suffix = path.with_suffix("")
    return str(no_suffix).replace("\\", "/").lower()


def _score_source_candidate(
    target_path: Path,
    target_root: Path,
    source_path: Path,
    source_root: Path,
) -> int:
    target_rel = target_path.relative_to(target_root)
    source_rel = source_path.relative_to(source_root)

    score = 0

    target_stem = target_rel.stem.lower()
    source_stem = source_rel.stem.lower()

    if source_rel == target_rel:
        score += 1000
    elif _relative_stem(source_rel) == _relative_stem(target_rel):
        score += 950

    if source_stem == target_stem:
        score += 300
    elif target_stem in source_stem or source_stem in target_stem:
        score += 120

    target_parts = [p.lower() for p in target_rel.parent.parts]
    source_parts = [p.lower() for p in source_rel.parent.parts]
    suffix_matches = 0
    for t, s in zip(reversed(target_parts), reversed(source_parts)):
        if t != s:
            break
        suffix_matches += 1
    score += suffix_matches * 80

    target_tokens = _tokenize_path_text(str(target_rel))
    source_tokens = _tokenize_path_text(str(source_rel))
    score += min(60, len(target_tokens & source_tokens) * 3)

    if source_path.suffix.lower() == target_path.suffix.lower():
        score += 10

    score -= abs(len(source_parts) - len(target_parts)) * 5
    return score


def _find_matching_input_from_files(
    target_path: Path,
    target_root: Path,
    source_root: Path,
    source_files: list[Path],
    *,
    min_score: int = 120,
) -> tuple[Path | None, dict[str, object]]:
    if not source_files:
        return None, {"reason": "no_source_candidates"}

    scored: list[tuple[int, Path]] = [
        (_score_source_candidate(target_path, target_root, source, source_root), source)
        for source in source_files
    ]
    scored.sort(key=lambda item: (item[0], str(item[1])), reverse=True)

    best_score, best_path = scored[0]
    if best_score < min_score:
        return None, {
            "reason": "no_high_confidence_match",
            "best_score": best_score,
            "candidate_preview": [
                {"source_file": str(path), "score": score} for score, path in scored[:3]
            ],
        }

    tied_best = [path for score, path in scored if score == best_score]
    if len(tied_best) > 1:
        return None, {
            "reason": "ambiguous_best_match",
            "best_score": best_score,
            "candidate_preview": [
                {"source_file": str(path), "score": best_score}
                for path in tied_best[:5]
            ],
        }

    return best_path, {
        "reason": "matched",
        "score": best_score,
    }


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
        "source",
        "--input-dir",
        "--source-dir",
        help="Directory containing source/input Excel files",
    ),
    ground_truth_dir: str = typer.Option(
        "target",
        "--ground-truth-dir",
        "--target-dir",
        help="Directory with target/golden Excel files",
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
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help="Recursively scan source/target directories for Excel files",
    ),
    allow_source_reuse: bool = typer.Option(
        False,
        "--allow-source-reuse/--no-source-reuse",
        help="Allow one source file to match multiple target files",
    ),
    min_match_score: int = typer.Option(
        120,
        "--min-match-score",
        min=0,
        help="Minimum confidence score required for source-target pairing",
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

    source_files = _discover_excel_files(input_path, recursive=recursive)
    target_files = _discover_excel_files(gt_dir, recursive=recursive)

    if not source_files:
        typer.echo(f"Error: no source files found in {input_path}", err=True)
        raise typer.Exit(1)

    if not target_files:
        typer.echo(f"Error: no golden files found in {gt_dir}", err=True)
        raise typer.Exit(1)

    typer.echo(
        f"[learn-batch] Found {len(source_files)} source files and "
        f"{len(target_files)} target files"
    )

    summary: list[dict[str, object]] = []
    remaining_source_files = list(source_files)

    for gt_file in target_files:
        input_file, match_meta = _find_matching_input_from_files(
            gt_file,
            gt_dir,
            input_path,
            remaining_source_files if not allow_source_reuse else source_files,
            min_score=min_match_score,
        )

        if input_file is None:
            summary.append(
                {
                    "target_file": str(gt_file),
                    "status": str(
                        match_meta.get("reason", "skipped_no_matching_input")
                    ),
                    "match_diagnostics": match_meta,
                }
            )
            continue

        if not allow_source_reuse:
            remaining_source_files = [
                p for p in remaining_source_files if p != input_file
            ]

        dataset_out = _build_target_output_dir(output_path, gt_file, gt_dir)
        dataset_out.mkdir(parents=True, exist_ok=True)

        typer.echo(
            f"\n[learn-batch] Training on {input_file.name} vs {gt_file.name} "
            f"(match score={match_meta.get('score', 'n/a')})"
        )
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
                "target_file": str(gt_file),
                "source_file": str(input_file),
                "status": "completed",
                "best_accuracy": result.get("best_accuracy", 0.0),
                "best_row_count_accuracy": result.get("best_row_count_accuracy", 0.0),
                "rules_count": len(result.get("learned_rules", {}).get("rules", [])),
                "target_reached": result.get("target_reached", False),
                "output_dir": str(dataset_out),
                "match_diagnostics": match_meta,
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
