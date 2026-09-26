#!/usr/bin/env bash
set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
    echo "Error: SOCKMAP requires Linux." >&2
    exit 1
fi

kernel_release="$(uname -r)"
kernel_version="${kernel_release%%-*}"
minimum_version="4.14"
first_version="$(printf '%s\n%s\n' "$minimum_version" "$kernel_version" | sort -V | head -n 1)"
if [ "$first_version" != "$minimum_version" ]; then
    echo "Error: SOCKMAP requires Linux 4.14 or newer; found ${kernel_release}." >&2
    exit 1
fi

config_path=""
if [ -r "/proc/config.gz" ]; then
    config_path="/proc/config.gz"
elif [ -r "/boot/config-${kernel_release}" ]; then
    config_path="/boot/config-${kernel_release}"
fi

if [ -n "$config_path" ]; then
    if [[ "$config_path" == *.gz ]]; then
        config_text="$(gzip -cd "$config_path")"
    else
        config_text="$(<"$config_path")"
    fi
    for option in CONFIG_BPF CONFIG_BPF_SYSCALL CONFIG_BPF_STREAM_PARSER; do
        if ! grep -q "^${option}=y$" <<<"$config_text"; then
            echo "Error: kernel ${kernel_release} does not enable ${option}." >&2
            exit 1
        fi
    done
else
    echo "Warning: kernel configuration is unavailable; runtime BPF support will be checked when XSR starts." >&2
fi

if [ "${REQUIRE_RUNTIME_BPF:-0}" = "1" ]; then
    [ "$(id -u)" -eq 0 ] || {
        echo "Error: runtime SOCKMAP/SK_SKB probing requires root; rerun the benchmark preflight with sudo." >&2
        exit 1
    }
    command -v bpftool >/dev/null 2>&1 || {
        echo "Error: bpftool is required for runtime SOCKMAP/SK_SKB probing." >&2
        exit 1
    }
fi

if command -v bpftool >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    feature_output="$(bpftool feature probe kernel 2>/dev/null)"
    grep -q "map_type sockmap is available" <<<"$feature_output" || {
        echo "Error: this kernel does not report SOCKMAP support." >&2
        exit 1
    }
    grep -q "program_type sk_skb is available" <<<"$feature_output" || {
        echo "Error: this kernel does not report SK_SKB program support." >&2
        exit 1
    }
fi

echo "SOCKMAP check passed for Linux ${kernel_release} (${ARCH:-$(uname -m)})."
