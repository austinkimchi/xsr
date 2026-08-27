#!/usr/bin/env bash
# Build a reproducible, repository-local wrk2 binary on explicit request.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRK2_REVISION="44a94c17d8e6a0bac8559b53da76848e430cb7a7"
TOOLS_DIR="${ROOT_DIR}/.tools"
SOURCE_DIR="${TOOLS_DIR}/wrk2-src"
INSTALL_DIR="${TOOLS_DIR}/wrk2"

mkdir -p "$TOOLS_DIR"
if [ ! -f /usr/include/openssl/ssl.h ]; then
    echo "Error: OpenSSL development headers are required to build wrk2." >&2
    echo "Install them (for example: sudo apt-get install libssl-dev), then rerun: make install-wrk2" >&2
    exit 1
fi
if [ ! -d "${SOURCE_DIR}/.git" ]; then
    git clone https://github.com/giltene/wrk2.git "$SOURCE_DIR"
fi
git -C "$SOURCE_DIR" fetch --tags origin
git -C "$SOURCE_DIR" checkout --detach "$WRK2_REVISION"
make -C "$SOURCE_DIR"
mkdir -p "$INSTALL_DIR"
install -m 0755 "$SOURCE_DIR/wrk" "$INSTALL_DIR/wrk"
printf 'wrk2 pinned revision: %s\nruntime path: %s\n' "$WRK2_REVISION" "$INSTALL_DIR/wrk"
