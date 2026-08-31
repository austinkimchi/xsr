# SOCKMAP connection lifecycle

XSR's SOCKMAP router owns one frontend socket and five backend sockets per
accepted connection. Before connection reaping was added,
`add_connection_set()` returned after installing them and discarded the five
backend FD values. The accepted frontend FD also stayed open. Six cookie keys
remained in `sk_routes`, request parsing could leave the client cookie in
`sk_http_flows` or `sk_route_decisions`, and the allocator advanced by six
without ever reusing a slot. Partial setup failure could leave already-inserted
map entries as well.

The lifecycle manager now retains all six FDs, their cached socket cookies, and
their six SOCKMAP slots. One epoll loop drives accepts, status queries, and a
100 ms maintenance `timerfd`. At each tick, one zero-time `poll()` checks all
active frontend FDs for `POLLRDHUP`, `POLLHUP`, or `POLLERR`; it never reads
request payloads and installs no persistent readiness hook on a data socket.
`POLLERR`, `POLLHUP`, and invalid FDs are fatal and reap immediately.
`POLLRDHUP` alone is only a peer write-side FIN, so it marks a drain state.
For a client with one outstanding response, XSR propagates the write-side
shutdown to all five backend connections. The selected backend can finish a
multi-write or streaming response before observing EOF and closing; unused
backends close without a request. Cleanup waits until every backend response
side has closed and TCP reports response bytes acknowledged with no
unacknowledged or unsent frontend data. A peer that sent no request, or
half-closed an incomplete parser flow, can be reclaimed immediately.

The backend FIN is the response-completion signal, so a temporary empty send
queue between streamed chunks cannot trigger cleanup. This drain proof
deliberately does not inspect HTTP in userspace or add a BPF map update per
response. Consequently, half-close correctness is scoped to one outstanding
response on the connection. Correlating a FIN with the last of multiple
pipelined or prior keep-alive requests would require explicit per-response
state in the data path; XSR does not claim that transport behavior. Normal
benchmark keep-alive clients close only after their responses and remain
promptly reclaimable.

Persistent frontend/backend epoll monitoring was tested and rejected because
socket readiness callbacks run on data arrival even when the requested mask
contains only hang-up events. Backend monitoring also lets teardown race a
final redirected response skb.
The frontend is therefore the ownership boundary: a backend failure makes its
frontend request fail or time out, after which frontend closure reclaims the
entire set.

## Kernel behavior and cleanup order

The checked-in `benchmarks/sockmap_lifecycle_semantics.c` probe demonstrates the
behavior relied upon by cleanup:

- peer close plus an open userspace FD leaves the SOCKMAP entry installed;
- closing the userspace FD invokes the kernel SOCKMAP close hook and unlinks the
  entry;
- explicit SOCKMAP deletion unlinks the entry without closing the userspace FD;
- deleting an already-empty valid SOCKMAP array slot reports `EINVAL` on the
  tested kernel.

This agrees with Linux's
[`sock_map_close()` and `sock_map_remove_links()` implementation](https://github.com/torvalds/linux/blob/v6.8/net/core/sock_map.c)
and the kernel's
[`BPF_MAP_TYPE_SOCKMAP` documentation](https://docs.kernel.org/bpf/map_sockmap.html).
The semantics probe uses a 64-bit SOCKMAP value because Linux requires that
width for userspace lookup to return a cookie. Production retains its original
32-bit FD value. Its status counter is incremented only after a successful map
insert and decremented only after confirmed deletion (including the kernel's
empty-slot result), so quiescence does not need an intrusive full-map scan.

Teardown therefore proceeds as follows:

1. mark the owned set inactive so later maintenance scans ignore it;
2. explicitly delete all six SOCKMAP slots;
3. delete all six cached cookie keys from `sk_routes`;
4. delete client-cookie state from `sk_http_flows` and
   `sk_route_decisions`;
5. close all six userspace FDs;
6. retry any failed removal after close and return the six-slot block only when
   every old map reference is absent.

An unconfirmed block is quarantined instead of reused. This preserves the
invariant that a recycled slot can never refer to an earlier connection.

## Slot allocator and benchmark quiescence

The 16,384-entry map is divided into 2,730 fixed six-slot blocks, with four
unused tail entries. A free stack allocates and recycles whole blocks. This is
enough structure for the router's fixed topology and avoids a general-purpose
allocator.

When `XSR_STATUS_SOCKET` is set, a local Unix socket reports the router PID,
owned-set counters, free/quarantined blocks, half-close and maintenance-poll
counters, a confirmed SOCKMAP mutation
count, and actual hash-map entry counts for `sk_routes`, `sk_http_flows`, and
`sk_route_decisions`. The
benchmark waits outside timed measurement until the same PID reports zero
active sets and zero lifecycle-map entries. Any PID mismatch or quarantined
block fails the trial.

The maintenance interval bounds cleanup latency at 100 ms and costs ten timer
wakeups and ten batched poll syscalls per second; `lifecycle_poll_total` makes
that wake rate directly observable. Work scales with active
connections, not HTTP requests. A cgroup `BPF_PROG_TYPE_SOCK_OPS`
state-transition program was unnecessary attachment and event-transport
complexity. Per-client threads were rejected because hundreds of lifecycle
threads would perturb the benchmark. Classification and forwarding remain
entirely in SK_SKB/SOCKMAP.
