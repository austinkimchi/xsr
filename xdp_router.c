/*
  Userspace XDP loader.
  This program loads the XDP program (xdp_router.bpf.c) into the kernel and
  attaches it to a network interface.
*/

// These macros could change:
#define BPF_OBJECT_FILE "xdp_router.bpf.o"
#define XDP_PROGRAM_NAME "xdp_router"
#define XDP_MAP_NAME "counters"

#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <net/if.h> // if_nametoindex
#include <stdio.h>

#include "xdp_router.h"

__u64 read_percpu_counter(int map_fd, __u32 key, int cpu_count) {
  __u64 values[cpu_count];
  __u64 total = 0;

  if (bpf_map_lookup_elem(map_fd, &key, values) != 0)
    return 0;

  for (int cpu = 0; cpu < cpu_count; cpu++)
    total += values[cpu];

  return total;
}

int main(void) {
  struct bpf_object *obj;
  struct bpf_program *prog;
  struct bpf_link *link;

  int map_fd;
  int ifindex;

  ifindex = if_nametoindex("veth0");
  if (!ifindex) {
    perror("if_nametoindex");
    return 1;
  }

  // Load BPF object file into the kernel
  obj = bpf_object__open_file(BPF_OBJECT_FILE, NULL);
  if (libbpf_get_error(obj)) { // File might not exist
    fprintf(stderr, "Failed to open BPF object file: %s\n", BPF_OBJECT_FILE);
    return 1;
  }

  if (bpf_object__load(obj)) { // Loading the object file could fail
    fprintf(stderr, "Failed to load BPF object file: %s\n", BPF_OBJECT_FILE);
    return 1;
  }

  // Find XDP program by name
  prog = bpf_object__find_program_by_name(obj, XDP_PROGRAM_NAME);
  if (!prog) { // Program might not exist
    fprintf(stderr, "Failed to find XDP program: %s\n", XDP_PROGRAM_NAME);
    return 1;
  }

  // Attach XDP program to the network interface
  link = bpf_program__attach_xdp(prog, ifindex);
  if (libbpf_get_error(link)) { // Attaching the program could fail
    fprintf(stderr, "Failed to attach XDP program to interface index: %d\n",
            ifindex);
    return 1;
  }

  // Find the map file descriptor by name
  map_fd = bpf_object__find_map_fd_by_name(obj, XDP_MAP_NAME);
  if (map_fd < 0) {
    fprintf(stderr, "Failed to find map: counters\n");
    return 1;
  }

  printf("XDP attached to interface index %d\n", ifindex);
  printf("Counters map FD: %d\n", map_fd);

  while (1) {
    int cpu_count = libbpf_num_possible_cpus();

    // Read the counters from the map
    printf("Total packets: %llu\n", (unsigned long long)read_percpu_counter(
                                        map_fd, COUNT_TOTAL, cpu_count));

    printf("IPv4 packets: %llu\n", (unsigned long long)read_percpu_counter(
                                       map_fd, COUNT_IPV4, cpu_count));

    printf("TCP packets: %llu\n", (unsigned long long)read_percpu_counter(
                                      map_fd, COUNT_TCP, cpu_count));
    printf("No Payload packets: %llu\n",
           (unsigned long long)read_percpu_counter(map_fd, COUNT_NO_PAYLOAD,
                                                   cpu_count));
    printf("HTTP packets: %llu\n", (unsigned long long)read_percpu_counter(
                                       map_fd, COUNT_HTTP, cpu_count));
    printf("content packets: %llu\n",
           (unsigned long long)read_percpu_counter(map_fd, COUNT_CONTENT_FOUND,
                                                   cpu_count));
    printf("partial packets: %llu\n",
           (unsigned long long)read_percpu_counter(
               map_fd, COUNT_CONTENT_PARTIAL, cpu_count));
  }

  bpf_link__destroy(link);
  bpf_object__close(obj);
  return 0;
}