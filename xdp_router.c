/*
  Userspace XDP loader.
  This program loads the XDP program (xdp_router.bpf.c) into the kernel and
  attaches it to a network interface.
*/

// These macros could change:
#define BPF_OBJECT_FILE "xdp_router.bpf.o"
#define XDP_PROGRAM_NAME "xdp_router"
#define XDP_MAP_NAME "counters"
#define XDP_NGRAM_MAP_NAME "xdp_ngram_weights"

#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <errno.h>
#include <net/if.h> // if_nametoindex
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "xdp_router.h"

static const char *counter_names[COUNT_MAX] = {
    [COUNT_TOTAL] = "Total packets",
    [COUNT_IPV4] = "IPv4 packets",
    [COUNT_TCP] = "TCP packets",
    [COUNT_HTTP] = "HTTP packets",
    [COUNT_FRAGMENT] = "Fragment packets",
    [COUNT_NO_PAYLOAD] = "No Payload packets",
    [COUNT_CONTENT_FOUND] = "content packets",
    [COUNT_CONTENT_PARTIAL] = "partial packets",
    [COUNT_ROUTE_CODING] = "route coding",
    [COUNT_ROUTE_GENERAL] = "route general",
    [COUNT_ROUTE_REASONING] = "route reasoning",
};

__u64 read_percpu_counter(int map_fd, __u32 key, int cpu_count) {
  __u64 values[cpu_count];
  __u64 total = 0;

  if (bpf_map_lookup_elem(map_fd, &key, values) != 0)
    return 0;

  for (int cpu = 0; cpu < cpu_count; cpu++)
    total += values[cpu];

  return total;
}

int read_file(const char *path, char **out, size_t *out_size) {
  FILE *file = fopen(path, "rb");
  char *buffer;
  long size;

  if (!file)
    return -1;

  if (fseek(file, 0, SEEK_END) != 0) {
    fclose(file);
    return -1;
  }

  size = ftell(file);
  if (size < 0) {
    fclose(file);
    return -1;
  }

  if (fseek(file, 0, SEEK_SET) != 0) {
    fclose(file);
    return -1;
  }

  buffer = calloc((size_t)size + 1, 1);
  if (!buffer) {
    fclose(file);
    return -1;
  }

  if (fread(buffer, 1, (size_t)size, file) != (size_t)size) {
    free(buffer);
    fclose(file);
    return -1;
  }

  fclose(file);
  *out = buffer;
  *out_size = (size_t)size;
  return 0;
}

int parse_next_int(char **cursor, long *value) {
  char *p = *cursor;
  char *end;

  while (*p && *p != '-' && (*p < '0' || *p > '9'))
    p++;

  if (!*p)
    return -1;

  errno = 0;
  *value = strtol(p, &end, 10);
  if (errno != 0 || end == p)
    return -1;

  *cursor = end;
  return 0;
}

int load_ngram_model_from_path(int map_fd, const char *path) {
  char *json;
  char *cursor;
  size_t json_size;
  long value;
  struct xdp_ngram_weight *weights;
  int result = -1;

  if (read_file(path, &json, &json_size) != 0)
    return -1;

  weights = calloc(XDP_NGRAM_FEATURES, sizeof(*weights));
  if (!weights) {
    free(json);
    return -1;
  }

  cursor = strstr(json, "\"bias\"");
  if (!cursor)
    goto out;

  for (int i = 0; i < 3; i++) {
    if (parse_next_int(&cursor, &value) != 0)
      goto out;
  }

  cursor = strstr(json, "\"weights\"");
  if (!cursor)
    goto out;

  for (int class_id = 0; class_id < 3; class_id++) {
    for (__u32 feature = 0; feature < XDP_NGRAM_FEATURES; feature++) {
      if (parse_next_int(&cursor, &value) != 0)
        goto out;

      if (class_id == 0)
        weights[feature].coding = (short)value;
      else if (class_id == 1)
        weights[feature].general = (short)value;
      else
        weights[feature].reasoning = (short)value;
    }
  }

  for (__u32 feature = 0; feature < XDP_NGRAM_FEATURES; feature++) {
    if (bpf_map_update_elem(map_fd, &feature, &weights[feature], BPF_ANY) != 0)
      goto out;
  }

  printf("Loaded n-gram weights from %s\n", path);
  result = 0;

out:
  free(weights);
  free(json);
  return result;
}

int load_ngram_model(struct bpf_object *obj) {
  const char *model_path = getenv("XDP_NGRAM_MODEL");
  int map_fd = bpf_object__find_map_fd_by_name(obj, XDP_NGRAM_MAP_NAME);

  if (map_fd < 0) {
    fprintf(stderr, "Failed to find map: %s\n", XDP_NGRAM_MAP_NAME);
    return -1;
  }

  if (model_path && load_ngram_model_from_path(map_fd, model_path) == 0)
    return 0;

  if (load_ngram_model_from_path(map_fd, "xdp_ngram_model.json") == 0)
    return 0;

  fprintf(stderr, "Failed to load n-gram model weights\n");
  return -1;
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

  if (load_ngram_model(obj) != 0)
    return 1;

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

    for (__u32 key = 0; key < COUNT_MAX; key++) {
      if (!counter_names[key])
        continue;

      printf("%s: %llu\n", counter_names[key],
             (unsigned long long)read_percpu_counter(map_fd, key, cpu_count));
    }
  }

  bpf_link__destroy(link);
  bpf_object__close(obj);
  return 0;
}
