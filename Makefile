CC ?= gcc
BPF_CLANG ?= clang
PKG_CONFIG ?= pkg-config
PYTHON ?= python3

ARCH := $(shell uname -m)
BPF_CFLAGS := -O2 -g -target bpf \
	-D__BPF__=1 \
	-D__TARGET_ARCH_x86 \
	-I. -Ibpf \
	-I/usr/include/$(ARCH)-linux-gnu

USER_CFLAGS := -Wall -O2
DEV_DEFS := -DXDP_DEBUG=1 -DXDP_PROFILE=1
LIBBPF_FLAGS := $(shell $(PKG_CONFIG) --cflags --libs libbpf)
XDP_NETNS ?= ns1
XDP_HOST_IF ?= veth0
XDP_PEER_IF ?= veth1
XDP_HOST_ADDR ?= 10.10.0.1/24
XDP_PEER_ADDR ?= 10.10.0.2/24
KEYWORD_POLICY ?= config/policy_ngram.yaml
NGRAM_MODEL ?= models/xdp_ngram_model_fnv.json

.DEFAULT_GOAL := all

all: xdp_router sk_router xdp_router.bpf.o sk_router.bpf.o benchmarks/mock_backend

dev: USER_CFLAGS += $(DEV_DEFS)
dev: BPF_CFLAGS += $(DEV_DEFS)
dev: clean all

prod: USER_CFLAGS += -O3
prod: BPF_CFLAGS += -O2
prod: clean all

xdp_router: xdp_router.c xdp_router.h bpf/xdp_ngram_model.generated.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS)

sk_router: sk_router.c xdp_router.h bpf/xdp_decision.bpf.h bpf/xdp_signals.bpf.h bpf/xdp_ngram_model.generated.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS) -lpthread

benchmarks/mock_backend: benchmarks/mock_backend.c
	$(CC) -O3 $< -o $@ -lpthread

bpf/xdp_ngram_model.generated.h: $(NGRAM_MODEL) scripts/generate_ngram_header.py
	$(PYTHON) scripts/generate_ngram_header.py $(NGRAM_MODEL) $@

xdp_router.bpf.o: bpf/xdp_router.bpf.c xdp_router.h bpf/xdp_http_parser.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_ngram_classifier.bpf.h bpf/xdp_ngram_model.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

sk_router.bpf.o: bpf/sk_router.bpf.c xdp_router.h bpf/xdp_decision.bpf.h bpf/xdp_signals.bpf.h bpf/xdp_classifier.bpf.h bpf/xdp_ngram_classifier.bpf.h bpf/xdp_ngram_model.generated.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

clean:
	rm -f xdp_router sk_router xdp_router.bpf.o sk_router.bpf.o bpf/xdp_keyword_policy.generated.h bpf/xdp_ngram_model.generated.h benchmarks/mock_backend

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
	@ip link set $(XDP_HOST_IF) up
	@ip netns exec $(XDP_NETNS) ip link set $(XDP_PEER_IF) up
	@ip netns exec $(XDP_NETNS) ip link set lo up
	@echo "setup complete: $(XDP_HOST_IF)=$(XDP_HOST_ADDR), $(XDP_NETNS)/$(XDP_PEER_IF)=$(XDP_PEER_ADDR)"

.PHONY: all dev clean clean-setup setup
