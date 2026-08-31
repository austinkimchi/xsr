#!/usr/bin/env python3
"""Condense recovery experiment reports without copying training histories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def compact_candidate(item: dict) -> dict:
    return {
        key: item[key] for key in (
            "representation", "feature_count", "training_size", "objective", "temperature",
            "parameter_count", "estimated_int8_bpf_map_bytes", "aggregate",
        ) if key in item
    }


def compact_classification(result: dict) -> dict:
    """Keep scalar/per-class results; omit redundant ground-truth matrices."""
    return {key: result[key] for key in (
        "teacher_agreement", "accuracy", "macro_f1", "per_class_recall",
        "prediction_distribution",
    ) if key in result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    diagnostics = load(args.directory / "diagnostics.json")
    oracle = load(args.directory / "linear_diagnostic.json")
    objectives = load(args.directory / "objectives.json")
    learning = load(args.directory / "learning_curve.json")
    features = load(args.directory / "features.json")
    nonlinear = load(args.directory / "nonlinear_h32.json")
    transfer = load(args.directory / "transfer_manifest_summary.json")

    baseline = {}
    for split, result in diagnostics["splits"].items():
        baseline[split] = {
            "samples": result["samples"],
            "student": compact_classification(result["student"]),
            "teacher_ground_truth": compact_classification(result["teacher_ground_truth"]),
            "student_teacher_confusion": result["student_teacher_confusion"],
            "agreement_by_teacher_class": result["agreement_by_teacher_class"],
            "teacher_confidence": result["teacher_confidence"],
            "teacher_top1_margin": result["teacher_top1_margin"],
            "dominant_confusion_pairs": result["dominant_confusion_pairs"][:10],
        }

    report = {
        "experiment": "intent-distillation recovery comparison",
        "canonical_deployment_untouched": diagnostics["deployment_untouched"],
        "prohibited_final_evaluators_or_benchmarks_run": False,
        "baseline_diagnostics": baseline,
        "bottleneck_classification": {
            "finding": "transfer/generalization and surface-feature fidelity",
            "evidence": [
                "The canonical 8K student has high training teacher agreement but low validation/development agreement.",
                "The collision-free observed-training-trigram oracle does not beat hashed 8K/16K development agreement.",
                "Teacher-top1 CE reaches 100% training agreement but only about 67% development agreement.",
                "Expanding transfer training from 4,900 to 11,938 rows reaches about 68% development agreement.",
                "Mixed byte/word linear features at 32K improve to about 74%, while the H=32 nonlinear byte-trigram fallback remains about 69%.",
            ],
        },
        "unhashed_and_width_diagnostic": {
            "exact_oracle_definition": oracle["exact_oracle"],
            "candidates": [compact_candidate(item) for item in oracle["configurations"]],
        },
        "teacher_fidelity_objectives": [
            compact_candidate(item) for item in objectives["configurations"]
        ],
        "transfer_expansion": {
            "manifest": transfer,
            "learning_curve": [compact_candidate(item) for item in learning["configurations"]],
        },
        "richer_linear_features": [
            compact_candidate(item) for item in features["configurations"]
        ],
        "nonlinear_fallback": {
            key: nonlinear[key] for key in (
                "representation", "architecture", "objective", "parameter_count",
                "estimated_int8_state_bytes", "quantization_note", "aggregate",
            )
        },
        "decision": {
            "best_exploratory_candidate": "mixed byte trigrams + word unigrams + word bigrams, shared 32K hash, linear teacher-top1 CE",
            "best_development_teacher_agreement_mean": 0.7385811467444121,
            "best_development_teacher_agreement_std": 0.013146500737092984,
            "deployment_update_justified": False,
            "reason": "The best candidate remains below the requested 80% quality/state trade-off band and far below the approximately 90% update threshold.",
            "recommendation": "Keep the sealed canonical 8K deployment unchanged; treat the remaining gap as a datapath surface-feature fidelity limitation.",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()
