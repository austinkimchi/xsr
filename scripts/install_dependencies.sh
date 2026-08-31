#!/usr/bin/env bash
set -euo pipefail

mode="${1:-production}"
if [ "$mode" != "production" ] && [ "$mode" != "benchmark" ]; then
    echo "Usage: $0 production|benchmark" >&2
    exit 2
fi
if [ "$(uname -s)" != "Linux" ]; then
    echo "Error: XSR requires Linux." >&2
    exit 1
fi

as_root=()
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || {
        echo "Error: sudo is required to install system packages." >&2
        exit 1
    }
    as_root=(sudo)
fi

run() {
    if [ "${INSTALL_DRY_RUN:-0}" = "1" ]; then
        printf 'Would run:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

if command -v apt-get >/dev/null 2>&1; then
    packages=(build-essential clang libbpf-dev pkg-config iproute2 ethtool iptables)
    if [ "$mode" = "benchmark" ]; then
        packages+=(curl docker.io git libssl-dev "linux-tools-$(uname -r)" linux-tools-common perl python3 python3-venv unzip zlib1g-dev)
    fi
    run "${as_root[@]}" apt-get update
    run "${as_root[@]}" apt-get install -y "${packages[@]}"
elif command -v dnf >/dev/null 2>&1; then
    packages=(gcc make clang libbpf-devel pkgconf-pkg-config iproute ethtool iptables)
    if [ "$mode" = "benchmark" ]; then
        packages+=(bpftool curl git openssl-devel perl python3 python3-pip unzip zlib-devel)
    fi
    run "${as_root[@]}" dnf install -y "${packages[@]}"
elif command -v pacman >/dev/null 2>&1; then
    packages=(base-devel clang libbpf pkgconf iproute2 ethtool iptables)
    if [ "$mode" = "benchmark" ]; then
        packages+=(bpf curl docker git openssl perl python unzip zlib)
    fi
    run "${as_root[@]}" pacman -Syu --needed --noconfirm "${packages[@]}"
else
    echo "Error: supported package managers are apt, dnf, and pacman." >&2
    exit 1
fi
