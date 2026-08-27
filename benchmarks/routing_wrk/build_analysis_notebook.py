#!/usr/bin/env python3
"""Build the committed repeated-trial benchmark analysis notebook.

Keeping the notebook source here makes reviewable changes practical while the
checked-in notebook remains a normal, executable Jupyter artifact.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "results" / "wrk_benchmark_analysis.ipynb"


def markdown(source: str):
    return nbf.v4.new_markdown_cell(dedent(source).strip() + "\n")


def code(source: str):
    return nbf.v4.new_code_cell(dedent(source).strip() + "\n")


cells = [
    markdown("""
    # Repeated-trial routing benchmark analysis

    This notebook reads hardened `summary.json` and per-trial `result.json`
    artifacts. Primary paper figures include only four-path, valid saturation
    configurations at request concurrency 1–256. Concurrency 512 is retained
    separately as an overload diagnostic.
    """),
    markdown("""
    ## 1. Configuration and run discovery

    Set a run ID to make a paper build reproducible. `None` selects the newest
    compatible hardened run and prints all candidates before making the choice.
    """),
    code("""
    SATURATION_RUN_ID = None
    FIXED_RATE_RUN_ID = None

    PAPER_MAX_CONCURRENCY = 256
    STRESS_CONCURRENCY = 512
    FIXED_RATE_CONCURRENCY = None
    CENTRAL_STATISTIC = "mean"
    ERROR_STATISTIC = "ci95"

    from pathlib import Path
    import json
    import sys
    import warnings
    from collections import Counter

    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from matplotlib.ticker import FuncFormatter, FixedLocator

    def repository_root(start: Path) -> Path:
        for candidate in (start, *start.parents):
            if (candidate / "benchmarks" / "routing_wrk").is_dir() and (candidate / "results").is_dir():
                return candidate
        raise FileNotFoundError(
            "Could not find the repository root. Start from this repository or a child directory containing benchmarks/routing_wrk and results."
        )

    REPO_ROOT = repository_root(Path.cwd().resolve())
    sys.path.insert(0, str(REPO_ROOT / "benchmarks" / "routing_wrk"))
    from analysis_utils import (
        REQUIRED_SYSTEMS, diagnostic_rows, exclusion_reasons, flatten_summary,
        load_trial_records, paired_ratios, paper_valid_configurations, ratio_statistics,
    )

    RESULTS_ROOT = REPO_ROOT / "results" / "routing-performance"
    if not RESULTS_ROOT.is_dir():
        raise FileNotFoundError(f"Missing hardened result directory: {RESULTS_ROOT}")

    def candidates_for(mode):
        candidates = []
        for path in RESULTS_ROOT.glob("*/summary.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                warnings.warn(f"Skipping invalid JSON {path}: {error}")
                continue
            modes = {row.get("mode") for row in payload.get("results", [])}
            if mode in modes:
                candidates.append((path.stat().st_mtime, path.parent, payload))
        return sorted(candidates, reverse=True, key=lambda item: item[0])

    def select_run(mode, requested):
        candidates = candidates_for(mode)
        print(f"{mode} candidates:")
        for _, path, _ in candidates:
            print(f"  {path}")
        if requested is not None:
            path = RESULTS_ROOT / requested
            summary_path = path / "summary.json"
            if not summary_path.is_file():
                raise FileNotFoundError(f"Requested {mode} run is missing {summary_path}")
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if mode not in {row.get("mode") for row in payload.get("results", [])}:
                raise ValueError(f"Requested run {requested} does not contain {mode} results")
        elif candidates:
            _, path, payload = candidates[0]
        else:
            print(f"No {mode} summary.json is available; its figure will not be exported.")
            return None, None
        print(f"Selected {mode} run: {path}")
        return path, payload

    SATURATION_DIR, saturation_summary = select_run("saturation", SATURATION_RUN_ID)
    FIXED_RATE_DIR, fixed_rate_summary = select_run("fixed-rate", FIXED_RATE_RUN_ID)
    if SATURATION_DIR is None:
        raise FileNotFoundError("No saturation run is available; a saturation run is required for the paper figures.")
    """),
    markdown("## 2. Provenance"),
    code("""
    def metadata_for(summary, run_dir):
        metadata = summary.get("metadata") if summary else None
        if metadata is None:
            path = run_dir / "metadata.json"
            if not path.is_file():
                raise FileNotFoundError(f"Missing provenance metadata: {path}")
            metadata = json.loads(path.read_text(encoding="utf-8"))
        return metadata

    saturation_metadata = metadata_for(saturation_summary, SATURATION_DIR)
    fixed_rate_metadata = metadata_for(fixed_rate_summary, FIXED_RATE_DIR) if FIXED_RATE_DIR else None

    def provenance_row(run_id, metadata):
        benchmark = metadata.get("benchmark", {})
        workload = metadata.get("workload", {})
        docker = metadata.get("docker", {})
        xsr = metadata.get("xsr", {})
        return {
            "run_id": run_id,
            "xsr_commit": xsr.get("commit"), "xsr_dirty_state": xsr.get("working_tree"),
            "benchmark_mode": benchmark.get("mode"), "benchmark_profile": benchmark.get("profile"),
            "trial_count": benchmark.get("trial_count"), "duration": benchmark.get("duration"),
            "warmup": benchmark.get("warmup_duration"),
            "policy_sha256": workload.get("policy_sha256"),
            "prompt_corpus_sha256": (workload.get("prompts") or {}).get("sha256"),
            "vsr_image": (docker.get("vsr") or {}).get("image_id"),
            "envoy_image": (docker.get("envoy") or {}).get("image_id"),
            "tool": (benchmark.get("wrk2") or {}).get("path") or (benchmark.get("wrk") or {}).get("path"),
            "routing_mode": xsr.get("routing_mode"),
        }

    provenance = pd.DataFrame([provenance_row(SATURATION_DIR.name, saturation_metadata)] + (
        [provenance_row(FIXED_RATE_DIR.name, fixed_rate_metadata)] if FIXED_RATE_DIR else []
    ))
    display(provenance.T)
    if len(provenance) == 2:
        checked = ["xsr_commit", "policy_sha256", "prompt_corpus_sha256", "vsr_image", "envoy_image"]
        mismatches = [field for field in checked if provenance[field].nunique(dropna=False) > 1]
        if mismatches:
            warnings.warn("Selected saturation and fixed-rate runs have different provenance: " + ", ".join(mismatches))
    """),
    markdown("## 3. Data loading and schema validation"),
    code("""
    def load_run(run_dir, summary, expected_mode):
        needed = {"metadata", "results"}
        missing = needed - set(summary)
        if missing:
            raise ValueError(f"{run_dir / 'summary.json'} is missing keys: {sorted(missing)}")
        aggregate_rows = flatten_summary(summary, run_dir.name)
        if not aggregate_rows:
            raise ValueError(f"{run_dir / 'summary.json'} has no usable aggregate metrics")
        trials = load_trial_records(run_dir, run_dir.name)
        found_systems = {row.get("system") for row in trials}
        unknown = found_systems - set(REQUIRED_SYSTEMS)
        if unknown:
            warnings.warn(f"Run {run_dir.name} includes additional systems: {sorted(unknown)}")
        missing_systems = set(REQUIRED_SYSTEMS) - found_systems
        if missing_systems:
            warnings.warn(f"Run {run_dir.name} is missing expected systems: {sorted(missing_systems)}")
        return pd.DataFrame(aggregate_rows), pd.DataFrame(trials)

    saturation_results, saturation_trials = load_run(SATURATION_DIR, saturation_summary, "saturation")
    if FIXED_RATE_DIR:
        fixed_rate_results, fixed_rate_trials = load_run(FIXED_RATE_DIR, fixed_rate_summary, "fixed-rate")
    else:
        fixed_rate_results, fixed_rate_trials = pd.DataFrame(), pd.DataFrame()
    all_results = pd.concat([saturation_results, fixed_rate_results], ignore_index=True)
    all_trials = pd.concat([saturation_trials, fixed_rate_trials], ignore_index=True)
    print(f"Aggregate rows: {len(all_results)}; trial records (including invalid): {len(all_trials)}")
    print("Observed tool and topology by system:")
    display(all_trials[["run_id", "system", "tool", "topology"]].drop_duplicates().sort_values(["run_id", "system"]))
    display(all_results.head())
    """),
    markdown("## 4. Trial-validity summary"),
    code("""
    saturation_trial_count = int((saturation_metadata.get("benchmark") or {}).get("trial_count", 0))
    if saturation_trial_count <= 0:
        raise ValueError("metadata.benchmark.trial_count must be a positive integer")
    saturation_exclusions = exclusion_reasons(
        saturation_results.to_dict("records"), saturation_trial_count, paper_max_concurrency=PAPER_MAX_CONCURRENCY,
        required_metrics=("throughput_rps", "average_latency_us"),
    )
    paper_configurations = paper_valid_configurations(
        saturation_results.to_dict("records"), saturation_trial_count, paper_max_concurrency=PAPER_MAX_CONCURRENCY,
        required_metrics=("throughput_rps", "average_latency_us"),
    )
    paper_valid_results = saturation_results[saturation_results.configuration.isin(paper_configurations)].copy()
    diagnostic_results = saturation_results[saturation_results.concurrency.eq(STRESS_CONCURRENCY)].copy()
    paper_concurrencies = sorted(paper_valid_results.concurrency.unique())
    if not paper_concurrencies:
        raise ValueError("No fully valid saturation configuration remains for paper figures")
    validity_summary = saturation_results[saturation_results.metric.eq("throughput_rps")].copy()
    validity_summary["paper_valid"] = validity_summary.configuration.isin(paper_configurations)
    validity_summary["exclusion_reason"] = validity_summary.configuration.map(
        lambda name: "; ".join(saturation_exclusions.get(name, []))
    )
    display(validity_summary.sort_values(["concurrency", "system"]))
    excluded_configurations = pd.DataFrame([
        {"configuration": name, "reason": reason}
        for name, reasons in saturation_exclusions.items() for reason in reasons
    ])
    print("Excluded configurations:")
    display(excluded_configurations if not excluded_configurations.empty else pd.DataFrame([{"configuration": "None", "reason": "No exclusions"}]))
    print(f"Paper maximum is {PAPER_MAX_CONCURRENCY}; the fully valid comparison currently ends at {max(paper_concurrencies)}. c={STRESS_CONCURRENCY} is diagnostic-only.")
    """),
    markdown("## 5. Saturation throughput"),
    code("""
    SYSTEM_STYLE = {
        "Direct backend": {"color": "#707070", "marker": "o", "linestyle": "-"},
        "Envoy only": {"color": "#2a9d8f", "marker": "s", "linestyle": "--"},
        "XSR (SK_SKB/SOCKMAP)": {"color": "#2878b5", "marker": "^", "linestyle": "-"},
        "VSR (Envoy ExtProc)": {"color": "#e68613", "marker": "D", "linestyle": ":"},
    }
    plt.rcParams.update({
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "font.size": 9.5, "axes.labelsize": 10, "axes.titlesize": 11,
        "legend.fontsize": 9, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    OUTPUT_RUN_ID = SATURATION_DIR.name if FIXED_RATE_DIR is None else f"{SATURATION_DIR.name}__{FIXED_RATE_DIR.name}"
    EXPORT_DIR = REPO_ROOT / "results" / "charts" / OUTPUT_RUN_ID
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    def export_figure(figure, stem):
        figure.savefig(EXPORT_DIR / f"{stem}.pdf", bbox_inches="tight")
        figure.savefig(EXPORT_DIR / f"{stem}.png", dpi=300, bbox_inches="tight")
        plt.show()
        plt.close(figure)

    saturation_throughput = paper_valid_results[paper_valid_results.metric.eq("throughput_rps")].copy()
    throughput_ticks = sorted(saturation_throughput.concurrency.unique())
    throughput_positions = np.arange(len(throughput_ticks))
    SATURATION_THROUGHPUT_WIDTH = 7.0
    fig, ax = plt.subplots(figsize=(SATURATION_THROUGHPUT_WIDTH, 3.75))
    for system in REQUIRED_SYSTEMS:
        frame = saturation_throughput[saturation_throughput.system.eq(system)].sort_values("concurrency")
        style = SYSTEM_STYLE[system]
        positions = [throughput_ticks.index(value) for value in frame.concurrency]
        ax.errorbar(positions, frame[CENTRAL_STATISTIC], yerr=frame[ERROR_STATISTIC], label=system,
                    color=style["color"], marker=style["marker"], linestyle=style["linestyle"],
                    linewidth=1.7, markersize=5, capsize=2.5, capthick=0.9)
    ax.set_xticks(throughput_positions, [str(value) for value in throughput_ticks])
    ax.set_xlabel("Request concurrency"); ax.set_ylabel("Throughput (requests/s)")
    ax.set_yscale("log")
    ax.margins(x=0.025)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False, columnspacing=1.6)
    # Keep the logarithmic scale readable without letting its dense minor grid
    # compete with the series and confidence intervals.
    ax.grid(False, axis="both", which="both")
    ax.grid(axis="y", which="major", color="#d9dee7", linewidth=0.75)
    ax.set_axisbelow(True); fig.tight_layout()
    export_figure(fig, "saturation_throughput")
    saturation_throughput.to_csv(EXPORT_DIR / "plotted_saturation_data.csv", index=False)

    # Linear-scale alternative: two stacked panels prevent the direct path from
    # visually flattening the routing paths while keeping each panel honest at zero.
    facet_groups = [
        ("Infrastructure paths", ("Direct backend", "Envoy only")),
        ("Routing paths", ("XSR (SK_SKB/SOCKMAP)", "VSR (Envoy ExtProc)")),
    ]
    SATURATION_THROUGHPUT_FACETED_WIDTH = 7.0
    fig, axes = plt.subplots(2, 1, figsize=(SATURATION_THROUGHPUT_FACETED_WIDTH, 5.45), sharex=True)
    for axis, (panel_label, panel_systems) in zip(axes, facet_groups):
        for system in panel_systems:
            frame = saturation_throughput[saturation_throughput.system.eq(system)].sort_values("concurrency")
            style = SYSTEM_STYLE[system]
            positions = [throughput_ticks.index(value) for value in frame.concurrency]
            lower_error = np.minimum(frame[ERROR_STATISTIC].to_numpy(), frame[CENTRAL_STATISTIC].to_numpy())
            upper_error = frame[ERROR_STATISTIC].to_numpy()
            axis.errorbar(positions, frame[CENTRAL_STATISTIC], yerr=np.vstack([lower_error, upper_error]), label=system,
                          color=style["color"], marker=style["marker"], linestyle=style["linestyle"],
                          linewidth=1.7, markersize=4.8, capsize=2.5, capthick=0.9)
        axis.set_ylim(bottom=0)
        axis.set_ylabel("Throughput (requests/s)")
        axis.text(0.01, 0.92, panel_label, transform=axis.transAxes, fontsize=9, weight="semibold", va="top")
        axis.grid(axis="y", color="#d9dee7", linewidth=0.8)
        axis.set_axisbelow(True); axis.margins(x=0.025)
    axes[1].set_xticks(throughput_positions, [str(value) for value in throughput_ticks])
    axes[1].set_xlabel("Request concurrency")
    facet_handles, facet_labels = [], []
    for axis in axes:
        handles, labels = axis.get_legend_handles_labels()
        facet_handles.extend(handles); facet_labels.extend(labels)
    fig.legend(facet_handles, facet_labels, loc="upper center", bbox_to_anchor=(0.5, 1.0),
               ncol=2, frameon=False, columnspacing=1.6)
    fig.tight_layout(rect=(0, 0, 1, 0.90), h_pad=1.1)
    export_figure(fig, "saturation_throughput_faceted")

    saturation_latency = paper_valid_results[paper_valid_results.metric.isin(["average_latency_us", "p50_latency_us", "p95_latency_us", "p99_latency_us"])].copy()
    latency_panels = [("Average", "average_latency_us"), ("P50", "p50_latency_us"), ("P95", "p95_latency_us"), ("P99", "p99_latency_us")]
    emphasized_systems = ("XSR (SK_SKB/SOCKMAP)", "VSR (Envoy ExtProc)")
    SATURATION_LATENCY_WIDTH = 7.0
    fig, axes = plt.subplots(2, 2, figsize=(SATURATION_LATENCY_WIDTH, 5.8), sharex=True, sharey=True)
    for axis, (panel_label, metric) in zip(axes.flat, latency_panels):
        for system in emphasized_systems:
            frame = saturation_latency[(saturation_latency.metric == metric) & (saturation_latency.system == system)].sort_values("concurrency")
            style = SYSTEM_STYLE[system]
            positions = [throughput_ticks.index(value) for value in frame.concurrency]
            axis.errorbar(positions, frame[CENTRAL_STATISTIC], yerr=frame[ERROR_STATISTIC], label=system,
                          color=style["color"], marker="o", linestyle=style["linestyle"],
                          linewidth=1.8, markersize=4.5, capsize=2.2, capthick=0.8)
        axis.set_title(panel_label, pad=6)
        axis.set_yscale("log")
        axis.grid(which="major", color="#d9e1ec", linewidth=0.8)
        axis.grid(which="minor", color="#eef2f6", linewidth=0.45)
        axis.set_axisbelow(True)
        axis.margins(x=0.025)
    for axis in axes[:, 0]: axis.set_ylabel("Latency (ms)")
    for axis in axes[1, :]:
        axis.set_xticks(throughput_positions, [str(value) for value in throughput_ticks], rotation=0)
        axis.set_xlabel("Request concurrency")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=2.0, w_pad=1.5)
    export_figure(fig, "saturation_latency")
    saturation_latency[saturation_latency.system.isin(emphasized_systems)].to_csv(EXPORT_DIR / "plotted_saturation_latency_data.csv", index=False)
    """),
    markdown("## 6. Fixed-rate latency"),
    code("""
    plotted_fixed_rate_data = pd.DataFrame()
    if FIXED_RATE_DIR is not None:
        fixed_trial_count = int((fixed_rate_metadata.get("benchmark") or {}).get("trial_count", 0))
        fixed_metrics = ("average_latency_us", "p50_latency_us", "p95_latency_us", "p99_latency_us")
        fixed_exclusions = exclusion_reasons(fixed_rate_results.to_dict("records"), fixed_trial_count, paper_max_concurrency=PAPER_MAX_CONCURRENCY, required_metrics=fixed_metrics)
        fixed_valid_configurations = paper_valid_configurations(fixed_rate_results.to_dict("records"), fixed_trial_count, paper_max_concurrency=PAPER_MAX_CONCURRENCY, required_metrics=fixed_metrics)
        available_concurrency = sorted(fixed_rate_results.concurrency.dropna().unique())
        if FIXED_RATE_CONCURRENCY is None and len(available_concurrency) != 1:
            raise ValueError("Fixed-rate data has multiple connection concurrencies; set FIXED_RATE_CONCURRENCY or generate separate figures.")
        selected_fixed_concurrency = FIXED_RATE_CONCURRENCY if FIXED_RATE_CONCURRENCY is not None else available_concurrency[0]
        plotted_fixed_rate_data = fixed_rate_results[
            fixed_rate_results.configuration.isin(fixed_valid_configurations)
            & fixed_rate_results.concurrency.eq(selected_fixed_concurrency)
            & fixed_rate_results.metric.isin(["average_latency_us", "p50_latency_us", "p95_latency_us", "p99_latency_us"])
        ].copy()
        fixed_rate_ticks = sorted(plotted_fixed_rate_data.offered_rate_rps.unique())
        fixed_rate_positions = np.arange(len(fixed_rate_ticks))
        fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.8), sharex=True, sharey=True)
        for axis, (label, metric) in zip(axes.flat, [("Average", "average_latency_us"), ("P50", "p50_latency_us"), ("P95", "p95_latency_us"), ("P99", "p99_latency_us")]):
            for system in emphasized_systems:
                frame = plotted_fixed_rate_data[(plotted_fixed_rate_data.metric == metric) & (plotted_fixed_rate_data.system == system)].sort_values("offered_rate_rps")
                style = SYSTEM_STYLE[system]
                positions = [fixed_rate_ticks.index(value) for value in frame.offered_rate_rps]
                axis.errorbar(positions, frame[CENTRAL_STATISTIC], yerr=frame[ERROR_STATISTIC], label=system,
                              color=style["color"], marker="o", linestyle=style["linestyle"],
                              linewidth=1.8, markersize=4.5, capsize=2.2, capthick=0.8)
            axis.set_title(label, pad=6); axis.set_yscale("log")
            axis.grid(which="major", color="#d9e1ec", linewidth=0.8)
            axis.grid(which="minor", color="#eef2f6", linewidth=0.45)
            axis.set_axisbelow(True); axis.margins(x=0.025)
        for axis in axes[:, 0]: axis.set_ylabel("Latency (ms)")
        for axis in axes[1, :]:
            axis.set_xticks(fixed_rate_positions, [str(value) for value in fixed_rate_ticks])
            axis.set_xlabel("Offered request rate (requests/s)")
        handles, labels = axes[0, 0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
        fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=2.0, w_pad=1.5)
        export_figure(fig, "fixed_rate_latency")
        plotted_fixed_rate_data.to_csv(EXPORT_DIR / "plotted_fixed_rate_data.csv", index=False)
    else:
        print("Fixed-rate figure not generated: no fixed-rate hardened run is available.")
    """),
    markdown("## 7. Routing-path overhead decomposition"),
    code("""
    highest_common_concurrency = max(saturation_results[saturation_results.configuration.isin(paper_configurations)].concurrency)
    decomposition_configuration = f"concurrency-{highest_common_concurrency}"
    paired = []
    for numerator, denominator, metric in [
        ("Envoy only", "Direct backend", "throughput_rps"),
        ("XSR (SK_SKB/SOCKMAP)", "Direct backend", "throughput_rps"),
        ("VSR (Envoy ExtProc)", "Direct backend", "throughput_rps"),
        ("Envoy only", "Direct backend", "average_latency_us"),
        ("XSR (SK_SKB/SOCKMAP)", "Direct backend", "average_latency_us"),
        ("VSR (Envoy ExtProc)", "Direct backend", "average_latency_us"),
        ("XSR (SK_SKB/SOCKMAP)", "VSR (Envoy ExtProc)", "throughput_rps"),
        ("VSR (Envoy ExtProc)", "XSR (SK_SKB/SOCKMAP)", "average_latency_us"),
        ("VSR (Envoy ExtProc)", "Envoy only", "average_latency_us"),
    ]:
        paired.extend(paired_ratios(saturation_trials.to_dict("records"), numerator, denominator, metric, paper_configurations))
    paired_trial_ratios = pd.DataFrame(paired)
    paired_comparisons = pd.DataFrame(ratio_statistics(paired))
    systems = list(REQUIRED_SYSTEMS)

    # Ratios are positive and span orders of magnitude. A geometric-mean interval
    # on a log axis preserves that structure without compressing XSR and VSR into
    # nearly invisible linear-scale bars.
    decomposition_interval_rows = []
    for metric in ("throughput_rps", "average_latency_us"):
        for system in systems:
            if system == "Direct backend":
                center = lower = upper = 1.0
                count = saturation_trial_count
            else:
                values = paired_trial_ratios[
                    paired_trial_ratios.configuration.eq(decomposition_configuration)
                    & paired_trial_ratios.metric.eq(metric)
                    & paired_trial_ratios.numerator.eq(system)
                    & paired_trial_ratios.denominator.eq("Direct backend")
                ].ratio.astype(float)
                if values.empty:
                    raise ValueError(f"No paired {metric} ratios for {system} at {decomposition_configuration}")
                logs = np.log(values.to_numpy())
                log_center = float(logs.mean())
                log_half_width = 1.96 * float(logs.std(ddof=1)) / np.sqrt(len(logs)) if len(logs) > 1 else 0.0
                center = float(np.exp(log_center))
                lower = float(np.exp(log_center - log_half_width))
                upper = float(np.exp(log_center + log_half_width))
                count = len(values)
            decomposition_interval_rows.append({
                "configuration": decomposition_configuration, "system": system, "metric": metric,
                "geometric_mean": center, "ci95_lower": lower, "ci95_upper": upper,
                "paired_trial_count": count,
            })
    decomposition_intervals = pd.DataFrame(decomposition_interval_rows)

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.55), sharey=True)
    y_positions = np.arange(len(systems))
    for axis, metric, panel_label in [
        (axes[0], "throughput_rps", "Throughput retained"),
        (axes[1], "average_latency_us", "Average-latency overhead"),
    ]:
        frame = decomposition_intervals[decomposition_intervals.metric.eq(metric)].set_index("system").loc[systems].reset_index()
        centers = frame.geometric_mean.to_numpy()
        lower_errors = centers - frame.ci95_lower.to_numpy()
        upper_errors = frame.ci95_upper.to_numpy() - centers
        axis.errorbar(centers, y_positions, xerr=np.vstack([lower_errors, upper_errors]), fmt="none",
                      ecolor="#444444", elinewidth=1.1, capsize=3, zorder=2)
        for y, system, value in zip(y_positions, systems, centers):
            style = SYSTEM_STYLE[system]
            axis.scatter(value, y, s=48, color=style["color"], marker=style["marker"],
                         edgecolor="white", linewidth=0.55, zorder=3)
            value_label = f"{value * 100:.3g}%" if metric == "throughput_rps" else f"{value:.1f}×"
            axis.annotate(value_label, (value, y), xytext=(7, 0), textcoords="offset points",
                          va="center", ha="left", fontsize=8,
                          bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 0.5})
        axis.set_xscale("log")
        axis.axvline(1.0, color="#7a7a7a", linestyle="--", linewidth=0.9, zorder=1)
        axis.set_title(panel_label, pad=8)
        axis.grid(axis="x", which="major", color="#d9dee7", linewidth=0.8)
        axis.grid(axis="x", which="minor", color="#eef1f5", linewidth=0.45)
        axis.set_axisbelow(True)
    axes[0].set_yticks(y_positions, systems)
    axes[0].invert_yaxis()
    axes[0].set_xlim(5e-7, 1.8)
    axes[0].xaxis.set_major_locator(FixedLocator([1e-6, 1e-4, 1e-2, 1.0]))
    axes[0].xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value * 100:g}%"))
    axes[0].set_xlabel("Relative to direct backend (log scale)")
    axes[1].set_xlim(0.7, 1500)
    axes[1].xaxis.set_major_locator(FixedLocator([1, 10, 100, 1000]))
    axes[1].xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}×"))
    axes[1].set_xlabel("Relative to direct backend (log scale)")
    fig.tight_layout(w_pad=2.0); export_figure(fig, "routing_path_decomposition")
    decomposition_intervals.to_csv(EXPORT_DIR / "routing_path_decomposition_ratio_data.csv", index=False)
    saturation_results[(saturation_results.configuration == decomposition_configuration) & saturation_results.metric.isin(["throughput_rps", "average_latency_us"])].to_csv(
        EXPORT_DIR / "routing_path_decomposition_data.csv", index=False
    )
    """),
    markdown("## 8. Concurrency-512 overload diagnostic"),
    code("""
    diagnostic_trial_rows = pd.DataFrame(diagnostic_rows(SATURATION_DIR, saturation_trials.to_dict("records"), STRESS_CONCURRENCY))
    if diagnostic_trial_rows.empty:
        print(f"No raw c={STRESS_CONCURRENCY} files were available for the diagnostic.")
    else:
        diagnostic_trial_rows["failure_reason"] = diagnostic_trial_rows.failure_reasons.apply(lambda reasons: "; ".join(reasons) if reasons else "valid")
        diagnostic_rows_by_system = []
        for system in REQUIRED_SYSTEMS:
            frame = diagnostic_trial_rows[diagnostic_trial_rows.system.eq(system)]
            valid_trials = int(frame.valid.sum()) if not frame.empty else 0
            raw_reasons = [reason for reasons in frame.failure_reasons for reason in reasons]
            diagnostic_rows_by_system.append({
                "system": system, "valid_trials": valid_trials,
                "failed_trials": saturation_trial_count - valid_trials,
                "recorded_invalid_trials": int((~frame.valid).sum()) if not frame.empty else 0,
                "missing_raw_trial_records": max(0, saturation_trial_count - len(frame)),
                "main_failure_reason": Counter(raw_reasons).most_common(1)[0][0] if raw_reasons else ("missing raw trial records" if len(frame) < saturation_trial_count else "valid"),
                "throughput_rps": frame.throughput_rps.mean(), "average_latency_ms": frame.average_latency_ms.mean(),
                "maximum_latency_ms": frame.maximum_latency_ms.max(), "timeout_count": frame.timeout_count.sum(),
                "non_success_count": frame.non_success_count.sum(), "estimated_inflight_requests": frame.estimated_inflight_requests.mean(),
                "raw_file_paths": "\\n".join(frame.raw_file_path.dropna()),
            })
        diagnostic_summary = pd.DataFrame(diagnostic_rows_by_system)
        diagnostic_summary.to_csv(EXPORT_DIR / "overload_c512_table.csv", index=False)
        diagnostic_trial_rows.to_csv(EXPORT_DIR / "overload_c512_trial_records.csv", index=False)
        display(diagnostic_summary)
        diagnostic_labels = {"Direct backend": "Direct", "Envoy only": "Envoy", "XSR (SK_SKB/SOCKMAP)": "XSR", "VSR (Envoy ExtProc)": "VSR"}
        fig, axes = plt.subplots(1, 2, figsize=(6.8, 4.0))
        positions = range(len(diagnostic_summary))
        axes[0].bar(positions, diagnostic_summary.valid_trials, label="valid", color="#5b8e7d")
        axes[0].bar(positions, diagnostic_summary.failed_trials, bottom=diagnostic_summary.valid_trials, label="invalid", color="white", edgecolor="#a33", hatch="//")
        axes[0].set_xticks(positions, [diagnostic_labels[system] for system in diagnostic_summary.system]); axes[0].set_ylabel("Trial count"); axes[0].legend(frameon=False, loc="upper center"); axes[0].grid(axis="y", alpha=0.25)
        for index, row in diagnostic_summary.reset_index(drop=True).iterrows():
            label = "" if pd.isna(row.throughput_rps) else f"{row.throughput_rps:.0f} rps\\n{row.average_latency_ms:.1f} ms"
            axes[1].scatter(index, row.throughput_rps, facecolors="none", edgecolors=SYSTEM_STYLE[row.system]["color"], marker=SYSTEM_STYLE[row.system]["marker"], s=80)
            axes[1].annotate(label, (index, row.throughput_rps), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=8)
        axes[1].set_xticks(positions, [diagnostic_labels[system] for system in diagnostic_summary.system]); axes[1].set_ylabel("Diagnostic throughput (requests/s)"); axes[1].set_yscale("log"); axes[1].grid(axis="y", alpha=0.25)
        fig.subplots_adjust(bottom=0.22, wspace=0.65); export_figure(fig, "overload_c512_diagnostic")
        vsr = diagnostic_summary[diagnostic_summary.system.eq("VSR (Envoy ExtProc)")]
        if not vsr.empty and vsr.iloc[0].estimated_inflight_requests == vsr.iloc[0].estimated_inflight_requests:
            print(f"VSR c={STRESS_CONCURRENCY} diagnostic: L ≈ λW = {vsr.iloc[0].estimated_inflight_requests:.1f} estimated in-flight requests.")
        print("Diagnostic labels remain path-specific: VSR timeout data indicates queueing overload/client timeout; Envoy-only non-success counts indicate HTTP response failures.")
    """),
    markdown("## 9. Paired speedups and paper statistics"),
    code("""
    def ratio_range(numerator, denominator, metric):
        frame = paired_comparisons[(paired_comparisons.numerator == numerator) & (paired_comparisons.denominator == denominator) & (paired_comparisons.metric == metric)]
        return {"minimum": float(frame["mean"].min()), "maximum": float(frame["mean"].max())} if not frame.empty else None

    def aggregate_at(configuration, system, metric):
        frame = saturation_results[(saturation_results.configuration == configuration) & (saturation_results.system == system) & (saturation_results.metric == metric)]
        return float(frame.iloc[0][CENTRAL_STATISTIC]) if not frame.empty else None

    headline_metrics = {
        "primary_domain": {"tested_request_concurrencies": [int(value) for value in paper_concurrencies]},
        "peak_xsr_throughput_rps": float(saturation_throughput[saturation_throughput.system.eq("XSR (SK_SKB/SOCKMAP)")][CENTRAL_STATISTIC].max()),
        "xsr_vsr_paired_throughput_speedup_range": ratio_range("XSR (SK_SKB/SOCKMAP)", "VSR (Envoy ExtProc)", "throughput_rps"),
        "xsr_vsr_paired_average_latency_improvement_range": ratio_range("VSR (Envoy ExtProc)", "XSR (SK_SKB/SOCKMAP)", "average_latency_us"),
        "xsr_throughput_retained_relative_to_direct": ratio_range("XSR (SK_SKB/SOCKMAP)", "Direct backend", "throughput_rps"),
        "envoy_only_average_latency_overhead_relative_to_direct": ratio_range("Envoy only", "Direct backend", "average_latency_us"),
        "vsr_average_latency_overhead_relative_to_envoy_only": ratio_range("VSR (Envoy ExtProc)", "Envoy only", "average_latency_us"),
        "highest_valid_common_concurrency": int(highest_common_concurrency),
        "excluded_configurations": saturation_exclusions,
        "selected_run_ids": {"saturation": SATURATION_DIR.name, "fixed_rate": FIXED_RATE_DIR.name if FIXED_RATE_DIR else None},
        "provenance": provenance.to_dict("records"),
    }
    print(json.dumps(headline_metrics, indent=2))
    """),
    markdown("## 10. Export"),
    code("""
    validity_summary.to_csv(EXPORT_DIR / "validity_summary.csv", index=False)
    paired_comparisons.to_csv(EXPORT_DIR / "paired_comparisons.csv", index=False)
    (EXPORT_DIR / "paper_metrics.json").write_text(json.dumps(headline_metrics, indent=2) + "\\n", encoding="utf-8")
    summary_lines = [
        "# Routing benchmark paper summary", "",
        "Primary comparative figures include only fully valid tested request concurrencies: " + ", ".join(str(int(value)) for value in paper_concurrencies) + ".",
        f"Concurrency {STRESS_CONCURRENCY} is reported separately because at least one comparison path did not complete the required valid trials.", "",
        f"- Highest fully valid common concurrency: {highest_common_concurrency}",
        f"- Peak XSR throughput: {headline_metrics['peak_xsr_throughput_rps']:.2f} requests/s",
        f"- Saturation run: `{SATURATION_DIR.name}`",
        f"- Fixed-rate run: `{FIXED_RATE_DIR.name if FIXED_RATE_DIR else 'not available'}`",
        "",
        "This summary reports measured comparisons only and does not infer causality.",
    ]
    (EXPORT_DIR / "paper_summary.md").write_text("\\n".join(summary_lines) + "\\n", encoding="utf-8")
    html = "<html><body><h1>Routing benchmark analysis</h1>" + provenance.to_html(index=False) + validity_summary.to_html(index=False) + "</body></html>"
    (EXPORT_DIR / "interactive_report.html").write_text(html, encoding="utf-8")
    (EXPORT_DIR / "figure_notes.md").write_text(
        "# Figure notes\\n\\n"
        "- saturation_throughput uses equally spaced tested configurations on x and a logarithmic y-axis.\\n"
        "- saturation_throughput_faceted is a linear-scale alternative with infrastructure and routing paths separated.\\n"
        "- saturation_latency is a 2×2 logarithmic grid for valid XSR/VSR Average, P50, P95, and P99 latency.\\n"
        "- Aggregate error bars are between-trial 95% confidence intervals.\\n"
        "- routing_path_decomposition uses paired per-trial ratios, geometric means, and log-scale 95% intervals because the positive ratios span several orders of magnitude.\\n"
        "- Configurations with incomplete valid-trial coverage are excluded before plotting or calculating headline statistics.\\n",
        encoding="utf-8",
    )
    print(f"Exported paper-ready artifacts to {EXPORT_DIR}")
    """),
    markdown("## 11. Average throughput speedup"),
    code("""
    # Aggregate the valid, paired trial-level throughput ratios across every
    # fully valid tested concurrency. The arithmetic mean answers "average
    # speedup" directly; the geometric mean is included because ratios are
    # multiplicative and can span several orders of magnitude.
    throughput_speedups = paired_trial_ratios[
        paired_trial_ratios.metric.eq("throughput_rps")
    ].copy()
    if throughput_speedups.empty:
        raise ValueError("No valid paired throughput trials are available for speedup analysis")

    average_throughput_speedup = (
        throughput_speedups
        .groupby(["numerator", "denominator"], as_index=False)
        .agg(
            paired_trial_count=("ratio", "size"),
            tested_concurrencies=("concurrency", lambda values: ", ".join(map(str, sorted(set(values))))),
            arithmetic_mean_speedup=("ratio", "mean"),
            geometric_mean_speedup=("ratio", lambda values: float(np.exp(np.log(values).mean()))),
            minimum_speedup=("ratio", "min"),
            maximum_speedup=("ratio", "max"),
        )
        .sort_values(["numerator", "denominator"])
        .reset_index(drop=True)
    )
    average_throughput_speedup["comparison"] = (
        average_throughput_speedup.numerator + " / " + average_throughput_speedup.denominator
    )
    average_throughput_speedup = average_throughput_speedup[
        ["comparison", "paired_trial_count", "tested_concurrencies", "arithmetic_mean_speedup", "geometric_mean_speedup", "minimum_speedup", "maximum_speedup"]
    ]
    display(average_throughput_speedup.style.format({
        "arithmetic_mean_speedup": "{:.2f}×",
        "geometric_mean_speedup": "{:.2f}×",
        "minimum_speedup": "{:.2f}×",
        "maximum_speedup": "{:.2f}×",
    }))

    # Detail XSR's throughput advantage over VSR at each concurrency. The
    # overall median and maximum use the per-concurrency paired-trial means,
    # giving every tested concurrency equal weight.
    xsr_vsr_throughput = throughput_speedups[
        throughput_speedups.numerator.eq("XSR (SK_SKB/SOCKMAP)")
        & throughput_speedups.denominator.eq("VSR (Envoy ExtProc)")
    ].copy()
    if xsr_vsr_throughput.empty:
        raise ValueError("No valid paired XSR/VSR throughput trials are available for speedup analysis")

    xsr_vsr_speedup_by_concurrency = (
        xsr_vsr_throughput
        .groupby("concurrency", as_index=False)
        .agg(
            paired_trial_count=("ratio", "size"),
            mean_speedup=("ratio", "mean"),
            median_speedup=("ratio", "median"),
            geometric_mean_speedup=("ratio", lambda values: float(np.exp(np.log(values).mean()))),
            minimum_speedup=("ratio", "min"),
            maximum_speedup=("ratio", "max"),
        )
        .sort_values("concurrency")
        .reset_index(drop=True)
    )
    peak_xsr_vsr_speedup = xsr_vsr_speedup_by_concurrency.loc[
        xsr_vsr_speedup_by_concurrency.mean_speedup.idxmax()
    ]
    xsr_vsr_speedup_summary = pd.DataFrame([{
        "median_per_concurrency_mean_speedup": xsr_vsr_speedup_by_concurrency.mean_speedup.median(),
        "maximum_per_concurrency_mean_speedup": peak_xsr_vsr_speedup.mean_speedup,
        "maximum_at_concurrency": int(peak_xsr_vsr_speedup.concurrency),
    }])
    print("XSR / VSR throughput speedup by concurrency")
    display(xsr_vsr_speedup_by_concurrency.style.format({
        "mean_speedup": "{:.2f}×",
        "median_speedup": "{:.2f}×",
        "geometric_mean_speedup": "{:.2f}×",
        "minimum_speedup": "{:.2f}×",
        "maximum_speedup": "{:.2f}×",
    }))
    print("XSR / VSR throughput speedup summary")
    display(xsr_vsr_speedup_summary.style.format({
        "median_per_concurrency_mean_speedup": "{:.2f}×",
        "maximum_per_concurrency_mean_speedup": "{:.2f}×",
    }))
    """),
]

notebook = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
})
nbf.write(notebook, OUTPUT)
print(OUTPUT)
