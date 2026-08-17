#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

WRK_BIN="${WRK_BIN:-wrk2}"
DURATION="${DURATION:-30s}"
BASE_THREADS="${THREADS:-4}"
DEFAULT_CONCURRENCIES=(1 2 4 8 10 16 32 64 96)
RATE="${RATE:-10000}"
XDP_PORT="${XDP_PORT:-18081}"
CODING_BACKEND_PORT="${CODING_BACKEND_PORT:-18391}"
MATH_BACKEND_PORT="${MATH_BACKEND_PORT:-18392}"
OTHERS_BACKEND_PORT="${OTHERS_BACKEND_PORT:-18393}"
VLLM_BACKEND_PORT="${VLLM_BACKEND_PORT:-18394}"
START_VLLM_MOCK="${START_VLLM_MOCK:-0}"
IFNAME="${IFNAME:-veth0}"
NETNS="${NETNS:-ns1}"
XDP_PEER_IF="${XDP_PEER_IF:-veth1}"
XDP_URL="${XDP_URL:-http://10.10.0.1:${XDP_PORT}/v1/chat/completions}"
# Use a marker backend directly over the same ns1/veth path as the routers.
DIRECT_BACKEND_URL="${DIRECT_BACKEND_URL:-http://10.10.0.1:${CODING_BACKEND_PORT}/v1/chat/completions}"
# Exercise both routers from the same client namespace across the veth pair.
# This preserves end-to-end router differences while removing the loopback vs.
# veth client-path confounder.
VLLM_URL="${VLLM_URL:-http://10.10.0.1:8899/v1/chat/completions}"
REPORT_DIR="${ROOT_DIR}/results/routing-performance"
LATEST_FILE="${REPORT_DIR}/latest.md"

if [ "$EUID" -ne 0 ]; then
    echo "Routing benchmark uses sudo for cleanup and firewall setup. Elevating..."
    sudo_env=(
        WRK_BIN="$WRK_BIN"
        DURATION="$DURATION"
        THREADS="$BASE_THREADS"
        RATE="$RATE"
        XDP_PORT="$XDP_PORT"
        CODING_BACKEND_PORT="$CODING_BACKEND_PORT"
        MATH_BACKEND_PORT="$MATH_BACKEND_PORT"
        OTHERS_BACKEND_PORT="$OTHERS_BACKEND_PORT"
        VLLM_BACKEND_PORT="$VLLM_BACKEND_PORT"
        START_VLLM_MOCK="$START_VLLM_MOCK"
        IFNAME="$IFNAME"
        NETNS="$NETNS"
        XDP_PEER_IF="$XDP_PEER_IF"
        XDP_URL="$XDP_URL"
        DIRECT_BACKEND_URL="$DIRECT_BACKEND_URL"
        VLLM_URL="$VLLM_URL"
    )
    # Only propagate CONCURRENCY when the caller supplied it. Otherwise the
    # elevated invocation must retain the default full sweep.
    if [ "${CONCURRENCY+x}" = "x" ]; then
        sudo_env+=(CONCURRENCY="$CONCURRENCY")
    fi
    exec sudo env "${sudo_env[@]}" "$0" "$@"
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

# Kill any stale mock_backend or router processes
pkill -9 mock_backend >/dev/null 2>&1 || true
pkill -9 xdp_router >/dev/null 2>&1 || true
pkill -9 sk_router >/dev/null 2>&1 || true

# Generate prompt dataset if missing or from the older no-route-metadata format.
if [ ! -f "benchmarks/dataset_prompts.jsonl" ] || ! head -n 1 benchmarks/dataset_prompts.jsonl | grep -q '"x_expected_route"'; then
    echo "Generating dataset_prompts.jsonl..."
    python3 "${SCRIPT_DIR}/export_prompts.py"
fi

# Build mock backend and routers if missing
if [ ! -f "benchmarks/mock_backend" ] || [ ! -f "sk_router" ] || [ ! -f "sk_router.bpf.o" ]; then
    echo "Building routing proxy and mock backends..."
    make dev KEYWORD_POLICY=config/policy_ngram.yaml
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

# Keep XDP exposed to ordinary MTU-sized TCP segments during benchmark runs.
ip link set dev "$IFNAME" mtu 1500
ip netns exec "$NETNS" ip link set dev "$XDP_PEER_IF" mtu 1500
ethtool -K "$IFNAME" gro off gso off tso off lro off 2>/dev/null || true
ip netns exec "$NETNS" ethtool -K "$XDP_PEER_IF" gro off gso off tso off lro off 2>/dev/null || true

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

ROUTER_PID=""

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
    for pid in "$ROUTER_PID" "$CODING_MOCK_PID" "$MATH_MOCK_PID" "$OTHERS_MOCK_PID" "$VLLM_MOCK_PID"; do
        if [ -n "$pid" ]; then
            kill -9 "$pid" >/dev/null 2>&1 || true
            wait "$pid" 2>/dev/null || true
        fi
    done
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

detach_xdp() {
    # A prior benchmark may have left an XDP program attached after its
    # userspace router exited. The direct control must not traverse it.
    if ! ip link set dev "$IFNAME" xdp off; then
        echo "Error: could not detach XDP from ${IFNAME}; refusing to run a non-control baseline."
        return 1
    fi
    if ip -details link show dev "$IFNAME" | grep -q 'prog/xdp'; then
        echo "Error: XDP remains attached to ${IFNAME}; refusing to run a non-control baseline."
        return 1
    fi
}

start_routing_proxy() {
    # Start routing proxy in background. Set SK_ROUTER_MODE=sockmap to exercise
    # the experimental kernel SOCKMAP path instead.
    echo "Starting routing proxy..."
    ./sk_router > /tmp/sk_router_wrk.log 2>&1 &
    ROUTER_PID=$!
    wait_for_port "$XDP_PORT" "routing frontend"
}

stop_routing_proxy() {
    if [ -n "$ROUTER_PID" ]; then
        kill -9 "$ROUTER_PID" >/dev/null 2>&1 || true
        wait "$ROUTER_PID" 2>/dev/null || true
        ROUTER_PID=""
    fi
}

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
    echo "## [1/3] Direct Backend"
    echo "\`\`\`"
    # No route decision occurs for the control, so prompts.lua must not check
    # response markers. XDP was detached before this benchmark began.
    VERIFY_BACKEND_MARKERS=0 ip netns exec "$NETNS" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s "${SCRIPT_DIR}/prompts.lua" "$DIRECT_BACKEND_URL"
    echo "\`\`\`"
    echo ""

    start_routing_proxy

    echo "## [2/3] XSR/XDP Route"
    echo "\`\`\`"
    VERIFY_BACKEND_MARKERS=1 ip netns exec "$NETNS" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s "${SCRIPT_DIR}/prompts.lua" "$XDP_URL"
    echo "\`\`\`"
    echo ""
    echo "## [3/3] vLLM-SR Route"
    echo "\`\`\`"
    if socket_check=$(ip netns exec "$NETNS" curl -s -m 1 "$VLLM_URL" 2>&1); [[ ! "$socket_check" =~ "Failed to connect" ]]; then
        VERIFY_BACKEND_MARKERS=1 ip netns exec "$NETNS" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s "${SCRIPT_DIR}/prompts.lua" "$VLLM_URL"
    else
        echo "vLLM-SR endpoint ($VLLM_URL) unreachable, skipping vLLM-SR run."
    fi
    echo "\`\`\`"
}

if [ "${CONCURRENCY+x}" = "x" ]; then
    CONCURRENCIES=("$CONCURRENCY")
else
    CONCURRENCIES=("${DEFAULT_CONCURRENCIES[@]}")
fi

for CONCURRENCY in "${CONCURRENCIES[@]}"; do
    # Restore the configured thread count for every sweep entry: a low initial
    # concurrency must not clamp the thread count of subsequent runs.
    THREADS="$BASE_THREADS"
    if [ "$THREADS" -gt "$CONCURRENCY" ]; then
        THREADS="$CONCURRENCY"
    fi

    TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
    REPORT_FILE="${REPORT_DIR}/routing_performance_c${CONCURRENCY}_${TIMESTAMP}.md"

    # The preceding XSR run leaves a classifier and router behind. Remove both
    # before each direct control measurement.
    stop_routing_proxy
    detach_xdp
    # Capture tee's PID before run_benchmark starts sk_router in the
    # background, which would otherwise overwrite $!.  Keep the write end in
    # an explicit descriptor so it can be closed after the router exits.
    exec {report_fd}> >(tee "$REPORT_FILE")
    tee_pid=$!
    run_benchmark >&"$report_fd"
    # sk_router inherits the report pipe; terminate it before closing the
    # descriptor and waiting for tee, otherwise tee never observes EOF.
    stop_routing_proxy
    exec {report_fd}>&-
    wait "$tee_pid"
    cp "$REPORT_FILE" "$LATEST_FILE"

    echo ""
    echo "================================================================="
    echo " Benchmark complete! Results saved to:"
    echo "   - ${REPORT_FILE}"
    echo "   - ${LATEST_FILE}"
    echo "================================================================="
done

if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:" "$REPORT_DIR" 2>/dev/null || true
fi
