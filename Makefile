SHELL := /bin/bash

CC ?= gcc
BPF_CLANG ?= clang
PKG_CONFIG ?= pkg-config
PYTHON ?= python3
BENCHMARK_PYTHON ?= $(CURDIR)/.venv/bin/python
LLMROUTER_PYTHON ?= $(CURDIR)/.venv-llmrouter/bin/python
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
USER_CFLAGS := -Wall $(OPT_CFLAGS) -Iinclude -Ibpf $(EXTRA_DEFS)
BPF_CFLAGS := -O2 -g -target bpf \
	-D__BPF__=1 \
	-D__TARGET_ARCH_$(BPF_ARCH) \
	-Iinclude -Ibpf $(MULTIARCH_INCLUDE) $(EXTRA_DEFS)
DEV_DEFS := -DXDP_DEBUG=1 -DXDP_PROFILE=1
LIBBPF_FLAGS = $(shell $(PKG_CONFIG) --cflags --libs libbpf 2>/dev/null)

XDP_NETNS ?= ns1
XDP_HOST_IF ?= veth0
XDP_PEER_IF ?= veth1
XDP_HOST_ADDR ?= 10.10.0.1/24
XDP_PEER_ADDR ?= 10.10.0.2/24
KEYWORD_POLICY ?= config/policy_ngram.yaml
SIGNAL_PROFILE ?= auto
XSR_DISTILL_PARITY_DEBUG ?= 0
VSR_BACKEND_PORTS ?= 18391 18392 18393 18394 18395
BENCHMARK_SYSTEMS ?= direct,envoy-only,xsr,vsr,llmrouter
args ?=

.DEFAULT_GOAL := build

help:
	@echo "XSR commands:"
	@echo "  make                 Build the production SOCKMAP router"
	@echo "  make install         Install Linux dependencies and build production"
	@echo "  sudo make benchmark  Check all default benchmark environments"
	@echo "  make benchmark-install  Install benchmark tools and selected adapters"
	@echo "  make check           Check build tools and SOCKMAP support"
	@echo "  make test            Run dependency-free unit tests"
	@echo "  make profile-check   Validate benchmark profiles without running them"
	@echo "  make test-distill    Run NumPy distillation tests in the benchmark venv"
	@echo "  make llmrouter-install  Install the optional pinned LLMRouter baseline"
	@echo "  make test-llmrouter  Test the optional LLMRouter adapter"
	@echo "  sudo make test-sockmap-lifecycle  Stress connection cleanup and slot reuse"
	@echo "  make dev             Build benchmark helpers with debug output"
	@echo "  make legacy          Build the older XDP router when explicitly needed"
	@echo "  make policy          Regenerate the checked-in policy header"
	@echo "  make SIGNAL_PROFILE=intent policy  Generate an intent-only build"
	@echo "  make parity-build    Build intent-only with kernel parity diagnostics"
	@echo "  sudo make setup      Create or repair ns1 and veth0/veth1"
	@echo "  sudo make correctness [args=\"...\"]"
	@echo "  sudo make performance [args=\"CONCURRENCY=1 DURATION=30s ...\"]"
	@echo "  sudo make performance-fixed-rate [args=\"RATES='100 250 500' ...\"]"
	@echo "  make clean           Remove compiled binaries and BPF objects"
	@echo "  sudo make clean-setup"

all: build

build: sk_router sk_router.bpf.o

legacy: xdp_router xdp_router.bpf.o

benchmark-build: build benchmarks/mock_backend benchmarks/sockmap_lifecycle_semantics

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

benchmark-install:
	./scripts/install_dependencies.sh benchmark
	$(PYTHON) -m venv .venv
	$(BENCHMARK_PYTHON) -m pip install --upgrade pip
	$(BENCHMARK_PYTHON) -m pip install -r benchmarks/requirements.txt
	$(MAKE) policy PYTHON=$(BENCHMARK_PYTHON)
	$(MAKE) benchmark-build
	$(MAKE) install-wrk
	$(MAKE) install-wrk2
	@if [[ ",$(BENCHMARK_SYSTEMS)," == *,llmrouter,* ]]; then $(MAKE) llmrouter-install; fi

benchmark:
	@BENCHMARK_SYSTEMS="$(BENCHMARK_SYSTEMS)" BENCHMARK_PYTHON="$(BENCHMARK_PYTHON)" \
		BENCHMARK_MODE=all REQUIRE_BENCHMARK_NETWORK=1 \
		LLMROUTER_PYTHON="$(LLMROUTER_PYTHON)" \
		./benchmarks/routing_wrk/check_environments.sh

test:
	$(PYTHON) -m unittest discover -s benchmarks/policy -p 'test_*.py'
	$(PYTHON) -m unittest discover -s benchmarks/routing_correctness -p 'test_*.py'
	$(PYTHON) -m unittest discover -s benchmarks/routing_wrk -p 'test_*.py'

profile-check:
	$(PYTHON) -m unittest discover -s benchmarks/routing_wrk -p 'test_benchmark_profile.py'

test-distill:
	@test -x "$(BENCHMARK_PYTHON)" || { echo "Error: run 'make benchmark-install' first." >&2; exit 1; }
	$(BENCHMARK_PYTHON) -m pytest benchmarks/lora_distill/test_core.py

llmrouter-install:
	$(PYTHON) -m venv .venv-llmrouter
	$(LLMROUTER_PYTHON) -m pip install --upgrade pip
	$(LLMROUTER_PYTHON) -m pip install -r benchmarks/llmrouter/requirements.txt
	@test -x "$(CURDIR)/.venv-llmrouter/bin/llmrouter"
	$(LLMROUTER_PYTHON) -c 'import llmrouter, openclaw_router, torch, uvicorn; from llmrouter.models.meta_router import MetaRouter'
	$(LLMROUTER_PYTHON) -m pip check

test-llmrouter:
	@test -x "$(LLMROUTER_PYTHON)" || { echo "Error: run 'make llmrouter-install' first." >&2; exit 1; }
	$(LLMROUTER_PYTHON) -m unittest discover -s benchmarks/llmrouter -p 'test_*.py'

test-sockmap-lifecycle: benchmark-build benchmarks/mock_backend_delayed
	$(require_sudo)
	./benchmarks/routing_wrk/run_sockmap_lifecycle_stress.sh

GENERATED_SIGNAL_DIR := bpf/stages/signals/generated

policy: $(GENERATED_SIGNAL_DIR)/xdp_keyword_modules.generated.h

$(GENERATED_SIGNAL_DIR)/xdp_keyword_modules.generated.h: FORCE
	$(PYTHON) benchmarks/policy/generate_policy_modules.py $(KEYWORD_POLICY) $(GENERATED_SIGNAL_DIR) \
		--signal-profile $(SIGNAL_PROFILE) $(if $(filter 1,$(XSR_DISTILL_PARITY_DEBUG)),--parity-debug,)

FORCE:

parity-build:
	$(MAKE) clean
	$(MAKE) policy SIGNAL_PROFILE=intent XSR_DISTILL_PARITY_DEBUG=1
	$(MAKE) build SIGNAL_PROFILE=intent XSR_DISTILL_PARITY_DEBUG=1

define require_sudo
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "Error: run this command as: sudo make $@" >&2; \
		exit 1; \
	fi
endef

correctness:
	$(require_sudo)
	@BENCHMARK_SYSTEMS="direct,xsr,vsr" BENCHMARK_PYTHON="$(BENCHMARK_PYTHON)" \
		./benchmarks/routing_wrk/check_environments.sh
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

check-benchmark:
	@test -x "$(BENCHMARK_PYTHON)" || { echo "Error: run 'make benchmark-install' first." >&2; exit 1; }
	@$(BENCHMARK_PYTHON) -c 'import datasets, matplotlib, nbconvert, nbformat, numpy, pandas' >/dev/null 2>&1 || { echo "Error: benchmark Python packages are incomplete; run 'make benchmark-install'." >&2; exit 1; }
	@command -v curl >/dev/null || { echo "Error: curl is required." >&2; exit 1; }
	@command -v ip >/dev/null || { echo "Error: iproute2 is required." >&2; exit 1; }
	@command -v ethtool >/dev/null || { echo "Error: ethtool is required." >&2; exit 1; }
	@command -v iptables >/dev/null || { echo "Error: iptables is required for benchmark setup." >&2; exit 1; }

check-performance: check-benchmark
	@test -x "$(CURDIR)/.tools/wrk/wrk" || command -v wrk >/dev/null || { echo "Error: saturation mode requires standard wrk; run 'make benchmark-install' or 'make install-wrk'." >&2; exit 1; }

check-performance-fixed-rate: check-benchmark
	@test -x "$(CURDIR)/.tools/wrk2/wrk" || command -v "$${WRK2_BIN:-wrk2}" >/dev/null || { echo "Error: fixed-rate mode requires wrk2; run 'make benchmark-install' or 'make install-wrk2'." >&2; exit 1; }

install-wrk:
	./benchmarks/routing_wrk/install_wrk.sh

install-wrk2:
	./benchmarks/routing_wrk/install_wrk2.sh

xdp_router: src/xdp_router.c src/distill_model_loader.c include/xsr/distill_model_loader.h include/xsr/distill_model_format.h include/xsr/router.h bpf/stages/signals/xdp_classifier.bpf.h bpf/stages/signals/xdp_distill_classifier.bpf.h bpf/stages/signals/xdp_ngram_classifier.bpf.h bpf/stages/signals/xdp_bm25_classifier.bpf.h include/xsr/keyword_policy_loader.h $(GENERATED_SIGNAL_DIR)/xdp_keyword_modules.generated.h
	$(CC) $(USER_CFLAGS) src/xdp_router.c src/distill_model_loader.c -o $@ $(LIBBPF_FLAGS)

sk_router: src/sk_router.c src/distill_model_loader.c include/xsr/distill_model_loader.h include/xsr/distill_model_format.h include/xsr/router.h bpf/stages/policy/decision.bpf.h bpf/stages/signals/domains.bpf.h bpf/stages/signals/xdp_classifier.bpf.h bpf/stages/signals/xdp_distill_classifier.bpf.h bpf/stages/signals/xdp_ngram_classifier.bpf.h bpf/stages/signals/xdp_bm25_classifier.bpf.h include/xsr/keyword_policy_loader.h $(GENERATED_SIGNAL_DIR)/xdp_keyword_modules.generated.h
	$(CC) $(USER_CFLAGS) src/sk_router.c src/distill_model_loader.c -o $@ $(LIBBPF_FLAGS) -lpthread

benchmarks/mock_backend: benchmarks/mock_backend.c
	$(CC) -O3 $< -o $@ -lpthread

benchmarks/mock_backend_delayed: benchmarks/mock_backend.c
	$(CC) -O3 -DXSR_MOCK_DELAY=1 $< -o $@ -lpthread

benchmarks/sockmap_lifecycle_semantics: benchmarks/sockmap_lifecycle_semantics.c
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS)

xdp_router.bpf.o: bpf/programs/xdp_router.bpf.c include/xsr/router.h include/xsr/distill_model_format.h bpf/stages/parsing/xdp_datapath_limits.h bpf/stages/parsing/xdp_http_parser.bpf.h bpf/stages/signals/xdp_classifier.bpf.h bpf/stages/signals/xdp_distill_classifier.bpf.h bpf/stages/signals/xdp_ngram_classifier.bpf.h bpf/stages/signals/xdp_jaccard_classifier.bpf.h bpf/stages/signals/xdp_bm25_classifier.bpf.h $(GENERATED_SIGNAL_DIR)/xdp_keyword_modules.generated.h $(GENERATED_SIGNAL_DIR)/xdp_unicode_word.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

sk_router.bpf.o: bpf/programs/sk_router.bpf.c include/xsr/router.h include/xsr/distill_model_format.h bpf/stages/forwarding/sockmap.bpf.h bpf/stages/parsing/xdp_datapath_limits.h bpf/stages/policy/decision.bpf.h bpf/stages/signals/domains.bpf.h bpf/stages/signals/xdp_classifier.bpf.h bpf/stages/signals/xdp_distill_classifier.bpf.h bpf/stages/signals/xdp_ngram_classifier.bpf.h bpf/stages/signals/xdp_jaccard_classifier.bpf.h bpf/stages/signals/xdp_bm25_classifier.bpf.h $(GENERATED_SIGNAL_DIR)/xdp_keyword_modules.generated.h $(GENERATED_SIGNAL_DIR)/xdp_unicode_word.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

clean:
	rm -f xdp_router sk_router xdp_router.bpf.o sk_router.bpf.o benchmarks/mock_backend benchmarks/mock_backend_delayed benchmarks/sockmap_lifecycle_semantics

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

.PHONY: help all build legacy benchmark-build prod dev install benchmark benchmark-install policy parity-build correctness performance performance-fixed-rate wrk check-build check check-benchmark check-performance check-performance-fixed-rate install-wrk install-wrk2 llmrouter-install test-llmrouter clean clean-setup setup iproutes FORCE
