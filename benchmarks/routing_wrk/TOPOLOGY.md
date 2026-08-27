# Benchmark topology modes

`TOPOLOGY_MODE=host` is the default and retains the existing XSR
SK_SKB/SOCKMAP path: the load generator resides in `ns1` and traverses the
host `veth0` interface to the host-resident routing process.

The Envoy-only baseline intentionally resides on the VSR Docker bridge. It is
started from the same image configured for the VSR Envoy container, on the
same Docker network, with a generated router-only configuration. Its
configuration is validated before a run and contains no ExtProc filter.

`TOPOLOGY_MODE=docker-parity` is not implemented. SOCKMAP maps store socket
references that are meaningful only when the classifier, accepted frontend
sockets, and redirected backend sockets are coordinated in the intended
network namespace. The present host process opens those sockets in the host
namespace while the Docker bridge endpoint exists in a container namespace;
placing only the classifier in a privileged container would therefore not
produce a valid parity path. The runner rejects this mode instead of labeling
host networking as Docker-bridge parity.
