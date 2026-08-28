# Routing performance summary

## Provenance

- XSR commit: `cce2d8b1dd52709ef6ab158baf6a1082c12aa054` (dirty)
- XSR build/routing: `prod` / `SK_SKB/SOCKMAP`
- Benchmark: `paper` / `saturation`; trials=`5`, duration=`45s`, warm-up=`5s`
- Linux kernel / CPUs: `6.8.0-134-generic` / `4`
- Policy SHA-256: `957a72503a39b2360a94ad2ba8f56f6c1f6da51e3b7182e5d768315ab9c37ec8`
- Prompt corpus SHA-256: `6664c3bf2fc9fc04ccd724da99a921a2afadf1a438dd10df5a523b6f08a7d582`
- VSR image ID: `unavailable`
- Envoy image ID/version: `unavailable` / `None`
- Raw trial artifacts: [`raw/`](raw/); full provenance: [`metadata.json`](metadata.json)

| Mode | Configuration | System | Topology | Valid | Failed | Throughput mean ± 95% CI |
| --- | --- | --- | --- | ---: | ---: | ---: |
| saturation | concurrency-1 | Direct backend | host-veth | 5 | 0 | 29168.47 ± 96.29 |
| saturation | concurrency-1 | Envoy only | docker-bridge | 5 | 0 | 2124.37 ± 5.08 |
| saturation | concurrency-1 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 399.97 ± 0.45 |
| saturation | concurrency-1 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 7352.08 ± 169.00 |
| saturation | concurrency-128 | Direct backend | host-veth | 5 | 0 | 367703.87 ± 814.77 |
| saturation | concurrency-128 | Envoy only | docker-bridge | 5 | 0 | 15357.97 ± 196.32 |
| saturation | concurrency-128 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1073.38 ± 11.77 |
| saturation | concurrency-128 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 25956.69 ± 45.24 |
| saturation | concurrency-16 | Direct backend | host-veth | 5 | 0 | 361888.19 ± 758.35 |
| saturation | concurrency-16 | Envoy only | docker-bridge | 5 | 0 | 10643.96 ± 38.45 |
| saturation | concurrency-16 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1111.01 ± 8.39 |
| saturation | concurrency-16 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 26256.78 ± 66.06 |
| saturation | concurrency-192 | Direct backend | host-veth | 5 | 0 | 364767.11 ± 864.22 |
| saturation | concurrency-192 | Envoy only | docker-bridge | 5 | 0 | 15489.60 ± 202.85 |
| saturation | concurrency-192 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1074.29 ± 2.94 |
| saturation | concurrency-192 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 25581.24 ± 1135.46 |
| saturation | concurrency-2 | Direct backend | host-veth | 5 | 0 | 46806.43 ± 60.01 |
| saturation | concurrency-2 | Envoy only | docker-bridge | 5 | 0 | 3751.57 ± 16.44 |
| saturation | concurrency-2 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 747.80 ± 9.59 |
| saturation | concurrency-2 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 12426.62 ± 41.94 |
| saturation | concurrency-256 | Direct backend | host-veth | 5 | 0 | 361452.96 ± 1787.40 |
| saturation | concurrency-256 | Envoy only | docker-bridge | 5 | 0 | 15451.62 ± 249.14 |
| saturation | concurrency-256 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1064.65 ± 5.97 |
| saturation | concurrency-256 | XSR (SK_SKB/SOCKMAP) | host-veth | 2 | 3 | 3637.30 ± 4365.27 |
| saturation | concurrency-32 | Direct backend | host-veth | 5 | 0 | 369990.46 ± 886.34 |
| saturation | concurrency-32 | Envoy only | docker-bridge | 5 | 0 | 13352.70 ± 92.99 |
| saturation | concurrency-32 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1111.31 ± 2.24 |
| saturation | concurrency-32 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 26209.53 ± 38.71 |
| saturation | concurrency-4 | Direct backend | host-veth | 5 | 0 | 344028.04 ± 959.68 |
| saturation | concurrency-4 | Envoy only | docker-bridge | 5 | 0 | 5345.16 ± 55.73 |
| saturation | concurrency-4 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1063.37 ± 3.42 |
| saturation | concurrency-4 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 24804.85 ± 509.17 |
| saturation | concurrency-512 | Direct backend | host-veth | 3 | 0 | 360770.52 ± 918.46 |
| saturation | concurrency-512 | Envoy only | docker-bridge | 4 | 0 | 15766.14 ± 186.94 |
| saturation | concurrency-512 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1066.11 ± 4.77 |
| saturation | concurrency-512 | XSR (SK_SKB/SOCKMAP) | host-veth | 0 | 5 | unavailable |
| saturation | concurrency-64 | Direct backend | host-veth | 5 | 0 | 369490.99 ± 981.34 |
| saturation | concurrency-64 | Envoy only | docker-bridge | 5 | 0 | 14867.26 ± 223.24 |
| saturation | concurrency-64 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1090.43 ± 2.50 |
| saturation | concurrency-64 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 26217.39 ± 59.38 |
| saturation | concurrency-8 | Direct backend | host-veth | 5 | 0 | 351296.35 ± 2517.76 |
| saturation | concurrency-8 | Envoy only | docker-bridge | 5 | 0 | 7268.58 ± 10.08 |
| saturation | concurrency-8 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1118.74 ± 4.65 |
| saturation | concurrency-8 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 26397.80 ± 96.79 |
| saturation | concurrency-96 | Direct backend | host-veth | 5 | 0 | 368712.00 ± 829.39 |
| saturation | concurrency-96 | Envoy only | docker-bridge | 5 | 0 | 15143.60 ± 172.73 |
| saturation | concurrency-96 | VSR (Envoy ExtProc) | docker-bridge | 5 | 0 | 1084.95 ± 2.05 |
| saturation | concurrency-96 | XSR (SK_SKB/SOCKMAP) | host-veth | 5 | 0 | 26047.13 ± 81.61 |
