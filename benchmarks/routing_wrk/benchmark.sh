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
        WARMUP_DURATION=*) WARMUP_DURATION="${benchmark_arg#WARMUP_DURATION=}" ;;
        TRIALS=*) TRIALS="${benchmark_arg#TRIALS=}" ;;
        BENCHMARK_PROFILE=*) BENCHMARK_PROFILE="${benchmark_arg#BENCHMARK_PROFILE=}" ;;
        RANDOM_SEED=*) RANDOM_SEED="${benchmark_arg#RANDOM_SEED=}" ;;
        BENCHMARK_DRY_RUN=*) BENCHMARK_DRY_RUN="${benchmark_arg#BENCHMARK_DRY_RUN=}" ;;
        WRK_BIN=*) WRK_BIN="${benchmark_arg#WRK_BIN=}" ;;
        WRK2_BIN=*) WRK2_BIN="${benchmark_arg#WRK2_BIN=}" ;;
        BENCHMARK_MODE=*) BENCHMARK_MODE="${benchmark_arg#BENCHMARK_MODE=}" ;;
        RATE=*) RATE="${benchmark_arg#RATE=}" ;;
        RATES=*) RATES="${benchmark_arg#RATES=}" ;;
        VALIDATE_LOAD=*) VALIDATE_LOAD="${benchmark_arg#VALIDATE_LOAD=}" ;;
        INCLUDE_XDP=*) INCLUDE_XDP="${benchmark_arg#INCLUDE_XDP=}" ;;
        KEYWORD_POLICY=*) KEYWORD_POLICY="${benchmark_arg#KEYWORD_POLICY=}" ;;
        INCLUDE_STRESS=*) INCLUDE_STRESS="${benchmark_arg#INCLUDE_STRESS=}" ;;
        BENCHMARK_SYSTEMS=*) BENCHMARK_SYSTEMS="${benchmark_arg#BENCHMARK_SYSTEMS=}" ;;
        LLMROUTER_CONFIG=*) LLMROUTER_CONFIG="${benchmark_arg#LLMROUTER_CONFIG=}" ;;
        LLMROUTER_PORT=*) LLMROUTER_PORT="${benchmark_arg#LLMROUTER_PORT=}" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${PYTHON:-${ROOT_DIR}/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ] && ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Error: benchmark Python is unavailable; run 'make benchmark-install' first." >&2
    exit 1
fi

BENCHMARK_MODE="${BENCHMARK_MODE:-saturation}"
WRK2_LOCAL_BIN="${ROOT_DIR}/.tools/wrk2/wrk"
WRK2_BIN="${WRK2_BIN:-$WRK2_LOCAL_BIN}"
WRK_LOCAL_BIN="${ROOT_DIR}/.tools/wrk/wrk"
WRK_BIN="${WRK_BIN:-}"
BENCHMARK_PROFILE="${BENCHMARK_PROFILE:-quick}"
case "$BENCHMARK_PROFILE" in
    quick) PROFILE_TRIALS=1; PROFILE_DURATION=5s; PROFILE_WARMUP=1s ;;
    paper) PROFILE_TRIALS=5; PROFILE_DURATION=40s; PROFILE_WARMUP=3s ;;
    *) echo "Error: BENCHMARK_PROFILE must be 'quick' or 'paper'." >&2; exit 1 ;;
esac
TRIALS="${TRIALS:-$PROFILE_TRIALS}"
DURATION="${DURATION:-$PROFILE_DURATION}"
WARMUP_DURATION="${WARMUP_DURATION:-$PROFILE_WARMUP}"
RANDOM_SEED="${RANDOM_SEED:-20260826}"
BENCHMARK_DRY_RUN="${BENCHMARK_DRY_RUN:-0}"
BASE_THREADS="${THREADS:-4}"
DEFAULT_CONCURRENCIES=(1 2 4 8 16 32 64 96 128 192)
STRESS_CONCURRENCIES=(256 512)
RATE="${RATE:-10000}"
RATES="${RATES:-100 250 500 750 900}"
VALIDATE_LOAD="${VALIDATE_LOAD:-0}"
TOPOLOGY_MODE="${TOPOLOGY_MODE:-host}"
INCLUDE_XDP="${INCLUDE_XDP:-0}"
INCLUDE_STRESS="${INCLUDE_STRESS:-0}"
BENCHMARK_SYSTEMS="${BENCHMARK_SYSTEMS:-}"
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
LLMROUTER_PYTHON="${LLMROUTER_PYTHON:-${ROOT_DIR}/.venv-llmrouter/bin/python}"
LLMROUTER_BIN="${LLMROUTER_BIN:-${ROOT_DIR}/.venv-llmrouter/bin/llmrouter}"
LLMROUTER_PORT="${LLMROUTER_PORT:-18083}"
LLMROUTER_URL="${LLMROUTER_URL:-http://10.10.0.1:${LLMROUTER_PORT}/v1/chat/completions}"
LLMROUTER_START_TIMEOUT="${LLMROUTER_START_TIMEOUT:-60}"
LLMROUTER_PLUGIN_DIR="${LLMROUTER_PLUGIN_DIR:-${ROOT_DIR}/benchmarks/llmrouter/custom_routers}"
LLMROUTER_SERVE_CONFIG="${LLMROUTER_SERVE_CONFIG:-${ROOT_DIR}/benchmarks/llmrouter/configs/serve-local.yaml}"
LLMROUTER_SERVE_SCRIPT="${LLMROUTER_SERVE_SCRIPT:-${ROOT_DIR}/benchmarks/llmrouter/serve_benchmark.py}"
LLMROUTER_CONFIG="${LLMROUTER_CONFIG:-}"
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
ENVOY_ONLY_PORT="${ENVOY_ONLY_PORT:-8898}"
ENVOY_ONLY_CONTAINER="${ENVOY_ONLY_CONTAINER:-xsr-benchmark-envoy-only-${RUN_ID:-$$}}"
ENVOY_ONLY_URL="${ENVOY_ONLY_URL:-}"
REPORT_DIR="${ROOT_DIR}/results/routing-performance"
KEYWORD_POLICY="${KEYWORD_POLICY:-${ROOT_DIR}/config/policy_ngram.yaml}"

if [ "$EUID" -ne 0 ] && [ "$BENCHMARK_DRY_RUN" != "1" ]; then
    echo "Routing benchmark uses sudo for cleanup and firewall setup. Elevating..."
    sudo_env=(
        PYTHON="$PYTHON_BIN"
        WRK_BIN="$WRK_BIN"
        WRK2_BIN="$WRK2_BIN"
        BENCHMARK_MODE="$BENCHMARK_MODE"
        BENCHMARK_PROFILE="$BENCHMARK_PROFILE"
        TRIALS="$TRIALS"
        DURATION="$DURATION"
        WARMUP_DURATION="$WARMUP_DURATION"
        RANDOM_SEED="$RANDOM_SEED"
        BENCHMARK_DRY_RUN="$BENCHMARK_DRY_RUN"
        THREADS="$BASE_THREADS"
        RATE="$RATE"
        RATES="$RATES"
        VALIDATE_LOAD="$VALIDATE_LOAD"
        TOPOLOGY_MODE="$TOPOLOGY_MODE"
        INCLUDE_XDP="$INCLUDE_XDP"
        KEYWORD_POLICY="$KEYWORD_POLICY"
        INCLUDE_STRESS="$INCLUDE_STRESS"
        BENCHMARK_SYSTEMS="$BENCHMARK_SYSTEMS"
        BENCHMARK_PYTHON="$PYTHON_BIN"
        LLMROUTER_PYTHON="$LLMROUTER_PYTHON"
        LLMROUTER_BIN="$LLMROUTER_BIN"
        LLMROUTER_PORT="$LLMROUTER_PORT"
        LLMROUTER_URL="$LLMROUTER_URL"
        LLMROUTER_START_TIMEOUT="$LLMROUTER_START_TIMEOUT"
        LLMROUTER_PLUGIN_DIR="$LLMROUTER_PLUGIN_DIR"
        LLMROUTER_SERVE_CONFIG="$LLMROUTER_SERVE_CONFIG"
        LLMROUTER_SERVE_SCRIPT="$LLMROUTER_SERVE_SCRIPT"
        LLMROUTER_CONFIG="$LLMROUTER_CONFIG"
        XSR_DISTILL_MODEL="${XSR_DISTILL_MODEL:-}"
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
        ENVOY_ONLY_PORT="$ENVOY_ONLY_PORT"
        ENVOY_ONLY_CONTAINER="$ENVOY_ONLY_CONTAINER"
        ENVOY_ONLY_URL="$ENVOY_ONLY_URL"
    )
    # Only propagate CONCURRENCY when the caller supplied it. Otherwise the
    # elevated invocation must retain the default full sweep.
    if [ "${CONCURRENCY+x}" = "x" ]; then
        sudo_env+=(CONCURRENCY="$CONCURRENCY")
    fi
    exec sudo env "${sudo_env[@]}" "$0" "$@"
fi

cd "$ROOT_DIR"

if [ "$INCLUDE_XDP" != "0" ] && [ "$INCLUDE_XDP" != "1" ]; then
    echo "Error: INCLUDE_XDP must be 0 or 1." >&2
    exit 1
fi
if [ "$INCLUDE_STRESS" != "0" ] && [ "$INCLUDE_STRESS" != "1" ]; then
    echo "Error: INCLUDE_STRESS must be 0 or 1." >&2
    exit 1
fi
if [ "$VALIDATE_LOAD" != "0" ] && [ "$VALIDATE_LOAD" != "1" ]; then
    echo "Error: VALIDATE_LOAD must be 0 or 1." >&2
    exit 1
fi
if ! [[ "$TRIALS" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: TRIALS must be a positive integer." >&2
    exit 1
fi
if [ "$TOPOLOGY_MODE" = "docker-parity" ]; then
    echo "Error: TOPOLOGY_MODE=docker-parity is not supported; see benchmarks/routing_wrk/TOPOLOGY.md." >&2
    exit 1
fi
if [ "$TOPOLOGY_MODE" != "host" ]; then
    echo "Error: TOPOLOGY_MODE must be 'host' (docker-parity is intentionally rejected)." >&2
    exit 1
fi

DEFAULT_SYSTEMS=(direct envoy-only xsr vsr llmrouter)
if [ -n "$BENCHMARK_SYSTEMS" ]; then
    IFS=',' read -r -a SELECTED_SYSTEMS <<< "$BENCHMARK_SYSTEMS"
else
    SELECTED_SYSTEMS=("${DEFAULT_SYSTEMS[@]}")
    [ "$INCLUDE_XDP" = "1" ] && SELECTED_SYSTEMS+=(xsr-legacy)
fi
declare -A SEEN_SYSTEMS=()
for system in "${SELECTED_SYSTEMS[@]}"; do
    case "$system" in
        direct|envoy-only|xsr|vsr|llmrouter) ;;
        xsr-legacy)
            if [ "$INCLUDE_XDP" != "1" ]; then
                echo "Error: BENCHMARK_SYSTEMS=xsr-legacy requires INCLUDE_XDP=1." >&2
                exit 1
            fi
            ;;
        *)
            echo "Error: unsupported BENCHMARK_SYSTEMS entry '${system}'; use direct,envoy-only,xsr,vsr,llmrouter or xsr-legacy." >&2
            exit 1
            ;;
    esac
    if [ "${SEEN_SYSTEMS[$system]+x}" = "x" ]; then
        echo "Error: duplicate BENCHMARK_SYSTEMS entry '${system}'." >&2
        exit 1
    fi
    SEEN_SYSTEMS[$system]=1
done
SELECTED_SYSTEMS_CSV="$(IFS=,; echo "${SELECTED_SYSTEMS[*]}")"

system_selected() {
    [ "${SEEN_SYSTEMS[$1]+x}" = "x" ]
}

if ! [ "${SEEN_SYSTEMS[xsr]+x}" = "x" ]; then
    XSR_WARMUP_LIFECYCLE="not-selected"
    XSR_MEASURED_INSTANCE_WARMED="not-applicable"
elif [ "$WARMUP_DURATION" = "0" ] || [ "$WARMUP_DURATION" = "0s" ]; then
    XSR_WARMUP_LIFECYCLE="disabled"
    XSR_MEASURED_INSTANCE_WARMED="false"
else
    XSR_WARMUP_LIFECYCLE="router-restart-after-load-warmup"
    XSR_MEASURED_INSTANCE_WARMED="false"
fi

if [ "$INCLUDE_STRESS" = "1" ]; then
    DEFAULT_CONCURRENCIES+=("${STRESS_CONCURRENCIES[@]}")
fi

case "$BENCHMARK_MODE" in
    saturation)
        if [ -z "$WRK_BIN" ]; then
            WRK_BIN="$([ -x "$WRK_LOCAL_BIN" ] && printf '%s' "$WRK_LOCAL_BIN" || printf 'wrk')"
        fi
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

if system_selected llmrouter && [ -z "$LLMROUTER_CONFIG" ]; then
    if grep -Eq '^[[:space:]]*method:[[:space:]]*bm25([[:space:]]|$)' "$KEYWORD_POLICY"; then
        LLMROUTER_CONFIG="${ROOT_DIR}/benchmarks/llmrouter/configs/bm25.yaml"
    elif grep -Eq '^[[:space:]]*method:[[:space:]]*ngram([[:space:]]|$)' "$KEYWORD_POLICY"; then
        LLMROUTER_CONFIG="${ROOT_DIR}/benchmarks/llmrouter/configs/ngram.yaml"
    else
        echo "Error: cannot infer an LLMRouter adapter config from ${KEYWORD_POLICY}; set LLMROUTER_CONFIG explicitly." >&2
        exit 1
    fi
fi

if [ "$BENCHMARK_DRY_RUN" = "1" ]; then
    printf 'profile=%s trials=%s duration=%s warmup_duration=%s build_profile=%s mode=%s tool=%s concurrencies=%q include_stress=%s systems=%s llmrouter_config=%s\n' \
        "$BENCHMARK_PROFILE" "$TRIALS" "$DURATION" "$WARMUP_DURATION" \
        "$([ "$BENCHMARK_PROFILE" = paper ] && echo prod || echo dev)" "$BENCHMARK_MODE" "$WRK_BIN" \
        "${CONCURRENCY:-${DEFAULT_CONCURRENCIES[*]}}" "$INCLUDE_STRESS" "$SELECTED_SYSTEMS_CSV" "${LLMROUTER_CONFIG:-not-selected}"
    exit 0
fi

BENCHMARK_SYSTEMS="$SELECTED_SYSTEMS_CSV" BENCHMARK_PYTHON="$PYTHON_BIN" \
    CC="${CC:-cc}" \
    LLMROUTER_PYTHON="$LLMROUTER_PYTHON" LLMROUTER_BIN="$LLMROUTER_BIN" \
    VLLM_HOST="$VLLM_HOST" "${SCRIPT_DIR}/check_environments.sh"

mkdir -p "$REPORT_DIR"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
RUN_ROOT="${REPORT_DIR}/${RUN_ID}"
RAW_DIR="${RUN_ROOT}/raw"
mkdir -p "$RAW_DIR"
"$PYTHON_BIN" "${SCRIPT_DIR}/manifest.py" --path "${RUN_ROOT}/manifest.json" --run-id "$RUN_ID" --profile "$BENCHMARK_PROFILE" \
    --mode "$BENCHMARK_MODE" --trials "$TRIALS" --duration "$DURATION" --warmup-duration "$WARMUP_DURATION" --seed "$RANDOM_SEED" \
    --systems "$SELECTED_SYSTEMS_CSV" --include-stress "$INCLUDE_STRESS" \
    --xsr-warmup-lifecycle "$XSR_WARMUP_LIFECYCLE"

# Generate prompts before metadata capture so a fresh clone records the exact
# workload hash, count, and route distribution used by the run.
if [ ! -f "benchmarks/dataset_prompts.jsonl" ] || ! head -n 1 benchmarks/dataset_prompts.jsonl | grep -q '"x_expected_route"'; then
    echo "Generating dataset_prompts.jsonl..."
    "$PYTHON_BIN" "${SCRIPT_DIR}/export_prompts.py" --config "$KEYWORD_POLICY"
fi

"$PYTHON_BIN" "${SCRIPT_DIR}/collect_metadata.py" --output "${RUN_ROOT}/metadata.json" --mode "$BENCHMARK_MODE" \
    --profile "$BENCHMARK_PROFILE" --trials "$TRIALS" --duration "$DURATION" --warmup-duration "$WARMUP_DURATION" \
    --concurrency "${CONCURRENCY:-${DEFAULT_CONCURRENCIES[*]}}" --rates "$RATES" --wrk-bin "$WRK_BIN" --wrk2-bin "$WRK2_BIN" \
    --systems "$SELECTED_SYSTEMS_CSV" --include-stress "$INCLUDE_STRESS" \
    --xsr-warmup-lifecycle "$XSR_WARMUP_LIFECYCLE" --xsr-measured-instance-warmed "$XSR_MEASURED_INSTANCE_WARMED" \
    --vllm-container "$VLLM_HOST" --vsr-container "${VSR_CONTAINER:-${VLLM_HOST/envoy/router}}" \
    --llmrouter-python "$LLMROUTER_PYTHON" --llmrouter-bin "$LLMROUTER_BIN" --llmrouter-config "${LLMROUTER_CONFIG:-}" \
    --policy "$KEYWORD_POLICY" --prompts "${ROOT_DIR}/benchmarks/dataset_prompts.jsonl"

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

echo "Building routing proxy and mock backends..."
make benchmarks/mock_backend
if system_selected xsr; then
    if [ "$BENCHMARK_PROFILE" = "paper" ]; then
        make KEYWORD_POLICY="$KEYWORD_POLICY" prod
    else
        make KEYWORD_POLICY="$KEYWORD_POLICY" dev
    fi
fi
if [ "$INCLUDE_XDP" = "1" ]; then
    make KEYWORD_POLICY="$KEYWORD_POLICY" legacy
fi

# Flush old iptables rules for these ports
iptables -D INPUT -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${QA_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${WRITING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -D INPUT -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
if system_selected llmrouter; then
    iptables -D INPUT -p tcp --dport "${LLMROUTER_PORT}" -j ACCEPT >/dev/null 2>&1 || true
fi

# Add iptables rules
iptables -I INPUT 1 -p tcp --dport "${XDP_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${CODING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${MATH_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${OTHERS_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${QA_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${WRITING_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
iptables -I INPUT 1 -p tcp --dport "${VLLM_BACKEND_PORT}" -j ACCEPT >/dev/null 2>&1 || true
if system_selected llmrouter; then
    iptables -I INPUT 1 -p tcp --dport "${LLMROUTER_PORT}" -j ACCEPT >/dev/null 2>&1 || true
fi

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
ROUTER_LOG="/tmp/sk_router_wrk.log"
LLMROUTER_PID=""
LLMROUTER_LOG="${RUN_ROOT}/raw/llmrouter-server.log"
VLLM_IF=""
ENVOY_ONLY_IP=""
ENVOY_ONLY_IF=""
ENVOY_ONLY_ROUTE_ADDED=0
ENVOY_ONLY_NAT_ADDED=0
ENVOY_ONLY_RAW_ACCEPT_ADDED=0
ENVOY_ONLY_FORWARD_OUT_ADDED=0
ENVOY_ONLY_FORWARD_RETURN_ADDED=0
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
    local timeout_seconds="${4:-10}"
    local deadline=$((SECONDS + timeout_seconds))

    while [ "$SECONDS" -lt "$deadline" ]; do
        if timeout 1 ip netns exec "$NETNS" bash -c ":</dev/tcp/${host}/${port}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done

    echo "Error: ${name} is not reachable from ${NETNS} at ${host}:${port} after ${timeout_seconds} seconds." >&2
    return 1
}

wait_for_router_ready() {
    local name="$1"
    local deadline=$((SECONDS + 10))

    while [ "$SECONDS" -lt "$deadline" ]; do
        if ! kill -0 "$ROUTER_PID" >/dev/null 2>&1; then
            echo "Error: sk_router exited before ${name} opened:"
            cat "$ROUTER_LOG"
            exit 1
        fi
        # A TCP readiness connection allocates a six-socket SOCKMAP set which
        # this router cannot yet reap. Use the startup log so readiness itself
        # does not contaminate the measured instance with stale sockets.
        if grep -Eq '(SK_SKB router|XDP-classified routing proxy) listening' "$ROUTER_LOG" 2>/dev/null; then
            return 0
        fi
        sleep 0.1
    done

    echo "Error: ${name} did not report ready; router log:"
    cat "$ROUTER_LOG"
    exit 1
}

start_llmrouter() {
    echo "Starting LLMRouter baseline..."
    mkdir -p "$(dirname "$LLMROUTER_LOG")"
    LLMROUTER_PLUGINS="$LLMROUTER_PLUGIN_DIR" \
        "$LLMROUTER_PYTHON" "$LLMROUTER_SERVE_SCRIPT" \
        --config "$LLMROUTER_SERVE_CONFIG" \
        --router xsr_reference \
        --router-config "$LLMROUTER_CONFIG" \
        --host 0.0.0.0 \
        --port "$LLMROUTER_PORT" > "$LLMROUTER_LOG" 2>&1 &
    LLMROUTER_PID=$!
    if ! wait_for_ns_port "10.10.0.1" "$LLMROUTER_PORT" "LLMRouter baseline" "$LLMROUTER_START_TIMEOUT"; then
        cat "$LLMROUTER_LOG" >&2 || true
        return 1
    fi
}

verify_llmrouter_backend_routing() {
    local expected prompt response

    echo "Verifying LLMRouter routes reach distinct marker backends..."
    while IFS='|' read -r expected prompt; do
        response=$(ip netns exec "$NETNS" curl --silent --show-error --fail \
            --max-time 10 -H 'Content-Type: application/json' \
            --data "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"${prompt}\"}]}" \
            "$LLMROUTER_URL") || {
            echo "Error: LLMRouter preflight request for ${expected} failed." >&2
            return 1
        }
        # Upstream normalizes backend responses into its OpenAI response model,
        # dropping the mock backend's custom `backend` property. It sets the
        # selected backend name in the standard `model` field after forwarding.
        if ! grep -Fq "\"model\":\"${expected}\"" <<<"$response"; then
            echo "Error: LLMRouter preflight expected model=${expected}, got: ${response}" >&2
            return 1
        fi
    done <<'EOF'
coding|write a python function
math|calculate the derivative of x squared
qa|answer this question: what is the capital of France?
writing|write a short poem about rain
others|tell me a short story
EOF
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

start_envoy_only() {
    local network gateway image config
    command -v docker >/dev/null 2>&1 || { echo "Error: Docker is required for the Envoy-only benchmark baseline." >&2; return 1; }
    network="$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$VLLM_HOST" 2>/dev/null | head -n1)"
    [ -n "$network" ] || { echo "Error: could not determine Docker network for ${VLLM_HOST}." >&2; return 1; }
    gateway="$(docker network inspect -f '{{(index .IPAM.Config 0).Gateway}}' "$network" 2>/dev/null)"
    [ -n "$gateway" ] || { echo "Error: could not determine Docker gateway for ${network}." >&2; return 1; }
    image="${VLLM_ENVOY_IMAGE:-$(docker inspect -f '{{.Config.Image}}' "$VLLM_HOST" 2>/dev/null)}"
    [ -n "$image" ] || { echo "Error: could not determine Envoy image for ${VLLM_HOST}." >&2; return 1; }
    config="${RAW_DIR}/envoy-only.json"
    "$PYTHON_BIN" "${SCRIPT_DIR}/generate_envoy_only_config.py" --gateway "$gateway" --port "$ENVOY_ONLY_PORT" \
        --coding-port "$CODING_BACKEND_PORT" --math-port "$MATH_BACKEND_PORT" --qa-port "$QA_BACKEND_PORT" \
        --writing-port "$WRITING_BACKEND_PORT" --others-port "$OTHERS_BACKEND_PORT" --output "$config"
    if grep -q 'ext_proc' "$config"; then
        echo "Error: generated Envoy-only configuration unexpectedly contains ExtProc." >&2
        return 1
    fi
    docker rm -f "$ENVOY_ONLY_CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$ENVOY_ONLY_CONTAINER" --network "$network" \
        -v "${config}:/etc/envoy/envoy.yaml:ro" "$image" \
        envoy --config-path /etc/envoy/envoy.yaml >/dev/null
    if ! docker exec "$ENVOY_ONLY_CONTAINER" envoy --mode validate --config-path /etc/envoy/envoy.yaml >/dev/null 2>&1; then
        docker logs "$ENVOY_ONLY_CONTAINER" >&2 || true
        echo "Error: Envoy-only configuration validation failed." >&2
        return 1
    fi
    ENVOY_ONLY_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{if .IPAddress}}{{.IPAddress}}{{end}}{{end}}' "$ENVOY_ONLY_CONTAINER")"
    [ -n "$ENVOY_ONLY_IP" ] || { echo "Error: Envoy-only container has no bridge IP." >&2; return 1; }
}

setup_envoy_only_route() {
    ENVOY_ONLY_IF="$(ip route get "$ENVOY_ONLY_IP" | awk '/ dev / { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
    [ -n "$ENVOY_ONLY_IF" ] || { echo "Error: could not determine interface to Envoy-only container." >&2; return 1; }
    if ! ip netns exec "$NETNS" ip route show exact "${ENVOY_ONLY_IP}/32" | grep -q .; then
        ip netns exec "$NETNS" ip route add "${ENVOY_ONLY_IP}/32" via 10.10.0.1 dev "$XDP_PEER_IF"
        ENVOY_ONLY_ROUTE_ADDED=1
    fi
    iptables -t raw -C PREROUTING -i "$IFNAME" -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -p tcp --dport "$ENVOY_ONLY_PORT" -j ACCEPT 2>/dev/null || { iptables -t raw -I PREROUTING 1 -i "$IFNAME" -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -p tcp --dport "$ENVOY_ONLY_PORT" -j ACCEPT; ENVOY_ONLY_RAW_ACCEPT_ADDED=1; }
    iptables -t nat -C POSTROUTING -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -o "$ENVOY_ONLY_IF" -j MASQUERADE 2>/dev/null || { iptables -t nat -A POSTROUTING -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -o "$ENVOY_ONLY_IF" -j MASQUERADE; ENVOY_ONLY_NAT_ADDED=1; }
    iptables -C FORWARD -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -o "$ENVOY_ONLY_IF" -p tcp --dport "$ENVOY_ONLY_PORT" -j ACCEPT 2>/dev/null || { iptables -I FORWARD 1 -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -o "$ENVOY_ONLY_IF" -p tcp --dport "$ENVOY_ONLY_PORT" -j ACCEPT; ENVOY_ONLY_FORWARD_OUT_ADDED=1; }
    iptables -C FORWARD -s "$ENVOY_ONLY_IP" -d 10.10.0.0/24 -i "$ENVOY_ONLY_IF" -p tcp --sport "$ENVOY_ONLY_PORT" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || { iptables -I FORWARD 1 -s "$ENVOY_ONLY_IP" -d 10.10.0.0/24 -i "$ENVOY_ONLY_IF" -p tcp --sport "$ENVOY_ONLY_PORT" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; ENVOY_ONLY_FORWARD_RETURN_ADDED=1; }
    ENVOY_ONLY_URL="http://${ENVOY_ONLY_IP}:${ENVOY_ONLY_PORT}/v1/chat/completions"
    wait_for_ns_port "$ENVOY_ONLY_IP" "$ENVOY_ONLY_PORT" "Envoy-only baseline"
}

verify_envoy_only_backend_routing() {
    local expected response
    echo "Verifying Envoy-only forwarding reaches every marker backend..."
    for expected in coding math qa writing others; do
        response=$(ip netns exec "$NETNS" curl --silent --show-error --fail --max-time 10 \
            -H 'Content-Type: application/json' -H "x-benchmark-backend: ${expected}" \
            --data '{"model":"MoM","messages":[{"role":"user","content":"benchmark"}]}' "$ENVOY_ONLY_URL") || return 1
        grep -Fq "\"backend\":\"${expected}\"" <<<"$response" || { echo "Error: Envoy-only expected backend=${expected}, got: ${response}" >&2; return 1; }
    done
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
qa|answer this question: what is the capital of France?
writing|write a short poem about rain
others|tell me a short story
EOF
}

check_marker_backend_processes() {
    local pid
    for pid in "$CODING_MOCK_PID" "$MATH_MOCK_PID" "$OTHERS_MOCK_PID" "$QA_MOCK_PID" "$WRITING_MOCK_PID"; do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            echo "Error: a marker backend exited after the invocation-level reachability check." >&2
            return 1
        fi
    done
}

cleanup() {
    echo ""
    echo "Cleaning up processes and network rules..."
    for pid in "$ROUTER_PID" "$LLMROUTER_PID" "$CODING_MOCK_PID" "$MATH_MOCK_PID" "$OTHERS_MOCK_PID" "$QA_MOCK_PID" "$WRITING_MOCK_PID" "$VLLM_MOCK_PID"; do
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
    if system_selected llmrouter; then
        iptables -D INPUT -p tcp --dport "${LLMROUTER_PORT}" -j ACCEPT >/dev/null 2>&1 || true
    fi
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
    docker rm -f "$ENVOY_ONLY_CONTAINER" >/dev/null 2>&1 || true
    [ "$ENVOY_ONLY_NAT_ADDED" = "1" ] && iptables -t nat -D POSTROUTING -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -o "$ENVOY_ONLY_IF" -j MASQUERADE >/dev/null 2>&1 || true
    [ "$ENVOY_ONLY_RAW_ACCEPT_ADDED" = "1" ] && iptables -t raw -D PREROUTING -i "$IFNAME" -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -p tcp --dport "$ENVOY_ONLY_PORT" -j ACCEPT >/dev/null 2>&1 || true
    [ "$ENVOY_ONLY_FORWARD_OUT_ADDED" = "1" ] && iptables -D FORWARD -s 10.10.0.0/24 -d "$ENVOY_ONLY_IP" -o "$ENVOY_ONLY_IF" -p tcp --dport "$ENVOY_ONLY_PORT" -j ACCEPT >/dev/null 2>&1 || true
    [ "$ENVOY_ONLY_FORWARD_RETURN_ADDED" = "1" ] && iptables -D FORWARD -s "$ENVOY_ONLY_IP" -d 10.10.0.0/24 -i "$ENVOY_ONLY_IF" -p tcp --sport "$ENVOY_ONLY_PORT" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT >/dev/null 2>&1 || true
    [ "$ENVOY_ONLY_ROUTE_ADDED" = "1" ] && ip netns exec "$NETNS" ip route del "${ENVOY_ONLY_IP}/32" via 10.10.0.1 dev "$XDP_PEER_IF" >/dev/null 2>&1 || true
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
    local log_path="${2:-/tmp/sk_router_wrk.log}"

    echo "Starting routing proxy (${mode})..."
    ROUTER_LOG="$log_path"
    mkdir -p "$(dirname "$ROUTER_LOG")"
    if [ "$mode" = "sockmap" ]; then
        SK_ROUTER_MODE=sockmap ./sk_router > "$ROUTER_LOG" 2>&1 &
    else
        ./sk_router > "$ROUTER_LOG" 2>&1 &
    fi
    ROUTER_PID=$!
    wait_for_router_ready "routing frontend"
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
qa|answer this question: what is the capital of France?
writing|write a short poem about rain
others|tell me a short story
EOF
}

validate_untimed_load() {
    local name="$1"
    local url="$2"
    if [ "$VALIDATE_LOAD" = "1" ]; then
        echo "Running untimed concurrent load validation for ${name}..."
        "$PYTHON_BIN" "${SCRIPT_DIR}/validate_load.py" --url "$url" > "${RAW_DIR}/${name//[^a-zA-Z0-9]/_}.load-validation.txt"
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
    raw_file="${RAW_DIR}/${3}/wrk.txt"
    reason_file="${RAW_DIR}/${3}/invalid.txt"
    mkdir -p "${RAW_DIR}/${3}"
    if [ "$WARMUP_DURATION" != "0" ] && [ "$WARMUP_DURATION" != "0s" ]; then
        ip netns exec "$NETNS" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$WARMUP_DURATION" $RATE_ARG -s "${SCRIPT_DIR}/prompts.lua" "$1" \
            > "${RAW_DIR}/${3}/warmup.txt" 2>&1 || { echo "Error: warm-up failed for $2." >&2; return 1; }
        if [ "$3" = "xsr" ]; then
            # SOCKMAP mode owns five persistent backend sockets for every
            # accepted frontend connection.  A separate wrk/wrk2 warm-up
            # process closes its peers, but the userspace router has no
            # connection reaper and retains those socket sets.  Reset XSR so
            # the measured process is not competing with stale warm-up state.
            stop_routing_proxy
            start_routing_proxy sockmap "${RAW_DIR}/${3}/router-measurement.log" || return 1
        fi
    fi
    set +e
    output=$(ip netns exec "$NETNS" "$WRK_BIN" -t"$THREADS" -c"$CONCURRENCY" -d"$DURATION" $RATE_ARG -s "${SCRIPT_DIR}/prompts.lua" "$1" 2>&1)
    status=$?
    set -e
    printf '%s\n' "$output" > "$raw_file"
    printf '%s\n' "$output"
    if [ "$status" -ne 0 ]; then
        printf 'tool exit status=%s\n' "$status" > "$reason_file"
        "$PYTHON_BIN" "${SCRIPT_DIR}/record_result.py" --raw "$raw_file" --output "${RAW_DIR}/${3}/result.json" \
            --system "$2" --topology "$(system_topology "$3")" --mode "$BENCHMARK_MODE" --configuration "$CURRENT_CONFIGURATION" \
            --trial "$CURRENT_TRIAL" --tool "$WRK_BIN" --exit-status "$status"
        echo "Error: ${WRK_BIN} failed for $2 (exit ${status})." >&2
        return "$status"
    fi
    "$PYTHON_BIN" "${SCRIPT_DIR}/record_result.py" --raw "$raw_file" --output "${RAW_DIR}/${3}/result.json" \
        --system "$2" --topology "$(system_topology "$3")" --mode "$BENCHMARK_MODE" --configuration "$CURRENT_CONFIGURATION" \
        --trial "$CURRENT_TRIAL" --tool "$WRK_BIN" --exit-status "$status"
    if ! reason=$("$PYTHON_BIN" "${SCRIPT_DIR}/validate_output.py" --input "$raw_file"); then
        printf '%s\n' "$reason" > "$reason_file"
        echo "Error: invalid ${WRK_BIN} run for $2: ${reason}. Raw output: ${raw_file}" >&2
        return 1
    fi
}

system_topology() {
    case "$1" in
        direct|xsr|xsr-legacy|llmrouter) echo host-veth ;;
        envoy-only|vsr) echo docker-bridge ;;
        *) echo unavailable ;;
    esac
}

run_benchmark() {
    local route_count="${#SYSTEM_ORDER[@]}"
    local step=1 system heading

    echo "# Routing Performance Benchmark Results"
    echo ""
    echo "- Timestamp: \`$(date)\`"
    echo "- Tool: \`${WRK_BIN}\`"
    echo "- Mode: \`${BENCHMARK_MODE}\`"
    echo "- Topology: XSR (SK_SKB/SOCKMAP)=\`host-veth\`, direct=\`host-veth\`, LLMRouter=\`host-veth\`, Envoy-only=\`docker-bridge\`, VSR (Envoy ExtProc)=\`docker-bridge\`"
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
    for system in "${SYSTEM_ORDER[@]}"; do
        case "$system" in
            direct)
                heading="Direct backend"
                detach_xdp || return 1
                ;;
            envoy-only)
                heading="Envoy only"
                wait_for_ns_port "$ENVOY_ONLY_IP" "$ENVOY_ONLY_PORT" "Envoy-only baseline" || return 1
                ;;
            xsr)
                heading="XSR (SK_SKB/SOCKMAP)"
                if [ "$WARMUP_DURATION" != "0" ] && [ "$WARMUP_DURATION" != "0s" ]; then
                    start_routing_proxy sockmap "${RAW_DIR}/${system}/router-warmup.log" || return 1
                else
                    start_routing_proxy sockmap "${RAW_DIR}/${system}/router-measurement.log" || return 1
                fi
                validate_untimed_load "xsr" "$XDP_URL" || return 1
                ;;
            xsr-legacy)
                heading="XSR (legacy)"
                start_routing_proxy proxy || return 1
                ;;
            vsr)
                heading="VSR (Envoy ExtProc)"
                wait_for_ns_port "$VLLM_IP" "$VLLM_PORT" "vLLM-SR Envoy (${VLLM_HOST})" || return 1
                validate_untimed_load "vsr" "$VLLM_URL" || return 1
                ;;
            llmrouter)
                heading="LLMRouter (XSR reference)"
                wait_for_ns_port "10.10.0.1" "$LLMROUTER_PORT" "LLMRouter baseline" || return 1
                validate_untimed_load "llmrouter" "$LLMROUTER_URL" || return 1
                ;;
            *) echo "Error: unsupported benchmark system ${system}." >&2; return 1 ;;
        esac
        echo "## [${step}/${route_count}] ${heading}"
        echo "\`\`\`"
        case "$system" in
            direct) run_wrk "$DIRECT_BACKEND_URL" "$heading" "$system" || return 1 ;;
            envoy-only) run_wrk "$ENVOY_ONLY_URL" "$heading" "$system" || return 1 ;;
            xsr|xsr-legacy) run_wrk "$XDP_URL" "$heading" "$system" || return 1 ;;
            vsr) run_wrk "$VLLM_URL" "$heading" "$system" || return 1 ;;
            llmrouter) run_wrk "$LLMROUTER_URL" "$heading" "$system" || return 1 ;;
        esac
        echo "\`\`\`"
        echo ""
        [ "$system" = "xsr" ] || [ "$system" = "xsr-legacy" ] && stop_routing_proxy
        step=$((step + 1))
    done
}

# Invocation-invariant setup and full correctness checks. Components that can
# fail later still receive cheap process/port readiness checks during trials.
for marker in \
    "${CODING_BACKEND_PORT}:coding" \
    "${MATH_BACKEND_PORT}:math" \
    "${OTHERS_BACKEND_PORT}:others" \
    "${QA_BACKEND_PORT}:QA" \
    "${WRITING_BACKEND_PORT}:writing"; do
    wait_for_ns_port "10.10.0.1" "${marker%%:*}" "${marker#*:} mock backend"
done

if system_selected vsr; then
    setup_vllm_route
    verify_vllm_backend_routing
fi
if system_selected envoy-only; then
    start_envoy_only
    setup_envoy_only_route
    verify_envoy_only_backend_routing
fi
if system_selected xsr; then
    start_routing_proxy sockmap "${RUN_ROOT}/raw/xsr-invocation-preflight.log"
    verify_router_backend_routing "XSR"
    stop_routing_proxy
fi
if system_selected xsr-legacy; then
    start_routing_proxy proxy "${RUN_ROOT}/raw/xsr-legacy-invocation-preflight.log"
    verify_router_backend_routing "XSR (legacy)"
    stop_routing_proxy
fi
if system_selected llmrouter; then
    start_llmrouter
    verify_llmrouter_backend_routing
fi
detach_xdp

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

FAILED_TRIALS=0
for RATE in "${RATE_VALUES[@]}"; do
for CONCURRENCY in "${CONCURRENCIES[@]}"; do
    # Restore the configured thread count for every sweep entry: a low initial
    # concurrency must not clamp the thread count of subsequent runs.
    THREADS="$BASE_THREADS"
    if [ "$THREADS" -gt "$CONCURRENCY" ]; then
        THREADS="$CONCURRENCY"
    fi

    if [ "$BENCHMARK_MODE" = "fixed-rate" ]; then
        CURRENT_CONFIGURATION="rate-${RATE}_concurrency-${CONCURRENCY}"
    else
        CURRENT_CONFIGURATION="concurrency-${CONCURRENCY}"
    fi
    for CURRENT_TRIAL in $(seq 1 "$TRIALS"); do
        RAW_DIR="${RUN_ROOT}/raw/${BENCHMARK_MODE}/${CURRENT_CONFIGURATION}/trial-$(printf '%02d' "$CURRENT_TRIAL")"
        mkdir -p "$RAW_DIR"
        mapfile -t SYSTEM_ORDER < <("$PYTHON_BIN" -c 'import random, sys; items=sys.argv[1:]; random.Random(int(items.pop(0))).shuffle(items); print(*items, sep="\n")' "$((RANDOM_SEED + CURRENT_TRIAL + CONCURRENCY + RATE))" "${SELECTED_SYSTEMS[@]}")
        "$PYTHON_BIN" "${SCRIPT_DIR}/manifest.py" --path "${RUN_ROOT}/manifest.json" --configuration "$CURRENT_CONFIGURATION" --trial "$CURRENT_TRIAL" --order "${SYSTEM_ORDER[@]}"
        REPORT_FILE="${RAW_DIR}/report.md"
        stop_routing_proxy
        detach_xdp
        check_marker_backend_processes
        if ! run_benchmark > >(tee "$REPORT_FILE"); then
            printf 'trial failed; see system raw output and invalid.txt files\n' > "${RAW_DIR}/FAILED"
            FAILED_TRIALS=$((FAILED_TRIALS + 1))
        fi
        stop_routing_proxy
        echo "Benchmark trial ${CURRENT_TRIAL}/${TRIALS}: ${REPORT_FILE}"
    done
done
done

"$PYTHON_BIN" "${SCRIPT_DIR}/aggregate_results.py" --run-dir "$RUN_ROOT" || echo "No completed trial results available for aggregation." >&2
if [ "$FAILED_TRIALS" -ne 0 ]; then
    echo "Error: ${FAILED_TRIALS} invalid benchmark trial(s) were excluded from aggregation." >&2
    exit 1
fi

if [ -n "$SUDO_USER" ]; then
    chown -R "$SUDO_USER:" "$REPORT_DIR" 2>/dev/null || true
fi
