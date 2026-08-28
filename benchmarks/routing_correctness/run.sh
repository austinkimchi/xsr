#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${PYTHON:-${ROOT_DIR}/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ] && ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: benchmark Python is unavailable; run 'make benchmark' first." >&2
  exit 1
fi

read -r -a METHODS <<< "${KEYWORD_METHODS:-ngram bm25}"
CONCURRENCIES=(1 4 8 16)
REPORT_ROOT="results/routing-correctness"
BENCHMARK_MODES="${BENCHMARK_MODES:-direct-netns,sockmap,vllm-sr}"
SPEED_BENCH_ARGS=(--dataset speed-bench --scan-limit 880)

if [ "$EUID" -ne 0 ]; then
  echo "XDP benchmark requires root privileges. Elevating with sudo..."
  exec sudo env PYTHON="$PYTHON_BIN" "$0" "$@"
fi

cd "${ROOT_DIR}"

echo "================================================================="
echo " Starting Routing Correctness Benchmarks"
echo " Methods: ${METHODS[*]}"
echo " Concurrency: ${CONCURRENCIES[*]}"
echo " Modes: ${BENCHMARK_MODES}"
echo " Dataset: SPEED-Bench qualitative/test (880 rows)"
echo " Report root: ${REPORT_ROOT}"
echo "================================================================="

for METHOD in "${METHODS[@]}"; do
  CONFIG="config/policy_${METHOD}.yaml"
  if [ ! -f "$CONFIG" ]; then
    echo "Warning: $CONFIG not found, skipping $METHOD."
    continue
  fi

  echo ""
  echo "-----------------------------------------------------------------"
  echo " [1/2] Building XDP router for method: ${METHOD}"
  echo " Config: ${CONFIG}"
  echo "-----------------------------------------------------------------"
  make KEYWORD_POLICY="$CONFIG" PYTHON="$PYTHON_BIN" policy
  make KEYWORD_POLICY="$CONFIG" dev
  if [[ ",${BENCHMARK_MODES}," == *,xdp,* ]]; then
    make legacy
  fi

  echo ""
  echo "-----------------------------------------------------------------"
  echo " [2/2] Running benchmark suite for method: ${METHOD}"
  echo "-----------------------------------------------------------------"
  for CONCURRENCY in "${CONCURRENCIES[@]}"; do
    REPORT_DIR="${REPORT_ROOT}"
    REPORT_NAME="routing_correctness_${METHOD}_concurrency_${CONCURRENCY}.md"
    mkdir -p "${REPORT_DIR}"

    echo ""
    echo "   - concurrency=${CONCURRENCY}"
    echo "     output=${REPORT_DIR}/${REPORT_NAME}"
    "$PYTHON_BIN" "${SCRIPT_DIR}/benchmark.py" \
      "${SPEED_BENCH_ARGS[@]}" \
      "$@" \
      --config "$CONFIG" \
      --concurrency "$CONCURRENCY" \
      --report-dir "$REPORT_DIR" \
      --report-name "$REPORT_NAME" \
      --modes "$BENCHMARK_MODES" \
      --no-build
  done
  echo ""
done

echo "================================================================="
echo " All routing correctness benchmarks completed successfully!"
echo " Generated report files:"
for CONCURRENCY in "${CONCURRENCIES[@]}"; do
  for METHOD in "${METHODS[@]}"; do
    REPORT_NAME="routing_correctness_${METHOD}_concurrency_${CONCURRENCY}.md"
    if [ -f "${REPORT_ROOT}/${REPORT_NAME}" ]; then
      echo "  - ${REPORT_ROOT}/${REPORT_NAME}"
    fi
  done
done
echo "================================================================="
