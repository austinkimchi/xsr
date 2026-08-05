#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

WRK_BIN="${WRK_BIN:-wrk2}"
DURATION="${DURATION:-15s}"
THREADS="${THREADS:-4}"
CONCURRENCY="${CONCURRENCY:-4}"
RATE="${RATE:-10000}"
XDP_PORT="${XDP_PORT:-18081}"
VLLM_BACKEND_PORT="${VLLM_BACKEND_PORT:-18391}"
IFNAME="${IFNAME:-veth0}"
NETNS="${NETNS:-ns1}"
XDP_URL="${XDP_URL:-http://10.10.0.1:${XDP_PORT}/v1/chat/completions}"
VLLM_URL="${VLLM_URL:-http://127.0.0.1:8899/v1/chat/completions}"
REPORT_DIR="${ROOT_DIR}/results/wrk-keyword-routing"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${REPORT_DIR}/wrk_benchmark_${TIMESTAMP}.md"
LATEST_FILE="${REPORT_DIR}/latest.md"

if [ "$EUID" -ne 0 ]; then
    echo "XDP benchmark requires root privileges to attach BPF and manage netns. Elevating with sudo..."
    exec sudo "$0" "$@"
fi

cd "$ROOT_DIR"
mkdir -p "$REPORT_DIR"

if ! command -v "$WRK_BIN" &> /dev/null; then
    if command -v wrk &> /dev/null; then
        WRK_BIN="wrk"
    else
        echo "Error: Neither wrk nor wrk2 is installed."
        echo "Install via: apt-get install wrk (or compile wrk2 from source)"
        exit 1
    fi
fi

# Ensure threads is not greater than concurrency (wrk requirement)
if [ "$THREADS" -gt "$CONCURRENCY" ]; then
    THREADS="$CONCURRENCY"
fi

# Kill any stale mock_backend or xdp_router processes
pkill -9 mock_backend >/dev/null 2>&1 || true
pkill -9 xdp_router >/dev/null 2>&1 || true

# Ensure netns setup
make setup >/dev/null 2>&1 || true

# Generate prompt dataset if missing
if [ ! -f "benchmarks/dataset_prompts.jsonl" ]; then
    echo "Generating dataset_prompts.jsonl..."
    python3 benchmarks/export_dataset_prompts.py
fi

# Build mock backend and xdp_router if missing
if [ ! -f "benchmarks/mock_backend" ] || [ ! -f "xdp_router" ]; then
    echo "Building XDP router and mock backend..."
    make dev KEYWORD_POLICY=config/policy_literal.yaml
fi

# Flush old iptables rules for these ports
iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true

# Add iptables rules
iptables -I INPUT 1 -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true

# Start mock HTTP backends for both XDP (18081) and vLLM-SR (18391)
echo "Starting mock HTTP backend for XDP on port ${XDP_PORT}..."
./benchmarks/mock_backend "${XDP_PORT}" > /dev/null 2>&1 &
XDP_MOCK_PID=$!

echo "Starting mock HTTP backend for vLLM-SR on port ${VLLM_BACKEND_PORT}..."
./benchmarks/mock_backend "${VLLM_BACKEND_PORT}" > /dev/null 2>&1 &
VLLM_MOCK_PID=$!

# Start xdp_router in background
echo "Attaching XDP router to ${IFNAME}..."
./xdp_router > /dev/null 2>&1 &
ROUTER_PID=$!

cleanup() {
    echo ""
    echo "Cleaning up processes and network rules..."
    kill -9 "$ROUTER_PID" >/dev/null 2>&1 || true
    kill -9 "$XDP_MOCK_PID" >/dev/null 2>&1 || true
    kill -9 "$VLLM_MOCK_PID" >/dev/null 2>&1 || true
    ip link set dev "${IFNAME}" xdp off >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    if [ -n "$SUDO_USER" ]; then
        chown -R "$SUDO_USER:" "$REPORT_DIR" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Wait a moment for socket bind and BPF attach
sleep 1.5

run_benchmark() {
    echo "# High-Performance ${WRK_BIN} Benchmark Results"
    echo ""
    echo "- Timestamp: \`$(date)\`"
    echo "- Tool: \`${WRK_BIN}\`"
    echo "- Threads: \`${THREADS}\`"
    echo "- Connections: \`${CONCURRENCY}\`"
    echo "- Duration: \`${DURATION}\`"
    if [ "$WRK_BIN" = "wrk2" ]; then
        echo "- Target Rate: \`${RATE} RPS\`"
        RATE_ARG="-R ${RATE}"
    else
        RATE_ARG=""
    fi
    echo ""
    echo "## [1/2] XDP Route (via netns)"
    echo "\`\`\`"
    ip netns exec "${NETNS}" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s benchmarks/prompts.lua "$XDP_URL"
    echo "\`\`\`"
    echo ""
    echo "## [2/2] vLLM-SR Route"
    echo "\`\`\`"
    if socket_check=$(curl -s -m 1 "$VLLM_URL" 2>&1); [[ ! "$socket_check" =~ "Failed to connect" ]]; then
        "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s benchmarks/prompts.lua "$VLLM_URL"
    else
        echo "vLLM-SR endpoint ($VLLM_URL) unreachable, skipping vLLM-SR run."
    fi
    echo "\`\`\`"
}

run_benchmark | tee "$REPORT_FILE"
cp "$REPORT_FILE" "$LATEST_FILE"

if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:" "$REPORT_DIR" 2>/dev/null || true
fi

echo ""
echo "================================================================="
echo " Benchmark complete! Results saved to:"
echo "   - ${REPORT_FILE}"
echo "   - ${LATEST_FILE}"
echo "================================================================="
