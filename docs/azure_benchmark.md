# Azure paper benchmark readiness

The benchmark runner provisions no Azure resources and accepts no cloud
credentials. Prepare the VM, clone the reviewed commit, and start the pinned VSR
Envoy deployment separately. The local readiness sequence is:

```bash
git clone https://github.com/austinkimchi/xsr.git
cd xsr
git switch master
make benchmark-install
sudo systemctl enable --now docker
sudo make setup iproutes
make test
make profile-check
make test-llmrouter
make prod
sudo make benchmark
```

`sudo make benchmark` is read-only. It checks Linux, build/libbpf tools,
SOCKMAP/SK_SKB capabilities, both wrk variants, Python environments, the pinned
LLMRouter revision, Docker, the running VSR Envoy container, and the configured
`veth0` plus `ns1/veth1` addresses.
Where kernel configuration is readable, `CONFIG_BPF`, `CONFIG_BPF_SYSCALL`, and
`CONFIG_BPF_STREAM_PARSER` are mandatory. The runner also starts and routes
through XSR once before any timed trial, so a BPF-object load failure on the
actual Azure kernel is an invocation-level failure gate.

The repository expects the external VSR deployment's Envoy container to be
running as `vllm-sr-envoy-container` (override with `VLLM_HOST`). Verify its
identity before the canary:

```bash
sudo docker inspect --format '{{.State.Running}} {{.Image}} {{.Config.Image}}' \
  vllm-sr-envoy-container
```

## Azure canary

Use production XSR settings but override only run length and trial count. This
exercises all five systems at the reviewed connection count without launching
the long experiment:

```bash
sudo make performance \
  args="BENCHMARK_PROFILE=paper TRIALS=1 CONCURRENCY=64 DURATION=5s WARMUP_DURATION=3s"
sudo make performance-fixed-rate \
  args="BENCHMARK_PROFILE=paper TRIALS=1 CONCURRENCY=64 DURATION=5s \
  WARMUP_DURATION=3s RATES='100 500'"
```

For an intent-manifest corpus, add the following assignments to both `args`
strings (the exporter sidecar normally supplies the workload identity):

```text
PROMPTS_FILE=/absolute/path/intent-test.jsonl
XSR_DISTILL_MODEL=/absolute/path/distilled_int8.xsrf
SIGNAL_PROFILE=intent
```

Use `SIGNAL_PROFILE=ngram`, `bm25`, or `intent` for every paper run. The runner
uses that single value for the compiled XSR signal set and the corresponding
LLMRouter adapter, and fails on a mismatch. `mixed` is reserved for explicit
mixed-function tests. Paper builds always require
`XSR_DISTILL_PARITY_DEBUG=0`.

Before a VSR run, automatic verification trusts only narrow active evidence:
an explicit router command-line selector, the exact configuration file named
by that command line, the corresponding model/config identity, and a simply
provable active Envoy ExtProc binding. Environment-variable names, label names,
mount destinations/types, and a hash of the active argv are recorded only as
minimal provenance; their values do not certify a classifier. If the active
configuration or binding is absent or ambiguous (including a multi-listener
Envoy layout), supply a reviewed fail-closed contract:

```text
VSR_SIGNAL_PROFILE=bm25
VSR_CONFIG_PATH=/absolute/path/reviewed-vsr-config.yaml
VSR_CONFIG_SHA256=<reviewed-lowercase-sha256>
```

The config hash must match. Intent inspection additionally looks for both the
mmBERT identity and a LoRA/adapter identity. Results distinguish automatic
inspection from a caller-reviewed hash contract in `manifest.json`,
`metadata.json`, and `vsr-verification.json`.

Do not proceed unless all five systems start, routing preflight and the Azure
kernel BPF load pass, the LLMRouter revision matches, all HTTP/socket error
counts are zero, and direct throughput is comfortably above XSR. If direct and
XSR flatten together, treat the client as the suspected ceiling. Review
`metadata.json` for a clean XSR commit, kernel, CPU/NUMA/memory, prompt and
policy hashes, workload identity, and VSR/Envoy image IDs.

## Long paper collection (only after the canary)

The saturation run keeps the full `1,2,4,8,16,32,64,96,128,192` sweep. The
fixed-rate run measures only the reviewed 64-connection slice:

```bash
sudo make performance args="BENCHMARK_PROFILE=paper"
sudo make performance-fixed-rate \
  args="BENCHMARK_PROFILE=paper CONCURRENCY=64 RATES='100 250 500 750 900'"
```

Add `INCLUDE_STRESS=1` only to an optional saturation run to append `256,512`.
Do not add it to the paper-default command.

XSR, VSR, and LLMRouter remain alive across load warm-up and timed measurement.
The XSR userspace lifecycle manager detects frontend peer closure, removes the
complete six-socket connection set, and returns its slot block for reuse.
After the warm-up client exits, the runner queries XSR's status socket and waits
for zero active connection sets before starting measurement. Metadata records
`xsr_warmup_lifecycle=same-process-load-warmup` and
`xsr_measured_instance_warmed=true`; a PID mismatch or cleanup quarantine makes
the trial fail rather than silently measuring a fresh or contaminated process.
