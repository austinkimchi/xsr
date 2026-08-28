CC ?= gcc
BPF_CLANG ?= clang
PKG_CONFIG ?= pkg-config
PYTHON ?= python3
NOFILE_LIMIT ?= 16384

ARCH := $(shell uname -m)
BPF_CFLAGS := -O2 -g -target bpf \
	-D__BPF__=1 \
	-D__TARGET_ARCH_x86 \
	-I. -Ibpf \
	-I/usr/include/$(ARCH)-linux-gnu

OPT_CFLAGS := -O2
USER_CFLAGS := -Wall $(OPT_CFLAGS)
DEV_DEFS := -DXDP_DEBUG=1 -DXDP_PROFILE=1
LIBBPF_FLAGS := $(shell $(PKG_CONFIG) --cflags --libs libbpf)
XDP_NETNS ?= ns1
XDP_HOST_IF ?= veth0
XDP_PEER_IF ?= veth1
XDP_HOST_ADDR ?= 10.10.0.1/24
XDP_PEER_ADDR ?= 10.10.0.2/24
KEYWORD_POLICY ?= config/policy_ngram.yaml
VSR_BACKEND_PORTS ?= 18391 18392 18393 18394 18395
# Optional arguments forwarded by `make correctness`, for example:
# sudo make correctness args="--modes direct-netns,xdp"
args ?=

.DEFAULT_GOAL := all

help:
	@echo "XDP router commands:"
	@echo "  make                     Build all router, BPF, and benchmark binaries"
	@echo "  make all                 Build all router, BPF, and benchmark binaries"
	@echo "  make dev                 Clean and build with debug/profile instrumentation"
	@echo "  make prod                Clean and build optimized binaries"
	@echo "  make check               Check required build and network dependencies"
	@echo "  make check-performance   Check dependencies plus saturation-mode wrk"
	@echo "  make check-performance-fixed-rate  Check dependencies plus fixed-rate wrk2"
	@echo "  make install-wrk2        Build the pinned wrk2 release in .tools/wrk2/"
	@echo "  sudo make setup          Create or repair ns1 and the veth0/veth1 pair"
	@echo "  sudo make iproutes       Allow benchmark backend ports through INPUT"
	@echo "  sudo make correctness [args=\"...\"]"
	@echo "                           Set up and run routing correctness checks"
	@echo "  sudo make sockmap-smoke"
	@echo "                           Verify SOCKMAP routing, including first-request delivery"
	@echo "  sudo make performance [args=\"CONCURRENCY=1 DURATION=30s ...\"]"
	@echo "                           Run the saturation (wrk) benchmark"
	@echo "  sudo make performance-fixed-rate [args=\"RATES='100 250 500' ...\"]"
	@echo "                           Run the fixed-rate (wrk2) benchmark"
	@echo "  sudo make wrk [args=\"...\"]"
	@echo "                           Alias for performance"
	@echo "  make clean               Remove built binaries and generated policy headers"
	@echo "  sudo make clean-setup    Remove ns1 and veth0"
	@echo ""
	@echo "Performance options: VLLM_IP, VLLM_HOST, VLLM_PORT, CONCURRENCY,"
	@echo "                     DURATION, WRK_BIN, WRK2_BIN, RATE/RATES, and INCLUDE_XDP=1 (legacy XSR)."

all: xdp_router sk_router xdp_router.bpf.o sk_router.bpf.o benchmarks/mock_backend

dev: USER_CFLAGS += $(DEV_DEFS)
dev: BPF_CFLAGS += $(DEV_DEFS)
dev: clean all

prod: OPT_CFLAGS := -O3
prod: USER_CFLAGS := -Wall $(OPT_CFLAGS)
prod: clean all

define require_sudo
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "Error: run this benchmark as: sudo make $@" >&2; \
		exit 1; \
	fi
endef

correctness:
	$(require_sudo)
	$(MAKE) check
	$(MAKE) setup
	$(MAKE) iproutes
	./benchmarks/run_routing_correctness.sh $(args)

sockmap-smoke:
	$(require_sudo)
	$(PYTHON) tests/probe_sk_router_smoke.py

performance:
	$(require_sudo)
	$(MAKE) check-performance
	$(MAKE) setup
	$(MAKE) iproutes
	@ulimit -n $(NOFILE_LIMIT) || { echo "Error: unable to set open-file limit to $(NOFILE_LIMIT)." >&2; exit 1; }; \
		echo "Effective open-file limit: $$(ulimit -n)"; \
		BENCHMARK_MODE=saturation ./benchmarks/run_routing_performance.sh $(args)

performance-fixed-rate:
	$(require_sudo)
	$(MAKE) check-performance-fixed-rate
	$(MAKE) setup
	$(MAKE) iproutes
	@ulimit -n $(NOFILE_LIMIT) || { echo "Error: unable to set open-file limit to $(NOFILE_LIMIT)." >&2; exit 1; }; \
		echo "Effective open-file limit: $$(ulimit -n)"; \
		BENCHMARK_MODE=fixed-rate ./benchmarks/run_routing_performance.sh $(args)

wrk: performance

check:
	@command -v "$(CC)" >/dev/null || { echo "Error: compiler '$(CC)' is required." >&2; exit 1; }
	@command -v "$(BPF_CLANG)" >/dev/null || { echo "Error: clang is required for BPF builds." >&2; exit 1; }
	@command -v "$(PKG_CONFIG)" >/dev/null || { echo "Error: pkg-config is required." >&2; exit 1; }
	@command -v "$(PYTHON)" >/dev/null || { echo "Error: python3 is required." >&2; exit 1; }
	@$(PYTHON) -c 'import yaml' >/dev/null 2>&1 || { echo "Error: Python yaml module is required (install python3-yaml)." >&2; exit 1; }
	@$(PKG_CONFIG) --exists libbpf || { echo "Error: libbpf development files are required (pkg-config libbpf)." >&2; exit 1; }
	@command -v ip >/dev/null || { echo "Error: iproute2 (ip) is required." >&2; exit 1; }
	@command -v iptables >/dev/null || { echo "Error: iptables is required." >&2; exit 1; }

check-performance: check
	@command -v wrk >/dev/null || { echo "Error: saturation mode requires standard wrk. Install it with your package manager (for example: apt-get install wrk)." >&2; exit 1; }

check-performance-fixed-rate: check
	@test -x "$(CURDIR)/.tools/wrk2/wrk" || command -v "$${WRK2_BIN:-wrk2}" >/dev/null || { echo "Error: fixed-rate mode requires wrk2. Run 'make install-wrk2' or set WRK2_BIN=/path/to/wrk2." >&2; exit 1; }

install-wrk2:
	./benchmarks/routing_wrk/install_wrk2.sh

xdp_router: xdp_router.c xdp_router.h bpf/xdp_jaccard_classifier.bpf.h bpf/xdp_jaccard_policy.generated.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS)

sk_router: sk_router.c xdp_router.h bpf/xdp_decision.bpf.h bpf/xdp_signals.bpf.h bpf/xdp_jaccard_classifier.bpf.h bpf/xdp_jaccard_policy.generated.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS) -lpthread

benchmarks/mock_backend: benchmarks/mock_backend.c
	$(CC) -O3 $< -o $@ -lpthread

bpf/xdp_jaccard_policy.generated.h: $(KEYWORD_POLICY) scripts/generate_jaccard_policy_header.py scripts/generate_keyword_header.py
	$(PYTHON) scripts/generate_jaccard_policy_header.py $(KEYWORD_POLICY) $@

xdp_router.bpf.o: bpf/xdp_router.bpf.c xdp_router.h bpf/xdp_http_parser.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_jaccard_classifier.bpf.h bpf/xdp_jaccard_policy.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

sk_router.bpf.o: bpf/sk_router.bpf.c xdp_router.h bpf/xdp_decision.bpf.h bpf/xdp_signals.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_jaccard_classifier.bpf.h bpf/xdp_jaccard_policy.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

clean:
	rm -f xdp_router sk_router xdp_router.bpf.o sk_router.bpf.o bpf/xdp_keyword_policy.generated.h bpf/xdp_jaccard_policy.generated.h bpf/xdp_ngram_model.generated.h benchmarks/mock_backend

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

# Permit vLLM-SR's Docker bridge to reach the five marker backends used by
# the routing benchmark.  INPUT is commonly DROP on development hosts.
iproutes:
	@for port in $(VSR_BACKEND_PORTS); do \
		iptables -C INPUT -p tcp --dport $$port -j ACCEPT 2>/dev/null || \
		iptables -I INPUT 1 -p tcp --dport $$port -j ACCEPT; \
	done
	@echo "benchmark backend ports allowed: $(VSR_BACKEND_PORTS)"

.PHONY: help all dev prod correctness sockmap-smoke performance performance-fixed-rate wrk check check-performance check-performance-fixed-rate install-wrk2 clean clean-setup setup iproutes
