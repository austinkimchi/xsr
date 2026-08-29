#include "distill_model_loader.h"
#include <bpf/bpf.h>
#include <endian.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define DISTILL_CLASSES 14
#define DISTILL_BUCKETS 4096
#define DISTILL_PROMPT_BYTES 16384
struct __attribute__((packed)) distill_file_header {
  char magic[8]; uint32_t version, classes, buckets, prompt_bytes, score_bound; double scale;
};
struct distill_bucket { int8_t weight[DISTILL_CLASSES]; };
struct distill_config {
  int32_t bias[DISTILL_CLASSES];
  uint32_t enabled, prompt_byte_limit, proven_score_bound;
};

int populate_distill_model(struct bpf_object *obj, const char *path) {
  struct distill_file_header header;
  struct distill_config config = {};
  struct distill_bucket bucket;
  int weights_fd, config_fd;
  FILE *input;
  int64_t max_bias = 0;
  if (!path || !*path)
    return 0;
  weights_fd = bpf_object__find_map_fd_by_name(obj, "xdp_distill_weights");
  config_fd = bpf_object__find_map_fd_by_name(obj, "xdp_distill_config_map");
  if (weights_fd < 0 || config_fd < 0) { errno = ENOENT; return -1; }
  input = fopen(path, "rb");
  if (!input)
    return -1;
  if (fread(&header, sizeof(header), 1, input) != 1 ||
      memcmp(header.magic, "XSRFNV14", 8) != 0 || le32toh(header.version) != 1 ||
      le32toh(header.classes) != DISTILL_CLASSES ||
      le32toh(header.buckets) != DISTILL_BUCKETS ||
      le32toh(header.prompt_bytes) != DISTILL_PROMPT_BYTES ||
      le32toh(header.score_bound) > INT32_MAX ||
      fread(config.bias, sizeof(config.bias), 1, input) != 1) {
    fclose(input); errno = EINVAL; return -1;
  }
  for (uint32_t index = 0; index < DISTILL_CLASSES; index++)
    config.bias[index] = (int32_t)le32toh((uint32_t)config.bias[index]);
  for (uint32_t index = 0; index < DISTILL_CLASSES; index++) {
    int64_t absolute = config.bias[index] < 0 ? -(int64_t)config.bias[index]
                                               : config.bias[index];
    if (absolute > max_bias)
      max_bias = absolute;
  }
  if (max_bias + (DISTILL_PROMPT_BYTES - 2) * 127 !=
      le32toh(header.score_bound)) {
    fclose(input); errno = EINVAL; return -1;
  }
  for (uint32_t key = 0; key < DISTILL_BUCKETS; key++)
    if (fread(&bucket, sizeof(bucket), 1, input) != 1 ||
        bpf_map_update_elem(weights_fd, &key, &bucket, BPF_ANY) != 0) {
      fclose(input); return -1;
    }
  if (fgetc(input) != EOF) { fclose(input); errno = EFBIG; return -1; }
  fclose(input);
  config.enabled = 1;
  config.prompt_byte_limit = le32toh(header.prompt_bytes);
  config.proven_score_bound = le32toh(header.score_bound);
  uint32_t key = 0;
  return bpf_map_update_elem(config_fd, &key, &config, BPF_ANY);
}
