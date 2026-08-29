SHELL := /bin/bash

CC ?= gcc
BPF_CLANG ?= clang
PKG_CONFIG ?= pkg-config
PYTHON ?= python3
BENCHMARK_PYTHON ?= $(CURDIR)/.venv/bin/python
NOFILE_LIMIT ?= 16384

ARCH := $(shell uname -m)
BPF_ARCH := $(ARCH)
ifneq (,$(filter x86_64 i386 i486 i586 i686,$(ARCH)))
BPF_ARCH := x86
else ifneq (,$(filter aarch64 arm64,$(ARCH)))
BPF_ARCH := arm64
else ifneq (,$(filter arm%,$(ARCH)))
BPF_ARCH := arm
else ifneq (,$(filter ppc64 ppc64le,$(ARCH)))
BPF_ARCH := powerpc
else ifeq ($(ARCH),s390x)
BPF_ARCH := s390
else ifeq ($(ARCH),riscv64)
BPF_ARCH := riscv
endif
MULTIARCH := $(shell $(CC) -print-multiarch 2>/dev/null)
MULTIARCH_INCLUDE := $(if $(MULTIARCH),-I/usr/include/$(MULTIARCH))

OPT_CFLAGS ?= -O3
EXTRA_DEFS ?=
USER_CFLAGS := -Wall $(OPT_CFLAGS) $(EXTRA_DEFS)
BPF_CFLAGS := -O2 -g -target bpf \
	-D__BPF__=1 \
	-D__TARGET_ARCH_$(BPF_ARCH) \
	-I. -Ibpf $(MULTIARCH_INCLUDE) $(EXTRA_DEFS)
DEV_DEFS := -DXDP_DEBUG=1 -DXDP_PROFILE=1
LIBBPF_FLAGS = $(shell $(PKG_CONFIG) --cflags --libs libbpf 2>/dev/null)

XDP_NETNS ?= ns1
XDP_HOST_IF ?= veth0
XDP_PEER_IF ?= veth1
XDP_HOST_ADDR ?= 10.10.0.1/24
XDP_PEER_ADDR ?= 10.10.0.2/24
KEYWORD_POLICY ?= config/policy_ngram.yaml
VSR_BACKEND_PORTS ?= 18391 18392 18393 18394 18395
args ?=

.DEFAULT_GOAL := build

help:
	@echo "XSR commands:"
	@echo "  make                 Build the production SOCKMAP router"
	@echo "  make install         Install Linux dependencies and build production"
	@echo "  make benchmark       Set up Python/tools and build benchmark helpers"
	@echo "  make check           Check build tools and SOCKMAP support"
	@echo "  make dev             Build benchmark helpers with debug output"
	@echo "  make legacy          Build the older XDP router when explicitly needed"
	@echo "  make policy          Regenerate the checked-in policy header"
	@echo "  sudo make setup      Create or repair ns1 and veth0/veth1"
	@echo "  sudo make correctness [args=\"...\"]"
	@echo "  sudo make performance [args=\"CONCURRENCY=1 DURATION=30s ...\"]"
	@echo "  sudo make performance-fixed-rate [args=\"RATES='100 250 500' ...\"]"
	@echo "  make clean           Remove compiled binaries and BPF objects"
	@echo "  sudo make clean-setup"

all: build

build: sk_router sk_router.bpf.o

legacy: xdp_router xdp_router.bpf.o

benchmark-build: build benchmarks/mock_backend

prod:
	$(MAKE) clean
	$(MAKE) build OPT_CFLAGS=-O3

dev:
	$(MAKE) clean
	$(MAKE) benchmark-build OPT_CFLAGS=-O2 EXTRA_DEFS="$(DEV_DEFS)"

install:
	./scripts/install_dependencies.sh production
	$(MAKE) check
	$(MAKE) prod

benchmark:
	./scripts/install_dependencies.sh benchmark
	$(PYTHON) -m venv .venv
	$(BENCHMARK_PYTHON) -m pip install --upgrade pip
	$(BENCHMARK_PYTHON) -m pip install -r benchmarks/requirements.txt
	$(MAKE) policy PYTHON=$(BENCHMARK_PYTHON)
	$(MAKE) benchmark-build
	$(MAKE) install-wrk
	$(MAKE) install-wrk2
	$(MAKE) check-benchmark

policy: bpf/xdp_keyword_modules.generated.h

bpf/xdp_keyword_modules.generated.h: FORCE
	$(PYTHON) benchmarks/policy/generate_policy_modules.py $(KEYWORD_POLICY) bpf

FORCE:

define require_sudo
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "Error: run this command as: sudo make $@" >&2; \
		exit 1; \
	fi
endef

correctness:
	$(require_sudo)
	$(MAKE) check-benchmark
	$(MAKE) setup
	$(MAKE) iproutes
	PYTHON="$(BENCHMARK_PYTHON)" ./benchmarks/run_routing_correctness.sh $(args)

performance:
	$(require_sudo)
	$(MAKE) check-performance
	$(MAKE) setup
	$(MAKE) iproutes
	@ulimit -n $(NOFILE_LIMIT) || { echo "Error: unable to set open-file limit to $(NOFILE_LIMIT)." >&2; exit 1; }; \
		echo "Effective open-file limit: $$(ulimit -n)"; \
		PYTHON="$(BENCHMARK_PYTHON)" BENCHMARK_MODE=saturation ./benchmarks/run_routing_performance.sh $(args)

performance-fixed-rate:
	$(require_sudo)
	$(MAKE) check-performance-fixed-rate
	$(MAKE) setup
	$(MAKE) iproutes
	@ulimit -n $(NOFILE_LIMIT) || { echo "Error: unable to set open-file limit to $(NOFILE_LIMIT)." >&2; exit 1; }; \
		echo "Effective open-file limit: $$(ulimit -n)"; \
		PYTHON="$(BENCHMARK_PYTHON)" BENCHMARK_MODE=fixed-rate ./benchmarks/run_routing_performance.sh $(args)

wrk: performance

check-build:
	@test "$$(uname -s)" = Linux || { echo "Error: XSR production requires Linux." >&2; exit 1; }
	@command -v "$(CC)" >/dev/null || { echo "Error: compiler '$(CC)' is required." >&2; exit 1; }
	@command -v "$(BPF_CLANG)" >/dev/null || { echo "Error: clang is required for BPF builds." >&2; exit 1; }
	@command -v "$(PKG_CONFIG)" >/dev/null || { echo "Error: pkg-config is required." >&2; exit 1; }
	@$(PKG_CONFIG) --exists libbpf || { echo "Error: libbpf development files are required." >&2; exit 1; }

check: check-build
	@./scripts/check_sockmap.sh
	@command -v ip >/dev/null || { echo "Error: iproute2 is required." >&2; exit 1; }
	@command -v ethtool >/dev/null || { echo "Error: ethtool is required." >&2; exit 1; }

check-benchmark: check
	@test -x "$(BENCHMARK_PYTHON)" || { echo "Error: run 'make benchmark' first." >&2; exit 1; }
	@$(BENCHMARK_PYTHON) -c 'import datasets, matplotlib, nbconvert, nbformat, numpy, pandas' >/dev/null 2>&1 || { echo "Error: benchmark Python packages are incomplete; run 'make benchmark'." >&2; exit 1; }
	@command -v curl >/dev/null || { echo "Error: curl is required." >&2; exit 1; }
	@command -v docker >/dev/null || { echo "Error: Docker is required for the VSR and Envoy comparisons." >&2; exit 1; }
	@command -v iptables >/dev/null || { echo "Error: iptables is required for benchmark setup." >&2; exit 1; }

check-performance: check-benchmark
	@test -x "$(CURDIR)/.tools/wrk/wrk" || command -v wrk >/dev/null || { echo "Error: saturation mode requires standard wrk; run 'make benchmark' or 'make install-wrk'." >&2; exit 1; }

check-performance-fixed-rate: check-benchmark
	@test -x "$(CURDIR)/.tools/wrk2/wrk" || command -v "$${WRK2_BIN:-wrk2}" >/dev/null || { echo "Error: fixed-rate mode requires wrk2; run 'make benchmark' or 'make install-wrk2'." >&2; exit 1; }

install-wrk:
	./benchmarks/routing_wrk/install_wrk.sh

install-wrk2:
	./benchmarks/routing_wrk/install_wrk2.sh

xdp_router: xdp_router.c xdp_router.h bpf/xdp_classifier.bpf.h bpf/xdp_ngram_classifier.bpf.h bpf/xdp_bm25_classifier.bpf.h bpf/xdp_keyword_policy_loader.h bpf/xdp_keyword_modules.generated.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS)

sk_router: sk_router.c xdp_router.h bpf/xdp_decision.bpf.h bpf/xdp_signals.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_ngram_classifier.bpf.h bpf/xdp_bm25_classifier.bpf.h bpf/xdp_keyword_policy_loader.h bpf/xdp_keyword_modules.generated.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS) -lpthread

benchmarks/mock_backend: benchmarks/mock_backend.c
	$(CC) -O3 $< -o $@ -lpthread

xdp_router.bpf.o: bpf/xdp_router.bpf.c xdp_router.h bpf/xdp_http_parser.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_ngram_classifier.bpf.h bpf/xdp_jaccard_classifier.bpf.h bpf/xdp_bm25_classifier.bpf.h bpf/xdp_keyword_modules.generated.h bpf/xdp_unicode_word.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

sk_router.bpf.o: bpf/sk_router.bpf.c xdp_router.h bpf/xdp_decision.bpf.h bpf/xdp_signals.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_ngram_classifier.bpf.h bpf/xdp_jaccard_classifier.bpf.h bpf/xdp_bm25_classifier.bpf.h bpf/xdp_keyword_modules.generated.h bpf/xdp_unicode_word.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

clean:
	rm -f xdp_router sk_router xdp_router.bpf.o sk_router.bpf.o benchmarks/mock_backend

clean-setup:
	@ip link delete $(XDP_HOST_IF) 2>/dev/null || true
	@ip netns delete $(XDP_NETNS) 2>/dev/null || true
	@echo "network setup reset"

setup:
	@if ! ip netns list | awk '{print $$1}' | grep -Fxq "$(XDP_NETNS)"; then \
		ip netns add $(XDP_NETNS); \
	fi
	@if ip link show dev $(XDP_HOST_IF) >/dev/null 2>&1 && ip netns exec $(XDP_NETNS) ip link show dev $(XDP_PEER_IF) >/dev/null 2>&1; then \
		echo "$(XDP_HOST_IF) and $(XDP_NETNS)/$(XDP_PEER_IF) already exist"; \
	elif ! ip link show dev $(XDP_HOST_IF) >/dev/null 2>&1 && ! ip netns exec $(XDP_NETNS) ip link show dev $(XDP_PEER_IF) >/dev/null 2>&1; then \
		ip link add $(XDP_HOST_IF) type veth peer name $(XDP_PEER_IF); \
		ip link set $(XDP_PEER_IF) netns $(XDP_NETNS); \
	else \
		echo "Partial setup detected; resetting network interfaces..." >&2; \
		ip link delete $(XDP_HOST_IF) 2>/dev/null || true; \
		ip netns delete $(XDP_NETNS) 2>/dev/null || true; \
		ip netns add $(XDP_NETNS); \
		ip link add $(XDP_HOST_IF) type veth peer name $(XDP_PEER_IF); \
		ip link set $(XDP_PEER_IF) netns $(XDP_NETNS); \
	fi
	@ip addr show dev $(XDP_HOST_IF) | grep -Fq "$(XDP_HOST_ADDR)" || ip addr add $(XDP_HOST_ADDR) dev $(XDP_HOST_IF)
	@ip netns exec $(XDP_NETNS) ip addr show dev $(XDP_PEER_IF) | grep -Fq "$(XDP_PEER_ADDR)" || ip netns exec $(XDP_NETNS) ip addr add $(XDP_PEER_ADDR) dev $(XDP_PEER_IF)
	@ip link set dev $(XDP_HOST_IF) mtu 1500
	@ip netns exec $(XDP_NETNS) ip link set dev $(XDP_PEER_IF) mtu 1500
	@ethtool -K $(XDP_HOST_IF) gro off gso off tso off lro off 2>/dev/null || true
	@ip netns exec $(XDP_NETNS) ethtool -K $(XDP_PEER_IF) gro off gso off tso off lro off 2>/dev/null || true
	@ip link set $(XDP_HOST_IF) up
	@ip netns exec $(XDP_NETNS) ip link set $(XDP_PEER_IF) up
	@ip netns exec $(XDP_NETNS) ip link set lo up
	@echo "setup complete: $(XDP_HOST_IF)=$(XDP_HOST_ADDR), $(XDP_NETNS)/$(XDP_PEER_IF)=$(XDP_PEER_ADDR)"

iproutes:
	@for port in $(VSR_BACKEND_PORTS); do \
		iptables -C INPUT -p tcp --dport $$port -j ACCEPT 2>/dev/null || \
		iptables -I INPUT 1 -p tcp --dport $$port -j ACCEPT; \
	done
	@echo "benchmark backend ports allowed: $(VSR_BACKEND_PORTS)"

.PHONY: help all build legacy benchmark-build prod dev install benchmark policy FORCE correctness performance performance-fixed-rate wrk check-build check check-benchmark check-performance check-performance-fixed-rate install-wrk install-wrk2 clean clean-setup setup iproutes
