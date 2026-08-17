#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$EUID" -ne 0 ]; then
  echo "Routing performance benchmark requires root privileges. Elevating with sudo..."
  exec sudo "$0" "$@"
fi

exec "${SCRIPT_DIR}/routing_wrk/benchmark.sh" "$@"
