#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NETNS=${XDP_NETNS:-ns1}
HOST_IF=${XDP_HOST_IF:-veth0}
STATUS_DIR=$(mktemp -d /tmp/xsr-lifecycle.XXXXXX)
STATUS_SOCKET="${STATUS_DIR}/status.sock"
ROUTER_LOG="${STATUS_DIR}/router.log"
PIDS=()
FIREWALL_RULE_ADDED=0

cleanup() {
    local pid
    for pid in "${PIDS[@]}"; do
        kill -9 "$pid" >/dev/null 2>&1 || true
    done
    for pid in "${PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
    if [ "$FIREWALL_RULE_ADDED" = 1 ]; then
        iptables -D INPUT -i "$HOST_IF" -p tcp --dport 18081 -j ACCEPT >/dev/null 2>&1 || true
    fi
    rm -f "$STATUS_SOCKET"
    rmdir "$STATUS_DIR" 2>/dev/null || true
}
trap cleanup EXIT

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: run this lifecycle stress test with sudo." >&2
    exit 1
fi

cd "$ROOT_DIR"
./benchmarks/sockmap_lifecycle_semantics
iptables -I INPUT 1 -i "$HOST_IF" -p tcp --dport 18081 -j ACCEPT
FIREWALL_RULE_ADDED=1
for backend in "18391 coding" "18392 math" "18393 others" "18394 qa" "18395 writing"; do
    read -r port name <<<"$backend"
    XSR_MOCK_RESPONSE_DELAY_MS=250 ./benchmarks/mock_backend_delayed \
        "$port" "$name" >"${STATUS_DIR}/${name}.log" 2>&1 &
    PIDS+=("$!")
done
for port in 18391 18392 18393 18394 18395; do
    for _ in $(seq 1 100); do
        if timeout 0.1 bash -c "</dev/tcp/127.0.0.1/${port}" 2>/dev/null; then
            break
        fi
        sleep 0.02
    done
    if ! timeout 0.1 bash -c "</dev/tcp/127.0.0.1/${port}" 2>/dev/null; then
        echo "Error: marker backend port ${port} did not become ready." >&2
        exit 1
    fi
done

SK_ROUTER_MODE=sockmap XSR_STATUS_SOCKET="$STATUS_SOCKET" ./sk_router >"$ROUTER_LOG" 2>&1 &
ROUTER_PID=$!
PIDS+=("$ROUTER_PID")

for _ in $(seq 1 200); do
    if [ -S "$STATUS_SOCKET" ]; then
        break
    fi
    if ! kill -0 "$ROUTER_PID" 2>/dev/null; then
        echo "Error: XSR exited during lifecycle-test startup." >&2
        sed -n '1,240p' "$ROUTER_LOG" >&2
        exit 1
    fi
    sleep 0.05
done
if [ ! -S "$STATUS_SOCKET" ]; then
    echo "Error: XSR lifecycle status socket was not created." >&2
    sed -n '1,240p' "$ROUTER_LOG" >&2
    exit 1
fi

python3 benchmarks/routing_wrk/wait_for_xsr_quiescence.py \
    --socket "$STATUS_SOCKET" --pid "$ROUTER_PID" --timeout 10 >/dev/null

ip netns exec "$NETNS" python3 benchmarks/routing_wrk/sockmap_lifecycle_stress.py \
    --status-socket "$STATUS_SOCKET" --pid "$ROUTER_PID" \
    --sequential "${LIFECYCLE_SEQUENTIAL:-3001}" \
    --wave-sizes 1 8 64 192 --wave-repeats "${LIFECYCLE_WAVE_REPEATS:-2}" \
    --cleanup-timeout "${LIFECYCLE_CLEANUP_TIMEOUT:-30}"

echo "router_log=${ROUTER_LOG}"
