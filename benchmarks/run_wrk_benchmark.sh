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
CODING_BACKEND_PORT="${CODING_BACKEND_PORT:-18391}"
MATH_BACKEND_PORT="${MATH_BACKEND_PORT:-18392}"
OTHERS_BACKEND_PORT="${OTHERS_BACKEND_PORT:-18393}"
VLLM_BACKEND_PORT="${VLLM_BACKEND_PORT:-18394}"
START_VLLM_MOCK="${START_VLLM_MOCK:-0}"
IFNAME="${IFNAME:-veth0}"
NETNS="${NETNS:-ns1}"
XDP_URL="${XDP_URL:-http://127.0.0.1:${XDP_PORT}/v1/chat/completions}"
VLLM_URL="${VLLM_URL:-http://127.0.0.1:8899/v1/chat/completions}"
REPORT_DIR="${ROOT_DIR}/results/wrk-keyword-routing"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${REPORT_DIR}/wrk_benchmark_${TIMESTAMP}.md"
LATEST_FILE="${REPORT_DIR}/latest.md"

if [ "$EUID" -ne 0 ]; then
    echo "Routing benchmark uses sudo for cleanup and firewall setup. Elevating..."
    exec sudo env \
        WRK_BIN="$WRK_BIN" \
        DURATION="$DURATION" \
        THREADS="$THREADS" \
        CONCURRENCY="$CONCURRENCY" \
        RATE="$RATE" \
        XDP_PORT="$XDP_PORT" \
        CODING_BACKEND_PORT="$CODING_BACKEND_PORT" \
        MATH_BACKEND_PORT="$MATH_BACKEND_PORT" \
        OTHERS_BACKEND_PORT="$OTHERS_BACKEND_PORT" \
        VLLM_BACKEND_PORT="$VLLM_BACKEND_PORT" \
        START_VLLM_MOCK="$START_VLLM_MOCK" \
        XDP_URL="$XDP_URL" \
        VLLM_URL="$VLLM_URL" \
        "$0" "$@"
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

# Kill any stale mock_backend or router processes
pkill -9 mock_backend >/dev/null 2>&1 || true
pkill -9 xdp_router >/dev/null 2>&1 || true
pkill -9 sk_router >/dev/null 2>&1 || true

# Generate prompt dataset if missing or from the older no-route-metadata format.
if [ ! -f "benchmarks/dataset_prompts.jsonl" ] || ! head -n 1 benchmarks/dataset_prompts.jsonl | grep -q '"x_expected_route"'; then
    echo "Generating dataset_prompts.jsonl..."
    python3 benchmarks/export_dataset_prompts.py
fi

# Build mock backend and routers if missing
if [ ! -f "benchmarks/mock_backend" ] || [ ! -f "sk_router" ] || [ ! -f "sk_router.bpf.o" ]; then
    echo "Building routing proxy and mock backends..."
    make dev KEYWORD_POLICY=config/policy_ngram.yaml XDP_CLASSIFIER=ngram
fi

# Flush old iptables rules for these ports
iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true

# Add iptables rules
iptables -I INPUT 1 -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true

# Start marker backends for routing.
echo "Starting coding backend on port ${CODING_BACKEND_PORT}..."
./benchmarks/mock_backend "${CODING_BACKEND_PORT}" coding > /dev/null 2>&1 &
CODING_MOCK_PID=$!

echo "Starting math backend on port ${MATH_BACKEND_PORT}..."
./benchmarks/mock_backend "${MATH_BACKEND_PORT}" math > /dev/null 2>&1 &
MATH_MOCK_PID=$!

echo "Starting others backend on port ${OTHERS_BACKEND_PORT}..."
./benchmarks/mock_backend "${OTHERS_BACKEND_PORT}" others > /dev/null 2>&1 &
OTHERS_MOCK_PID=$!

VLLM_MOCK_PID=""
if [ "$START_VLLM_MOCK" = "1" ]; then
    echo "Starting auxiliary mock HTTP backend for vLLM-SR on port ${VLLM_BACKEND_PORT}..."
    ./benchmarks/mock_backend "${VLLM_BACKEND_PORT}" others > /dev/null 2>&1 &
    VLLM_MOCK_PID=$!
fi

# Start routing proxy in background. Set SK_ROUTER_MODE=sockmap to exercise the
# experimental kernel SOCKMAP path instead.
echo "Starting routing proxy..."
./sk_router > /tmp/sk_router_wrk.log 2>&1 &
ROUTER_PID=$!

wait_for_port() {
    local port="$1"
    local name="$2"
    local deadline=$((SECONDS + 10))

    while [ "$SECONDS" -lt "$deadline" ]; do
        if ! kill -0 "$ROUTER_PID" >/dev/null 2>&1; then
            echo "Error: sk_router exited before ${name} opened:"
            cat /tmp/sk_router_wrk.log
            exit 1
        fi
        if timeout 1 bash -c ":</dev/tcp/127.0.0.1/${port}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "Error: ${name} did not open on port ${port}; router log:"
    cat /tmp/sk_router_wrk.log
    exit 1
}

cleanup() {
    echo ""
    echo "Cleaning up processes and network rules..."
    kill -9 "$ROUTER_PID" >/dev/null 2>&1 || true
    kill -9 "$CODING_MOCK_PID" >/dev/null 2>&1 || true
    kill -9 "$MATH_MOCK_PID" >/dev/null 2>&1 || true
    kill -9 "$OTHERS_MOCK_PID" >/dev/null 2>&1 || true
    kill -9 "$VLLM_MOCK_PID" >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    if [ -n "$SUDO_USER" ]; then
        chown -R "$SUDO_USER:" "$REPORT_DIR" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Wait for socket bind.
wait_for_port "$XDP_PORT" "routing frontend"

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
    echo "- Routing backend ports: coding=\`${CODING_BACKEND_PORT}\`, math=\`${MATH_BACKEND_PORT}\`, others=\`${OTHERS_BACKEND_PORT}\`"
    echo ""
    echo "## [1/2] Routing Proxy"
    echo "\`\`\`"
    VERIFY_BACKEND_MARKERS=1 "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s benchmarks/prompts.lua "$XDP_URL"
    echo "\`\`\`"
    echo ""
    echo "## [2/2] vLLM-SR Route"
    echo "\`\`\`"
    if socket_check=$(curl -s -m 1 "$VLLM_URL" 2>&1); [[ ! "$socket_check" =~ "Failed to connect" ]]; then
        VERIFY_BACKEND_MARKERS=1 "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s benchmarks/prompts.lua "$VLLM_URL"
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
