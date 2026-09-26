#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT_DIR=""
TRIALS=5
DURATION=20s
WARMUP=2s
CONCURRENCY=64
SEED=20260826
PROMPTS_FILE="${ROOT_DIR}/benchmarks/dataset_prompts.jsonl"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --trials) TRIALS="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --warmup) WARMUP="$2"; shift 2 ;;
        --concurrency) CONCURRENCY="$2"; shift 2 ;;
        --seed) SEED="$2"; shift 2 ;;
        --prompts) PROMPTS_FILE="$2"; shift 2 ;;
        *) echo "Error: unknown forwarding ablation option: $1" >&2; exit 2 ;;
    esac
done

[ -n "$OUTPUT_DIR" ] || OUTPUT_DIR="${ROOT_DIR}/results/ablation/forwarding-$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"
REPORT_DIR="$(dirname "$OUTPUT_DIR")"
RUN_ID="$(basename "$OUTPUT_DIR")"

if [ "$EUID" -ne 0 ]; then
    exec sudo "$0" --output-dir "$OUTPUT_DIR" --trials "$TRIALS" \
        --duration "$DURATION" --warmup "$WARMUP" --concurrency "$CONCURRENCY" \
        --seed "$SEED" --prompts "$PROMPTS_FILE"
fi

cd "$ROOT_DIR"
env REPORT_DIR="$REPORT_DIR" RUN_ID="$RUN_ID" \
    BENCHMARK_PROFILE=ablation BENCHMARK_SYSTEMS=direct,envoy-only,xsr \
    XSR_FORWARDING_ONLY=1 SIGNAL_PROFILE=ngram TRIALS="$TRIALS" \
    DURATION="$DURATION" WARMUP_DURATION="$WARMUP" CONCURRENCY="$CONCURRENCY" \
    RANDOM_SEED="$SEED" PROMPTS_FILE="$PROMPTS_FILE" PROMPTS_EXPLICIT=1 \
    WORKLOAD_ID=ablation-paper-workload \
    ./benchmarks/routing_wrk/benchmark.sh

python3 - "$OUTPUT_DIR" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
isolation = {
    "ablation": "forwarding-path",
    "systems": ["direct-backend", "xsr-forwarding-only", "envoy-only"],
    "xsr_fixed_backend": "coding",
    "xsr_signal_generation": False,
    "xsr_decision_policy": False,
    "envoy_extproc": False,
    "timed_metrics": ["throughput_rps", "average_latency_us", "p99_latency_us"],
}
(output / "isolation.json").write_text(json.dumps(isolation, indent=2) + "\n", encoding="utf-8")
metadata_path = output / "metadata.json"
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
metadata["ablation"] = isolation
if isinstance(metadata.get("xsr"), dict):
    metadata["xsr"]["routing_mode"] = "forwarding-only-fixed-coding-backend"
metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

if [ -n "${SUDO_USER:-}" ]; then
    chown -R "$SUDO_USER:" "$OUTPUT_DIR" 2>/dev/null || true
fi
echo "Forwarding-path ablation results: $OUTPUT_DIR"
