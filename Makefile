CC ?= gcc
BPF_CLANG ?= clang
PKG_CONFIG ?= pkg-config

ARCH := $(shell uname -m)
BPF_CFLAGS := -O2 -g -target bpf \
	-D__TARGET_ARCH_x86 \
	-I/usr/include/$(ARCH)-linux-gnu

USER_CFLAGS := -Wall -O2
LIBBPF_FLAGS := $(shell $(PKG_CONFIG) --cflags --libs libbpf)

.DEFAULT_GOAL := all

all: xdp_router xdp_router.bpf.o

xdp_router: xdp_router.c xdp_router.h
	$(CC) $(USER_CFLAGS) $< -o $@ $(LIBBPF_FLAGS)

xdp_router.bpf.o: xdp_router.bpf.c xdp_router.h xdp_http_parser.bpf.h xdp_ngram_classifier.bpf.h
	$(BPF_CLANG) $(BPF_CFLAGS) -c $< -o $@

clean:
	rm -f xdp_router xdp_router.bpf.o

.PHONY: all clean
