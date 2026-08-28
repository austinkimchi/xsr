# Routing performance summary

## Provenance

- XSR commit: `e1e6258d1e1d74f8d0d6fdcaafecfe54729148e9` (dirty)
- XSR build/routing: `prod` / `SK_SKB/SOCKMAP`
- Benchmark: `paper` / `fixed-rate`; trials=`5`, duration=`45s`, warm-up=`5s`
- Linux kernel / CPUs: `6.8.0-138-generic` / `4`
- Policy SHA-256: `957a72503a39b2360a94ad2ba8f56f6c1f6da51e3b7182e5d768315ab9c37ec8`
- Prompt corpus SHA-256: `6664c3bf2fc9fc04ccd724da99a921a2afadf1a438dd10df5a523b6f08a7d582`
- VSR image ID: `unavailable`
- Envoy image ID/version: `unavailable` / `None`
- Raw trial artifacts: [`raw/`](raw/); full provenance: [`metadata.json`](metadata.json)

| Mode | Configuration | System | Topology | Valid | Failed | Throughput mean ± 95% CI |
| --- | --- | --- | --- | ---: | ---: | ---: |
| fixed-rate | rate-100_concurrency-64 | Direct backend | host-veth | 5 | 0 | 100.08 ± 0.00 |
| fixed-rate | rate-100_concurrency-64 | Envoy only | docker-bridge | 5 | 0 | 100.07 ± 0.00 |
| fixed-rate | rate-100_concurrency-64 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 100.05 ± 0.01 |
| fixed-rate | rate-100_concurrency-64 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 100.08 ± 0.00 |
| fixed-rate | rate-250_concurrency-64 | Direct backend | host-veth | 5 | 0 | 249.56 ± 0.62 |
| fixed-rate | rate-250_concurrency-64 | Envoy only | docker-bridge | 5 | 0 | 250.06 ± 0.00 |
| fixed-rate | rate-250_concurrency-64 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 249.72 ± 0.55 |
| fixed-rate | rate-250_concurrency-64 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 250.08 ± 0.00 |
| fixed-rate | rate-500_concurrency-64 | Direct backend | host-veth | 5 | 0 | 500.53 ± 0.01 |
| fixed-rate | rate-500_concurrency-64 | Envoy only | docker-bridge | 5 | 0 | 500.48 ± 0.01 |
| fixed-rate | rate-500_concurrency-64 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 500.45 ± 0.02 |
| fixed-rate | rate-500_concurrency-64 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 500.51 ± 0.03 |
| fixed-rate | rate-750_concurrency-64 | Direct backend | host-veth | 5 | 0 | 750.07 ± 0.01 |
| fixed-rate | rate-750_concurrency-64 | Envoy only | docker-bridge | 5 | 0 | 750.06 ± 0.01 |
| fixed-rate | rate-750_concurrency-64 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 749.99 ± 0.02 |
| fixed-rate | rate-750_concurrency-64 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 750.05 ± 0.01 |
| fixed-rate | rate-900_concurrency-64 | Direct backend | host-veth | 5 | 0 | 897.84 ± 2.49 |
| fixed-rate | rate-900_concurrency-64 | Envoy only | docker-bridge | 5 | 0 | 899.90 ± 0.02 |
| fixed-rate | rate-900_concurrency-64 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 899.75 ± 0.17 |
| fixed-rate | rate-900_concurrency-64 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 899.89 ± 0.03 |
