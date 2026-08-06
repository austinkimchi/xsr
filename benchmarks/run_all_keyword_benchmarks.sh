#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

METHODS=("literal" "exact" "bm25" "ngram" "regex")
CONCURRENCIES=(1 4 8 16)
REPORT_ROOT="reports/keyword-routing"
BENCHMARK_MODES="${BENCHMARK_MODES:-direct-netns,xdp,vllm-sr}"

if [ "$EUID" -ne 0 ]; then
  echo "XDP benchmark requires root privileges. Elevating with sudo..."
  exec sudo "$0" "$@"
fi

cd "${ROOT_DIR}"

echo "================================================================="
echo " Starting Keyword Routing Benchmarks"
echo " Methods: ${METHODS[*]}"
echo " Concurrency: ${CONCURRENCIES[*]}"
echo " Modes: ${BENCHMARK_MODES}"
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
  XDP_CLASSIFIER_MODE="literal"
  if [ "$METHOD" = "ngram" ]; then
    XDP_CLASSIFIER_MODE="ngram"
  fi
  make KEYWORD_POLICY="$CONFIG" XDP_CLASSIFIER="$XDP_CLASSIFIER_MODE" dev

  echo ""
  echo "-----------------------------------------------------------------"
  echo " [2/2] Running benchmark suite for method: ${METHOD}"
  echo "-----------------------------------------------------------------"
  for CONCURRENCY in "${CONCURRENCIES[@]}"; do
    REPORT_DIR="${REPORT_ROOT}/concurrency_${CONCURRENCY}"
    mkdir -p "$REPORT_DIR"

    echo ""
    echo "   - concurrency=${CONCURRENCY}"
    echo "     output=${REPORT_DIR}/keyword_${METHOD}.md"
    python3 tests/benchmark_keyword_routing.py \
      "$@" \
      --config "$CONFIG" \
      --concurrency "$CONCURRENCY" \
      --report-dir "$REPORT_DIR" \
      --modes "$BENCHMARK_MODES" \
      --no-build
  done
  echo ""
done

echo "================================================================="
echo " All keyword benchmarks completed successfully!"
echo " Generated report files:"
for CONCURRENCY in "${CONCURRENCIES[@]}"; do
  REPORT_DIR="${REPORT_ROOT}/concurrency_${CONCURRENCY}"
  echo "  - ${REPORT_DIR}/"
  for METHOD in "${METHODS[@]}"; do
    if [ -f "${REPORT_DIR}/keyword_${METHOD}.md" ]; then
      echo "      keyword_${METHOD}.md"
    fi
  done
done
echo "================================================================="
