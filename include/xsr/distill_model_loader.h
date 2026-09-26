#ifndef DISTILL_MODEL_LOADER_H
#define DISTILL_MODEL_LOADER_H
#include <bpf/libbpf.h>
int populate_distill_model(struct bpf_object *obj, const char *path);
#endif
