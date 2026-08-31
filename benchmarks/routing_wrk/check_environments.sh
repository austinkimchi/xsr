#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BENCHMARK_SYSTEMS="${BENCHMARK_SYSTEMS:-direct,envoy-only,xsr,vsr,llmrouter}"
BENCHMARK_PYTHON="${BENCHMARK_PYTHON:-${ROOT_DIR}/.venv/bin/python}"
LLMROUTER_PYTHON="${LLMROUTER_PYTHON:-${ROOT_DIR}/.venv-llmrouter/bin/python}"
LLMROUTER_BIN="${LLMROUTER_BIN:-${ROOT_DIR}/.venv-llmrouter/bin/llmrouter}"
LLMROUTER_REVISION="${LLMROUTER_REVISION:-da3430baaea672743c3957457b0c76faba19876e}"
VLLM_HOST="${VLLM_HOST:-vllm-sr-envoy-container}"

fail() {
    echo "Error: $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "command '$1' is required."
}

IFS=',' read -r -a systems <<< "$BENCHMARK_SYSTEMS"
declare -A selected=()
for system in "${systems[@]}"; do
    case "$system" in
        direct|envoy-only|xsr|vsr|llmrouter|xsr-legacy) ;;
        *) fail "unsupported benchmark system '$system'." ;;
    esac
    [ -z "${selected[$system]+x}" ] || fail "duplicate benchmark system '$system'."
    selected[$system]=1
done

[ -x "$BENCHMARK_PYTHON" ] || fail "benchmark Python is missing; run 'make benchmark-install'."
"$BENCHMARK_PYTHON" -c 'import datasets, matplotlib, nbconvert, nbformat, numpy, pandas' \
    >/dev/null 2>&1 || fail "benchmark Python packages are incomplete; run 'make benchmark-install'."
for command in "${CC:-cc}" curl ip iptables ethtool; do
    require_command "$command"
done

if [ -n "${selected[xsr]+x}" ] || [ -n "${selected[xsr-legacy]+x}" ]; then
    make -C "$ROOT_DIR" check
fi

if [ -n "${selected[vsr]+x}" ] || [ -n "${selected[envoy-only]+x}" ]; then
    require_command docker
    docker info >/dev/null 2>&1 || fail "the Docker daemon is unavailable."
    running="$(docker inspect -f '{{.State.Running}}' "$VLLM_HOST" 2>/dev/null || true)"
    [ "$running" = "true" ] || fail "VSR Envoy container '$VLLM_HOST' is not running."
fi

if [ -n "${selected[llmrouter]+x}" ]; then
    [ -x "$LLMROUTER_PYTHON" ] && [ -x "$LLMROUTER_BIN" ] || \
        fail "LLMRouter is missing; run 'make llmrouter-install'."
    "$LLMROUTER_PYTHON" -c 'import llmrouter, openclaw_router, uvicorn; from llmrouter.models.meta_router import MetaRouter' \
        >/dev/null 2>&1 || fail "the LLMRouter environment is incomplete; run 'make llmrouter-install'."
    installed_revision=$("$LLMROUTER_PYTHON" -c \
        'import json; from importlib.metadata import distribution; print(json.loads(distribution("llmrouter-lib").read_text("direct_url.json"))["vcs_info"]["commit_id"])' \
        2>/dev/null) || fail "could not verify the installed LLMRouter revision."
    [ "$installed_revision" = "$LLMROUTER_REVISION" ] || \
        fail "LLMRouter revision ${installed_revision} is installed; expected ${LLMROUTER_REVISION}. Run 'make llmrouter-install'."
fi

echo "Benchmark environment check passed for: ${BENCHMARK_SYSTEMS}"
