#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONCURRENCIES=(1 2 4 8 16 32 64 96)

if [ "$EUID" -ne 0 ]; then
  echo "Routing performance sweep requires root privileges. Elevating with sudo..."
  exec sudo "$0" "$@"
fi

for C in "${CONCURRENCIES[@]}"; do
  CONCURRENCY="$C" DURATION=30s "${ROOT_DIR}/benchmarks/run_routing_performance.sh"
done
