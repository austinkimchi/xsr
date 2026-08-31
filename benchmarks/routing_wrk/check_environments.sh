#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BENCHMARK_SYSTEMS="${BENCHMARK_SYSTEMS:-direct,envoy-only,xsr,vsr,llmrouter}"
BENCHMARK_PYTHON="${BENCHMARK_PYTHON:-${ROOT_DIR}/.venv/bin/python}"
LLMROUTER_PYTHON="${LLMROUTER_PYTHON:-${ROOT_DIR}/.venv-llmrouter/bin/python}"
LLMROUTER_BIN="${LLMROUTER_BIN:-${ROOT_DIR}/.venv-llmrouter/bin/llmrouter}"
LLMROUTER_REVISION="${LLMROUTER_REVISION:-da3430baaea672743c3957457b0c76faba19876e}"
VLLM_HOST="${VLLM_HOST:-vllm-sr-envoy-container}"
BENCHMARK_MODE="${BENCHMARK_MODE:-all}"
WRK_BIN="${WRK_BIN:-${ROOT_DIR}/.tools/wrk/wrk}"
WRK2_BIN="${WRK2_BIN:-${ROOT_DIR}/.tools/wrk2/wrk}"
NETNS="${NETNS:-ns1}"
IFNAME="${IFNAME:-veth0}"
XDP_PEER_IF="${XDP_PEER_IF:-veth1}"
REQUIRE_BENCHMARK_NETWORK="${REQUIRE_BENCHMARK_NETWORK:-0}"

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
[ "$(uname -s)" = "Linux" ] || fail "routing benchmarks require Linux."
"$BENCHMARK_PYTHON" -c 'import datasets, matplotlib, nbconvert, nbformat, numpy, pandas' \
    >/dev/null 2>&1 || fail "benchmark Python packages are incomplete; run 'make benchmark-install'."
for command in "${CC:-cc}" curl ip iptables ethtool; do
    require_command "$command"
done

case "$BENCHMARK_MODE" in
    saturation)
        [ -x "$WRK_BIN" ] || command -v "$WRK_BIN" >/dev/null 2>&1 || \
            fail "standard wrk is missing; run 'make install-wrk'."
        ;;
    fixed-rate)
        [ -x "$WRK2_BIN" ] || command -v "$WRK2_BIN" >/dev/null 2>&1 || \
            fail "wrk2 is missing; run 'make install-wrk2'."
        ;;
    all)
        [ -x "$WRK_BIN" ] || command -v wrk >/dev/null 2>&1 || \
            fail "standard wrk is missing; run 'make install-wrk'."
        [ -x "$WRK2_BIN" ] || command -v wrk2 >/dev/null 2>&1 || \
            fail "wrk2 is missing; run 'make install-wrk2'."
        ;;
    *) fail "BENCHMARK_MODE must be saturation, fixed-rate, or all." ;;
esac

if [ "$REQUIRE_BENCHMARK_NETWORK" = "1" ]; then
    ip link show dev "$IFNAME" >/dev/null 2>&1 || \
        fail "benchmark interface ${IFNAME} is missing; run 'sudo make setup iproutes'."
    ip netns exec "$NETNS" ip link show dev "$XDP_PEER_IF" >/dev/null 2>&1 || \
        fail "benchmark interface ${NETNS}/${XDP_PEER_IF} is missing; run 'sudo make setup iproutes'."
    ip -o -4 addr show dev "$IFNAME" | grep -Fq '10.10.0.1/24' || \
        fail "benchmark interface ${IFNAME} does not have 10.10.0.1/24; run 'sudo make setup iproutes'."
    ip netns exec "$NETNS" ip -o -4 addr show dev "$XDP_PEER_IF" | grep -Fq '10.10.0.2/24' || \
        fail "benchmark interface ${NETNS}/${XDP_PEER_IF} does not have 10.10.0.2/24; run 'sudo make setup iproutes'."
fi

if [ -n "${selected[xsr]+x}" ]; then
    REQUIRE_RUNTIME_BPF=1 make -C "$ROOT_DIR" check
elif [ -n "${selected[xsr-legacy]+x}" ]; then
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
