#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WRK_REVISION="a211dd5a7050b1f9e8a9870b95513060e72ac4a0"
TOOLS_DIR="${ROOT_DIR}/.tools"
SOURCE_DIR="${TOOLS_DIR}/wrk-src"
INSTALL_DIR="${TOOLS_DIR}/wrk"

mkdir -p "$TOOLS_DIR"
if [ ! -f /usr/include/openssl/ssl.h ]; then
    echo "Error: OpenSSL development headers are required to build wrk." >&2
    exit 1
fi
if [ ! -d "${SOURCE_DIR}/.git" ]; then
    git clone https://github.com/wg/wrk.git "$SOURCE_DIR"
fi
git -C "$SOURCE_DIR" fetch --tags origin
git -C "$SOURCE_DIR" checkout --detach "$WRK_REVISION"
make -C "$SOURCE_DIR"
mkdir -p "$INSTALL_DIR"
install -m 0755 "$SOURCE_DIR/wrk" "$INSTALL_DIR/wrk"
printf 'wrk pinned revision: %s\nruntime path: %s\n' "$WRK_REVISION" "$INSTALL_DIR/wrk"
