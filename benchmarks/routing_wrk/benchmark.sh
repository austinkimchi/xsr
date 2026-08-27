#!/usr/bin/env bash
set -e

# `make performance args="VLLM_IP=..."` forwards these as positional
# arguments. Accept the benchmark configuration assignments that users
# commonly pass through that target without evaluating arbitrary shell text.
for benchmark_arg in "$@"; do
    case "$benchmark_arg" in
        VLLM_IP=*) VLLM_IP="${benchmark_arg#VLLM_IP=}" ;;
        VLLM_HOST=*) VLLM_HOST="${benchmark_arg#VLLM_HOST=}" ;;
        VLLM_PORT=*) VLLM_PORT="${benchmark_arg#VLLM_PORT=}" ;;
        CONCURRENCY=*) CONCURRENCY="${benchmark_arg#CONCURRENCY=}" ;;
        DURATION=*) DURATION="${benchmark_arg#DURATION=}" ;;
        WRK_BIN=*) WRK_BIN="${benchmark_arg#WRK_BIN=}" ;;
        WRK2_BIN=*) WRK2_BIN="${benchmark_arg#WRK2_BIN=}" ;;
        BENCHMARK_MODE=*) BENCHMARK_MODE="${benchmark_arg#BENCHMARK_MODE=}" ;;
        RATE=*) RATE="${benchmark_arg#RATE=}" ;;
        RATES=*) RATES="${benchmark_arg#RATES=}" ;;
        VALIDATE_LOAD=*) VALIDATE_LOAD="${benchmark_arg#VALIDATE_LOAD=}" ;;
        INCLUDE_XDP=*) INCLUDE_XDP="${benchmark_arg#INCLUDE_XDP=}" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BENCHMARK_MODE="${BENCHMARK_MODE:-saturation}"
WRK2_LOCAL_BIN="${ROOT_DIR}/.tools/wrk2/wrk"
WRK2_BIN="${WRK2_BIN:-$WRK2_LOCAL_BIN}"
WRK_BIN="${WRK_BIN:-}"
DURATION="${DURATION:-30s}"
BASE_THREADS="${THREADS:-4}"
DEFAULT_CONCURRENCIES=(1 2 4 8 16 32 64 96 128 192 256 512)
RATE="${RATE:-10000}"
RATES="${RATES:-100 250 500 750 900}"
VALIDATE_LOAD="${VALIDATE_LOAD:-0}"
INCLUDE_XDP="${INCLUDE_XDP:-0}"
XDP_PORT="${XDP_PORT:-18081}"
CODING_BACKEND_PORT="${CODING_BACKEND_PORT:-18391}"
MATH_BACKEND_PORT="${MATH_BACKEND_PORT:-18392}"
OTHERS_BACKEND_PORT="${OTHERS_BACKEND_PORT:-18393}"
QA_BACKEND_PORT="${QA_BACKEND_PORT:-18394}"
WRITING_BACKEND_PORT="${WRITING_BACKEND_PORT:-18395}"
VLLM_BACKEND_PORT="${VLLM_BACKEND_PORT:-18396}"
START_VLLM_MOCK="${START_VLLM_MOCK:-0}"
VLLM_HOST="${VLLM_HOST:-vllm-sr-envoy-container}"
VLLM_PORT="${VLLM_PORT:-8899}"
# Set this explicitly when Docker DNS and the Docker CLI are both unavailable.
VLLM_IP="${VLLM_IP:-}"
IFNAME="${IFNAME:-veth0}"
NETNS="${NETNS:-ns1}"
XDP_PEER_IF="${XDP_PEER_IF:-veth1}"
XDP_URL="${XDP_URL:-http://10.10.0.1:${XDP_PORT}/v1/chat/completions}"
# Use a marker backend directly over the same ns1/veth path as the routers.
DIRECT_BACKEND_URL="${DIRECT_BACKEND_URL:-http://10.10.0.1:${CODING_BACKEND_PORT}/v1/chat/completions}"
# VLLM_URL is assigned after resolving VLLM_HOST from the root namespace. ns1
# reaches that address through veth0 with destination-scoped NAT below.
VLLM_URL="${VLLM_URL:-}"
REPORT_DIR="${ROOT_DIR}/results/routing-performance"

if [ "$EUID" -ne 0 ]; then
    echo "Routing benchmark uses sudo for cleanup and firewall setup. Elevating..."
    sudo_env=(
        WRK_BIN="$WRK_BIN"
        WRK2_BIN="$WRK2_BIN"
        BENCHMARK_MODE="$BENCHMARK_MODE"
        DURATION="$DURATION"
        THREADS="$BASE_THREADS"
        RATE="$RATE"
        RATES="$RATES"
        VALIDATE_LOAD="$VALIDATE_LOAD"
        INCLUDE_XDP="$INCLUDE_XDP"
        XDP_PORT="$XDP_PORT"
        CODING_BACKEND_PORT="$CODING_BACKEND_PORT"
        MATH_BACKEND_PORT="$MATH_BACKEND_PORT"
        OTHERS_BACKEND_PORT="$OTHERS_BACKEND_PORT"
        QA_BACKEND_PORT="$QA_BACKEND_PORT"
        WRITING_BACKEND_PORT="$WRITING_BACKEND_PORT"
        VLLM_BACKEND_PORT="$VLLM_BACKEND_PORT"
        START_VLLM_MOCK="$START_VLLM_MOCK"
        VLLM_HOST="$VLLM_HOST"
        VLLM_PORT="$VLLM_PORT"
        VLLM_IP="$VLLM_IP"
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
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
RAW_DIR="${REPORT_DIR}/raw/${RUN_ID}"
mkdir -p "$RAW_DIR"

if [ "$INCLUDE_XDP" != "0" ] && [ "$INCLUDE_XDP" != "1" ]; then
    echo "Error: INCLUDE_XDP must be 0 or 1." >&2
    exit 1
fi
if [ "$VALIDATE_LOAD" != "0" ] && [ "$VALIDATE_LOAD" != "1" ]; then
    echo "Error: VALIDATE_LOAD must be 0 or 1." >&2
    exit 1
fi

case "$BENCHMARK_MODE" in
    saturation)
        if [ -z "$WRK_BIN" ]; then WRK_BIN="wrk"; fi
        if ! command -v "$WRK_BIN" >/dev/null 2>&1; then
            echo "Error: saturation mode requires standard wrk; '${WRK_BIN}' is not available." >&2
            echo "Install wrk with your package manager, then retry 'sudo make performance'." >&2
            exit 1
        fi
        if [ "$(basename "$WRK_BIN")" = "wrk2" ]; then
            echo "Error: saturation mode requires standard wrk and will not substitute wrk2." >&2
            exit 1
        fi
        RATE_ARG=""
        ;;
    fixed-rate)
        if [ ! -x "$WRK2_BIN" ]; then
            if command -v "$WRK2_BIN" >/dev/null 2>&1; then
                WRK2_BIN="$(command -v "$WRK2_BIN")"
            else
                echo "Error: fixed-rate mode requires wrk2; '${WRK2_BIN}' is not available." >&2
                echo "Install the pinned local copy with: make install-wrk2" >&2
                echo "Or set WRK2_BIN=/path/to/wrk2 and retry 'sudo make performance-fixed-rate'." >&2
                exit 1
            fi
        fi
        WRK_BIN="$WRK2_BIN"
        ;;
    *)
        echo "Error: BENCHMARK_MODE must be 'saturation' or 'fixed-rate' (got '${BENCHMARK_MODE}')." >&2
        exit 1
        ;;
esac

if ! ip netns exec "$NETNS" ip link show dev "$XDP_PEER_IF" >/dev/null 2>&1; then
    echo "Error: ${NETNS}/${XDP_PEER_IF} is missing. Run 'make setup' first." >&2
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo "Error: curl is required to verify vLLM-SR backend routing." >&2
    exit 1
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

# The quick profile uses development instrumentation; paper runs switch to the
# production build in the repeated-trial runner added later.
echo "Building routing proxy and mock backends..."
make dev KEYWORD_POLICY=config/policy_ngram.yaml

# Flush old iptables rules for these ports
iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${QA_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${WRITING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true

# Add iptables rules
iptables -I INPUT 1 -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${QA_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${WRITING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
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

echo "Starting QA backend on port ${QA_BACKEND_PORT}..."
./benchmarks/mock_backend "${QA_BACKEND_PORT}" qa > /dev/null 2>&1 &
QA_MOCK_PID=$!

echo "Starting writing backend on port ${WRITING_BACKEND_PORT}..."
./benchmarks/mock_backend "${WRITING_BACKEND_PORT}" writing > /dev/null 2>&1 &
WRITING_MOCK_PID=$!

VLLM_MOCK_PID=""
if [ "$START_VLLM_MOCK" = "1" ]; then
    echo "Starting auxiliary mock HTTP backend for vLLM-SR on port ${VLLM_BACKEND_PORT}..."
    ./benchmarks/mock_backend "${VLLM_BACKEND_PORT}" others > /dev/null 2>&1 &
    VLLM_MOCK_PID=$!
fi

ROUTER_PID=""
VLLM_IF=""
VLLM_ROUTE_ADDED=0
VLLM_NAT_ADDED=0
VLLM_RAW_ACCEPT_ADDED=0
VLLM_FORWARD_OUT_ADDED=0
VLLM_FORWARD_RETURN_ADDED=0
IP_FORWARD_CHANGED=0
ORIGINAL_IP_FORWARD=""

wait_for_ns_port() {
    local host="$1"
    local port="$2"
    local name="$3"
    local deadline=$((SECONDS + 10))

    while [ "$SECONDS" -lt "$deadline" ]; do
        if timeout 1 ip netns exec "$NETNS" bash -c ":</dev/tcp/${host}/${port}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "Error: ${name} is not reachable from ${NETNS} at ${host}:${port} after 10 seconds." >&2
    return 1
}

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

setup_vllm_route() {
    if [ -z "$VLLM_IP" ]; then
        VLLM_IP="$(getent ahostsv4 "$VLLM_HOST" | awk 'NR == 1 { print $1 }')"
    fi
    # Docker DNS is only available to containers attached to the same Docker
    # network. When the benchmark is launched on the Docker host, query the
    # already-running Envoy's address as a metadata fallback; this neither
    # starts containers nor uses Docker-in-Docker.
    if [ -z "$VLLM_IP" ] && command -v docker >/dev/null 2>&1; then
        VLLM_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{if .IPAddress}}{{.IPAddress}}{{end}}{{end}}' "$VLLM_HOST" 2>/dev/null || true)"
    fi
    if [ -z "$VLLM_IP" ]; then
        echo "Error: could not resolve ${VLLM_HOST} to an IPv4 address. Set VLLM_IP explicitly if Docker DNS/CLI is unavailable." >&2
        return 1
    fi

    VLLM_IF="$(ip route get "$VLLM_IP" | awk '/ dev / { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
    if [ -z "$VLLM_IF" ]; then
        echo "Error: could not determine the interface used to reach ${VLLM_HOST} (${VLLM_IP})." >&2
        return 1
    fi

    ORIGINAL_IP_FORWARD="$(sysctl -n net.ipv4.ip_forward)"
    if [ "$ORIGINAL_IP_FORWARD" != "1" ]; then
        sysctl -w net.ipv4.ip_forward=1 >/dev/null
        IP_FORWARD_CHANGED=1
    fi

    if ! ip netns exec "$NETNS" ip route show exact "${VLLM_IP}/32" | grep -q .; then
        ip netns exec "$NETNS" ip route add "${VLLM_IP}/32" via 10.10.0.1 dev "$XDP_PEER_IF"
        VLLM_ROUTE_ADDED=1
    fi

    # Docker protects container IPs with raw/PREROUTING DROP rules before the
    # FORWARD chain. Permit only ns1's TCP traffic to this Envoy endpoint so
    # the scoped FORWARD and NAT rules below can process it.
    if ! iptables -t raw -C PREROUTING -i "$IFNAME" -s 10.10.0.0/24 -d "$VLLM_IP" -p tcp --dport "$VLLM_PORT" -j ACCEPT 2>/dev/null; then
        iptables -t raw -I PREROUTING 1 -i "$IFNAME" -s 10.10.0.0/24 -d "$VLLM_IP" -p tcp --dport "$VLLM_PORT" -j ACCEPT
        VLLM_RAW_ACCEPT_ADDED=1
    fi
    if ! iptables -t nat -C POSTROUTING -s 10.10.0.0/24 -d "$VLLM_IP" -o "$VLLM_IF" -j MASQUERADE 2>/dev/null; then
        iptables -t nat -A POSTROUTING -s 10.10.0.0/24 -d "$VLLM_IP" -o "$VLLM_IF" -j MASQUERADE
        VLLM_NAT_ADDED=1
    fi
    if ! iptables -C FORWARD -s 10.10.0.0/24 -d "$VLLM_IP" -o "$VLLM_IF" -p tcp --dport "$VLLM_PORT" -j ACCEPT 2>/dev/null; then
        iptables -I FORWARD 1 -s 10.10.0.0/24 -d "$VLLM_IP" -o "$VLLM_IF" -p tcp --dport "$VLLM_PORT" -j ACCEPT
        VLLM_FORWARD_OUT_ADDED=1
    fi
    if ! iptables -C FORWARD -s "$VLLM_IP" -d 10.10.0.0/24 -i "$VLLM_IF" -p tcp --sport "$VLLM_PORT" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; then
        iptables -I FORWARD 1 -s "$VLLM_IP" -d 10.10.0.0/24 -i "$VLLM_IF" -p tcp --sport "$VLLM_PORT" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
        VLLM_FORWARD_RETURN_ADDED=1
    fi

    if [ -z "$VLLM_URL" ]; then
        VLLM_URL="http://${VLLM_IP}:${VLLM_PORT}/v1/chat/completions"
    fi
    wait_for_ns_port "$VLLM_IP" "$VLLM_PORT" "vLLM-SR Envoy (${VLLM_HOST})"
}

verify_vllm_backend_routing() {
    local expected prompt response

    echo "Verifying vLLM-SR routes reach distinct marker backends..."
    while IFS='|' read -r expected prompt; do
        response=$(ip netns exec "$NETNS" curl --silent --show-error --fail \
            --max-time 10 -H 'Content-Type: application/json' \
            --data "{\"model\":\"MoM\",\"messages\":[{\"role\":\"user\",\"content\":\"${prompt}\"}]}" \
            "$VLLM_URL") || {
            echo "Error: vLLM-SR preflight request for ${expected} failed." >&2
            return 1
        }
        if ! grep -Fq "\"backend\":\"${expected}\"" <<<"$response"; then
            echo "Error: vLLM-SR preflight expected backend=${expected}, got: ${response}" >&2
            return 1
        fi
    done <<'EOF'
coding|write a python function
math|calculate the derivative of x squared
qa|what is the capital of France?
writing|write a short poem about rain
others|tell me a short story
EOF
}

cleanup() {
    echo ""
    echo "Cleaning up processes and network rules..."
    for pid in "$ROUTER_PID" "$CODING_MOCK_PID" "$MATH_MOCK_PID" "$OTHERS_MOCK_PID" "$QA_MOCK_PID" "$WRITING_MOCK_PID" "$VLLM_MOCK_PID"; do
        if [ -n "$pid" ]; then
            kill -9 "$pid" >/dev/null 2>&1 || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${QA_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${WRITING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    if [ "$VLLM_NAT_ADDED" = "1" ]; then
        iptables -t nat -D POSTROUTING -s 10.10.0.0/24 -d "$VLLM_IP" -o "$VLLM_IF" -j MASQUERADE >/dev/null 2>&1 || true
    fi
    if [ "$VLLM_RAW_ACCEPT_ADDED" = "1" ]; then
        iptables -t raw -D PREROUTING -i "$IFNAME" -s 10.10.0.0/24 -d "$VLLM_IP" -p tcp --dport "$VLLM_PORT" -j ACCEPT >/dev/null 2>&1 || true
    fi
    if [ "$VLLM_FORWARD_OUT_ADDED" = "1" ]; then
        iptables -D FORWARD -s 10.10.0.0/24 -d "$VLLM_IP" -o "$VLLM_IF" -p tcp --dport "$VLLM_PORT" -j ACCEPT >/dev/null 2>&1 || true
    fi
    if [ "$VLLM_FORWARD_RETURN_ADDED" = "1" ]; then
        iptables -D FORWARD -s "$VLLM_IP" -d 10.10.0.0/24 -i "$VLLM_IF" -p tcp --sport "$VLLM_PORT" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT >/dev/null 2>&1 || true
    fi
    if [ "$VLLM_ROUTE_ADDED" = "1" ]; then
        ip netns exec "$NETNS" ip route del "${VLLM_IP}/32" via 10.10.0.1 dev "$XDP_PEER_IF" >/dev/null 2>&1 || true
    fi
    if [ "$IP_FORWARD_CHANGED" = "1" ]; then
        sysctl -w "net.ipv4.ip_forward=${ORIGINAL_IP_FORWARD}" >/dev/null 2>&1 || true
    fi
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
    local mode="${1:-proxy}"

    echo "Starting routing proxy (${mode})..."
    if [ "$mode" = "sockmap" ]; then
        SK_ROUTER_MODE=sockmap ./sk_router > /tmp/sk_router_wrk.log 2>&1 &
    else
        ./sk_router > /tmp/sk_router_wrk.log 2>&1 &
    fi
    ROUTER_PID=$!
    wait_for_port "$XDP_PORT" "routing frontend"
    if ! wait_for_ns_port "10.10.0.1" "$XDP_PORT" "routing frontend"; then
        echo "sk_router log:" >&2
        cat /tmp/sk_router_wrk.log >&2
        return 1
    fi
}

verify_router_backend_routing() {
    local name="$1"
    local expected prompt response

    echo "Verifying ${name} reaches distinct marker backends..."
    while IFS='|' read -r expected prompt; do
        response=$(ip netns exec "$NETNS" curl --silent --show-error --fail \
            --max-time 10 -H 'Content-Type: application/json' \
            --data "{\"model\":\"MoM\",\"messages\":[{\"role\":\"user\",\"content\":\"${prompt}\"}]}" \
            "$XDP_URL") || {
            echo "Error: ${name} preflight request for ${expected} failed." >&2
            return 1
        }
        if ! grep -Fq "\"backend\":\"${expected}\"" <<<"$response"; then
            echo "Error: ${name} preflight expected backend=${expected}, got: ${response}" >&2
            return 1
        fi
    done <<'EOF'
coding|write a python function
math|calculate the derivative of x squared
qa|what is the capital of France?
writing|write a short poem about rain
others|tell me a short story
EOF
}

validate_untimed_load() {
    local name="$1"
    local url="$2"
    if [ "$VALIDATE_LOAD" = "1" ]; then
        echo "Running untimed concurrent load validation for ${name}..."
        python3 "${SCRIPT_DIR}/validate_load.py" --url "$url" > "${RAW_DIR}/${name//[^a-zA-Z0-9]/_}.load-validation.txt"
    fi
}

stop_routing_proxy() {
    if [ -n "$ROUTER_PID" ]; then
        kill -9 "$ROUTER_PID" >/dev/null 2>&1 || true
        wait "$ROUTER_PID" 2>/dev/null || true
        ROUTER_PID=""
    fi
}

run_wrk() {
    local output status raw_file reason_file reason
    raw_file="${RAW_DIR}/${3}.txt"
    reason_file="${RAW_DIR}/${3}.invalid.txt"
    set +e
    output=$(ip netns exec "$NETNS" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s "${SCRIPT_DIR}/prompts.lua" "$1" 2>&1)
    status=$?
    set -e
    printf '%s\n' "$output" > "$raw_file"
    printf '%s\n' "$output"
    if [ "$status" -ne 0 ]; then
        printf 'tool exit status=%s\n' "$status" > "$reason_file"
        echo "Error: ${WRK_BIN} failed for $2 (exit ${status})." >&2
        return "$status"
    fi
    if ! reason=$(python3 "${SCRIPT_DIR}/validate_output.py" --input "$raw_file"); then
        printf '%s\n' "$reason" > "$reason_file"
        echo "Error: invalid ${WRK_BIN} run for $2: ${reason}. Raw output: ${raw_file}" >&2
        return 1
    fi
}

run_benchmark() {
    local route_count=3
    local step=1

    if [ "$INCLUDE_XDP" = "1" ]; then
        route_count=4
    fi

    echo "# Routing Performance Benchmark Results"
    echo ""
    echo "- Timestamp: \`$(date)\`"
    echo "- Tool: \`${WRK_BIN}\`"
    echo "- Mode: \`${BENCHMARK_MODE}\`"
    echo "- Timed response-body validation: \`disabled\` (routing correctness is measured separately)"
    echo "- Threads: \`${THREADS}\`"
    echo "- Connections: \`${CONCURRENCY}\`"
    echo "- Duration: \`${DURATION}\`"
    if [ "$BENCHMARK_MODE" = "fixed-rate" ]; then
        echo "- Target Rate: \`${RATE} RPS\`"
        RATE_ARG="-R ${RATE}"
    else
        RATE_ARG=""
    fi
    echo ""
    echo "- Routing backend ports: coding=\`${CODING_BACKEND_PORT}\`, math=\`${MATH_BACKEND_PORT}\`, qa=\`${QA_BACKEND_PORT}\`, writing=\`${WRITING_BACKEND_PORT}\`, others=\`${OTHERS_BACKEND_PORT}\`"
    echo ""
    echo "## [${step}/${route_count}] Direct Backend"
    echo "\`\`\`"
    # No route decision occurs for the control. XDP was detached before this
    # measurement began.
    run_wrk "$DIRECT_BACKEND_URL" "direct backend" "direct"
    echo "\`\`\`"
    echo ""
    step=$((step + 1))

    if [ "$INCLUDE_XDP" = "1" ]; then
        start_routing_proxy proxy

        echo "## [${step}/${route_count}] XSR (legacy) Route"
        echo "\`\`\`"
        run_wrk "$XDP_URL" "XSR (legacy) route" "xsr-legacy"
        echo "\`\`\`"
        echo ""
        stop_routing_proxy
        step=$((step + 1))
    fi

    start_routing_proxy sockmap
    verify_router_backend_routing "XSR"
    validate_untimed_load "xsr" "$XDP_URL"
    echo "## [${step}/${route_count}] XSR Route"
    echo "\`\`\`"
    run_wrk "$XDP_URL" "XSR route" "xsr"
    echo "\`\`\`"
    echo ""
    stop_routing_proxy
    step=$((step + 1))

    echo "## [${step}/${route_count}] vLLM-SR Route"
    echo "\`\`\`"
    validate_untimed_load "vsr" "$VLLM_URL"
    run_wrk "$VLLM_URL" "vLLM-SR route" "vsr"
    echo "\`\`\`"
}

if [ "${CONCURRENCY+x}" = "x" ]; then
    CONCURRENCIES=("$CONCURRENCY")
else
    CONCURRENCIES=("${DEFAULT_CONCURRENCIES[@]}")
fi

if [ "$BENCHMARK_MODE" = "fixed-rate" ]; then
    RATE_VALUES=( $RATES )
else
    RATE_VALUES=( "$RATE" )
fi

for RATE in "${RATE_VALUES[@]}"; do
for CONCURRENCY in "${CONCURRENCIES[@]}"; do
    # Restore the configured thread count for every sweep entry: a low initial
    # concurrency must not clamp the thread count of subsequent runs.
    THREADS="$BASE_THREADS"
    if [ "$THREADS" -gt "$CONCURRENCY" ]; then
        THREADS="$CONCURRENCY"
    fi

    if [ "$BENCHMARK_MODE" = "fixed-rate" ]; then
        REPORT_FILE="${REPORT_DIR}/routing_fixed_rate_${RATE}_concurrency_${CONCURRENCY}.md"
    else
        REPORT_FILE="${REPORT_DIR}/routing_performance_${CONCURRENCY}.md"
    fi

    # The preceding routing run leaves a classifier and router behind. Remove
    # both before each direct control measurement.
    stop_routing_proxy
    detach_xdp
    wait_for_ns_port "10.10.0.1" "$CODING_BACKEND_PORT" "coding mock backend"
    wait_for_ns_port "10.10.0.1" "$MATH_BACKEND_PORT" "math mock backend"
    wait_for_ns_port "10.10.0.1" "$OTHERS_BACKEND_PORT" "others mock backend"
    wait_for_ns_port "10.10.0.1" "$QA_BACKEND_PORT" "QA mock backend"
    wait_for_ns_port "10.10.0.1" "$WRITING_BACKEND_PORT" "writing mock backend"
    setup_vllm_route
    verify_vllm_backend_routing
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

    echo ""
    echo "================================================================="
    echo " Benchmark complete! Results saved to:"
    echo "   - ${REPORT_FILE}"
    echo "================================================================="
done
done

if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:" "$REPORT_DIR" 2>/dev/null || true
fi
