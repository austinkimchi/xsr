#define _GNU_SOURCE

/* Native component harness.  Both realizations run in one optimized binary so
 * process, language-runtime, HTTP, and forwarding costs are outside timing. */

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define ABL_MAX_DOCUMENTS 16
#define ABL_MAX_KEYWORD_GRAMS 32
#define ABL_MAX_WORD_GRAMS 128
#define ABL_NGRAM_MAP_SIZE 2048

enum { ABL_OR, ABL_AND, ABL_NOR };
enum { ROUTE_CODING, ROUTE_OTHERS, ROUTE_MATH, ROUTE_QA, ROUTE_WRITING };

struct abl_ngram_rule {
  double threshold;
  uint32_t threshold_milli;
  uint32_t priority;
  uint8_t route, operator, keyword_count;
};
struct abl_ngram_keyword { const char *text; uint8_t rule_id; };
struct abl_bm25_rule {
  double threshold;
  int64_t threshold_fixed;
  uint32_t priority;
  uint8_t route, operator, document_start, document_count;
  uint16_t document_mask;
};
struct abl_bm25_term {
  const char *text;
  uint32_t hash;
  double reference[ABL_MAX_DOCUMENTS];
  int64_t fixed[ABL_MAX_DOCUMENTS];
  uint8_t stopword;
};

#include "ablation_config.generated.h"

struct prompt { unsigned char *data; uint32_t length; };
struct workload { struct prompt *prompts; size_t count; };

struct gram { uint32_t a, b, c; };
struct keyword_grams {
  struct gram grams[ABL_MAX_KEYWORD_GRAMS];
  uint8_t counts[ABL_MAX_KEYWORD_GRAMS];
  uint8_t unique_count, total_count;
};
struct gram_map_entry { uint64_t key; uint16_t keyword_mask; uint8_t used; };

static struct keyword_grams precomputed_keywords[ABL_NGRAM_KEYWORD_COUNT];
static struct gram_map_entry gram_map[ABL_NGRAM_MAP_SIZE];
static volatile uint64_t benchmark_sink;

static uint64_t now_ns(void) {
  struct timespec value;
  if (clock_gettime(CLOCK_MONOTONIC_RAW, &value) != 0) {
    perror("clock_gettime");
    exit(2);
  }
  return (uint64_t)value.tv_sec * 1000000000ULL + (uint64_t)value.tv_nsec;
}

static uint32_t read_u32(FILE *input) {
  unsigned char bytes[4];
  if (fread(bytes, 1, sizeof(bytes), input) != sizeof(bytes)) {
    fprintf(stderr, "truncated workload header\n");
    exit(2);
  }
  return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
         (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

static struct workload load_workload(const char *path) {
  FILE *input = fopen(path, "rb");
  struct workload result = {};
  uint32_t count;
  if (!input) { perror(path); exit(2); }
  count = read_u32(input);
  if (!count || count > 1000000) { fprintf(stderr, "invalid prompt count\n"); exit(2); }
  result.prompts = calloc(count, sizeof(*result.prompts));
  if (!result.prompts) { perror("calloc"); exit(2); }
  result.count = count;
  for (uint32_t i = 0; i < count; i++) {
    uint32_t length = read_u32(input);
    if (length > 1024 * 1024) { fprintf(stderr, "prompt is too large\n"); exit(2); }
    result.prompts[i].data = malloc((size_t)length + 1);
    result.prompts[i].length = length;
    if (!result.prompts[i].data || fread(result.prompts[i].data, 1, length, input) != length) {
      fprintf(stderr, "truncated workload payload\n"); exit(2);
    }
    result.prompts[i].data[length] = 0;
  }
  if (fgetc(input) != EOF) { fprintf(stderr, "trailing workload bytes\n"); exit(2); }
  fclose(input);
  return result;
}

static int gram_equal(struct gram left, struct gram right) {
  return left.a == right.a && left.b == right.b && left.c == right.c;
}

static uint64_t gram_key(struct gram gram, uint8_t occurrence) {
  /* The paper policies are ASCII.  Keep full scalar values collision-free. */
  uint64_t hash = 1469598103934665603ULL;
  const uint32_t values[] = {gram.a, gram.b, gram.c, occurrence};
  for (size_t i = 0; i < 4; i++) {
    hash ^= values[i];
    hash *= 1099511628211ULL;
  }
  return hash ? hash : 1;
}

static void gram_map_add(struct gram gram, uint8_t occurrence, unsigned keyword) {
  uint64_t key = gram_key(gram, occurrence);
  size_t slot = (size_t)key & (ABL_NGRAM_MAP_SIZE - 1);
  for (size_t probe = 0; probe < ABL_NGRAM_MAP_SIZE; probe++) {
    struct gram_map_entry *entry = &gram_map[(slot + probe) & (ABL_NGRAM_MAP_SIZE - 1)];
    if (!entry->used) { entry->used = 1; entry->key = key; }
    if (entry->key == key) { entry->keyword_mask |= (uint16_t)(1U << keyword); return; }
  }
  fprintf(stderr, "ngram lookup table overflow\n"); exit(2);
}

static uint16_t gram_map_lookup(struct gram gram, uint8_t occurrence) {
  uint64_t key = gram_key(gram, occurrence);
  size_t slot = (size_t)key & (ABL_NGRAM_MAP_SIZE - 1);
  for (size_t probe = 0; probe < ABL_NGRAM_MAP_SIZE; probe++) {
    struct gram_map_entry *entry = &gram_map[(slot + probe) & (ABL_NGRAM_MAP_SIZE - 1)];
    if (!entry->used) return 0;
    if (entry->key == key) return entry->keyword_mask;
  }
  return 0;
}

static unsigned char ascii_lower(unsigned char value) {
  return value >= 'A' && value <= 'Z' ? (unsigned char)(value + 32) : value;
}

static size_t make_grams(const unsigned char *text, size_t length,
                         struct gram *output, size_t capacity) {
  uint32_t previous = ' ', last = ' ';
  size_t count = 0;
  for (size_t position = 0; position < length; position++) {
    uint32_t current = ascii_lower(text[position]);
    if (count < capacity) output[count] = (struct gram){previous, last, current};
    count++;
    previous = last; last = current;
  }
  for (int pad = 0; pad < 2; pad++) {
    if (count < capacity) output[count] = (struct gram){previous, last, ' '};
    count++;
    previous = last; last = ' ';
  }
  return count;
}

static void initialize_ngram_tables(void) {
  for (unsigned keyword = 0; keyword < ABL_NGRAM_KEYWORD_COUNT; keyword++) {
    const char *text = abl_ngram_keywords[keyword].text;
    struct keyword_grams *target = &precomputed_keywords[keyword];
    struct gram all[ABL_MAX_KEYWORD_GRAMS];
    size_t count = make_grams((const unsigned char *)text, strlen(text), all,
                              ABL_MAX_KEYWORD_GRAMS);
    if (count > ABL_MAX_KEYWORD_GRAMS) { fprintf(stderr, "keyword gram overflow\n"); exit(2); }
    target->total_count = (uint8_t)count;
    for (size_t i = 0; i < count; i++) {
      size_t unique;
      for (unique = 0; unique < target->unique_count; unique++)
        if (gram_equal(all[i], target->grams[unique])) break;
      if (unique == target->unique_count) {
        target->grams[unique] = all[i]; target->unique_count++;
      }
      target->counts[unique]++;
    }
    for (size_t i = 0; i < target->unique_count; i++)
      for (uint8_t occurrence = 1; occurrence <= target->counts[i]; occurrence++)
        gram_map_add(target->grams[i], occurrence, keyword);
  }
}

static int is_ngram_word(unsigned char value) {
  return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z') ||
         (value >= '0' && value <= '9') || value == '_' || value == '-';
}

static int score_matches(unsigned same, unsigned all, uint32_t threshold_milli) {
  unsigned diff = all - same;
  return same && all && (uint64_t)(all * all - diff * diff) * 1000ULL >=
                            (uint64_t)all * all * threshold_milli;
}

static void reference_ngram_word(const unsigned char *word, size_t length,
                                 uint16_t *matched_keywords) {
  struct gram query[ABL_MAX_WORD_GRAMS];
  size_t query_count = make_grams(word, length, query, ABL_MAX_WORD_GRAMS);
  if (query_count > ABL_MAX_WORD_GRAMS) return;
  for (unsigned keyword = 0; keyword < ABL_NGRAM_KEYWORD_COUNT; keyword++) {
    struct keyword_grams *candidate = &precomputed_keywords[keyword];
    unsigned same = 0;
    for (size_t i = 0; i < query_count; i++) {
      unsigned query_occurrence = 0;
      for (size_t before = 0; before <= i; before++)
        query_occurrence += gram_equal(query[i], query[before]);
      for (size_t k = 0; k < candidate->unique_count; k++)
        if (gram_equal(query[i], candidate->grams[k]) &&
            query_occurrence <= candidate->counts[k]) { same++; break; }
    }
    unsigned all = (unsigned)query_count + candidate->total_count - same;
    const struct abl_ngram_rule *rule = &abl_ngram_rules[abl_ngram_keywords[keyword].rule_id];
    unsigned diff = all - same;
    double score = same && all ? (double)(all * all - diff * diff) /
                                     (double)(all * all) : 0.0;
    if (same && score >= rule->threshold)
      *matched_keywords |= (uint16_t)(1U << keyword);
  }
}

static void xsr_ngram_word(const unsigned char *word, size_t length,
                           uint16_t *matched_keywords) {
  struct gram query[ABL_MAX_KEYWORD_GRAMS];
  uint8_t occurrences[ABL_MAX_KEYWORD_GRAMS] = {};
  uint8_t intersections[ABL_NGRAM_KEYWORD_COUNT] = {};
  size_t total = make_grams(word, length, query, ABL_MAX_KEYWORD_GRAMS);
  if (total > ABL_MAX_KEYWORD_GRAMS) return;
  for (size_t i = 0; i < total; i++) {
    size_t unique;
    for (unique = 0; unique < i; unique++) if (gram_equal(query[i], query[unique])) break;
    uint8_t occurrence = unique < i ? ++occurrences[unique] : (occurrences[i] = 1);
    uint16_t mask = gram_map_lookup(query[i], occurrence);
    for (unsigned keyword = 0; keyword < ABL_NGRAM_KEYWORD_COUNT; keyword++)
      if (mask & (1U << keyword)) intersections[keyword]++;
  }
  for (unsigned keyword = 0; keyword < ABL_NGRAM_KEYWORD_COUNT; keyword++) {
    unsigned same = intersections[keyword];
    unsigned all = (unsigned)total + precomputed_keywords[keyword].total_count - same;
    const struct abl_ngram_rule *rule = &abl_ngram_rules[abl_ngram_keywords[keyword].rule_id];
    if (score_matches(same, all, rule->threshold_milli))
      *matched_keywords |= (uint16_t)(1U << keyword);
  }
}

typedef void (*ngram_word_fn)(const unsigned char *, size_t, uint16_t *);
static uint64_t ngram_signal(const unsigned char *text, size_t length, ngram_word_fn score_word) {
  uint16_t keywords = 0;
  for (size_t start = 0; start < length;) {
    while (start < length && !is_ngram_word(text[start])) start++;
    size_t end = start;
    while (end < length && is_ngram_word(text[end])) end++;
    if (end > start) score_word(text + start, end - start, &keywords);
    start = end;
  }
  uint64_t signals = 0;
  unsigned keyword_start = 0;
  for (unsigned rule_id = 0; rule_id < ABL_NGRAM_RULE_COUNT; rule_id++) {
    const struct abl_ngram_rule *rule = &abl_ngram_rules[rule_id];
    unsigned matched = 0;
    for (unsigned k = 0; k < rule->keyword_count; k++)
      matched += !!(keywords & (1U << (keyword_start + k)));
    if ((rule->operator == ABL_OR && matched) ||
        (rule->operator == ABL_AND && matched == rule->keyword_count) ||
        (rule->operator == ABL_NOR && !matched)) signals |= 1ULL << rule->route;
    keyword_start += rule->keyword_count;
  }
  return signals;
}

static uint32_t fnv1a(const unsigned char *text, size_t length) {
  uint32_t value = 2166136261U;
  for (size_t i = 0; i < length; i++) value = (value ^ ascii_lower(text[i])) * 16777619U;
  return value;
}

static const struct abl_bm25_term *term_by_hash(uint32_t hash) {
  size_t low = 0, high = ABL_BM25_TERM_COUNT;
  while (low < high) {
    size_t middle = low + (high - low) / 2;
    uint32_t candidate = abl_bm25_terms_by_hash[middle].hash;
    if (candidate < hash) low = middle + 1; else high = middle;
  }
  return low < ABL_BM25_TERM_COUNT && abl_bm25_terms_by_hash[low].hash == hash
             ? &abl_bm25_terms_by_hash[low] : NULL;
}

static const struct abl_bm25_term *term_by_text(const unsigned char *text, size_t length) {
  size_t low = 0, high = ABL_BM25_TERM_COUNT;
  while (low < high) {
    size_t middle = low + (high - low) / 2;
    const char *candidate = abl_bm25_terms_by_text[middle].text;
    size_t candidate_length = strlen(candidate);
    size_t shared = candidate_length < length ? candidate_length : length;
    int order = memcmp(candidate, text, shared);
    if (!order) order = candidate_length < length ? -1 : candidate_length > length ? 1 : 0;
    if (order < 0) low = middle + 1; else high = middle;
  }
  if (low >= ABL_BM25_TERM_COUNT) return NULL;
  const char *candidate = abl_bm25_terms_by_text[low].text;
  return strlen(candidate) == length && !memcmp(candidate, text, length)
             ? &abl_bm25_terms_by_text[low] : NULL;
}

static int bm25_word_char(unsigned char c) { return isalnum(c); }
static int bm25_connector(unsigned char c) { return c == '\'' || c == '.' || c == '_'; }

typedef const struct abl_bm25_term *(*term_lookup_fn)(const unsigned char *, size_t);
static const struct abl_bm25_term *reference_lookup(const unsigned char *text, size_t length) {
  return term_by_text(text, length);
}
static const struct abl_bm25_term *xsr_lookup(const unsigned char *text, size_t length) {
  const struct abl_bm25_term *term = term_by_hash(fnv1a(text, length));
  return term && strlen(term->text) == length && !memcmp(term->text, text, length)
             ? term : NULL;
}

static uint64_t bm25_signal(const unsigned char *text, size_t length,
                            term_lookup_fn lookup, int fixed) {
  double reference_scores[ABL_MAX_DOCUMENTS] = {};
  int64_t fixed_scores[ABL_MAX_DOCUMENTS] = {};
  unsigned char token[4096];
  size_t token_length = 0;
  for (size_t i = 0; i <= length; i++) {
    unsigned char c = i < length ? ascii_lower(text[i]) : ' ';
    if (i < length && (bm25_word_char(c) ||
        (bm25_connector(c) && token_length && i + 1 < length &&
         bm25_word_char(ascii_lower(text[i + 1])) &&
         (c != '.' || (isdigit(token[token_length - 1]) && isdigit(text[i + 1])))))) {
      if (token_length < sizeof(token)) token[token_length++] = c;
      continue;
    }
    if (token_length) {
      const struct abl_bm25_term *term = lookup(token, token_length);
      if (term && !term->stopword) for (unsigned d = 0; d < ABL_MAX_DOCUMENTS; d++) {
        reference_scores[d] += term->reference[d];
        fixed_scores[d] += term->fixed[d];
      }
      token_length = 0;
    }
  }
  uint16_t matched_documents = 0;
  for (unsigned d = 0; d < ABL_MAX_DOCUMENTS; d++)
    for (unsigned r = 0; r < ABL_BM25_RULE_COUNT; r++) {
      const struct abl_bm25_rule *rule = &abl_bm25_rules[r];
      if (d >= rule->document_start && d < rule->document_start + rule->document_count &&
          (fixed ? fixed_scores[d] >= rule->threshold_fixed
                 : reference_scores[d] >= rule->threshold) &&
          (fixed ? fixed_scores[d] > 0 : reference_scores[d] > 0))
        matched_documents |= (uint16_t)(1U << d);
    }
  uint64_t signals = 0;
  for (unsigned r = 0; r < ABL_BM25_RULE_COUNT; r++) {
    const struct abl_bm25_rule *rule = &abl_bm25_rules[r];
    uint16_t matched = matched_documents & rule->document_mask;
    if ((rule->operator == ABL_OR && matched) ||
        (rule->operator == ABL_AND && matched == rule->document_mask) ||
        (rule->operator == ABL_NOR && !matched)) signals |= 1ULL << rule->route;
  }
  return signals;
}

static uint64_t reference_policy(uint64_t signals) {
  /* Conventional userspace representation: named outputs and ordered
   * high-level conditions matching the paper policy priorities. */
  const uint8_t routes[] = {ROUTE_CODING, ROUTE_MATH, ROUTE_QA, ROUTE_WRITING, ROUTE_OTHERS};
  for (size_t rule = 0; rule < sizeof(routes); rule++)
    if (signals & (1ULL << routes[rule])) return routes[rule];
  return ROUTE_OTHERS;
}

struct mask_rule { uint64_t require_any, require_all, reject_any; uint32_t route, enabled; };
static const struct mask_rule mask_rules[16] = {
  {.require_any = 1ULL << ROUTE_CODING, .route = ROUTE_CODING, .enabled = 1},
  {.require_any = 1ULL << ROUTE_MATH, .route = ROUTE_MATH, .enabled = 1},
  {.require_any = 1ULL << ROUTE_QA, .route = ROUTE_QA, .enabled = 1},
  {.require_any = 1ULL << ROUTE_WRITING, .route = ROUTE_WRITING, .enabled = 1},
  {.require_any = 1ULL << ROUTE_OTHERS, .route = ROUTE_OTHERS, .enabled = 1},
};
static uint64_t xsr_policy(uint64_t signals) {
  for (size_t i = 0; i < 16; i++) {
    const struct mask_rule *rule = &mask_rules[i];
    if (!rule->enabled || (rule->require_any && !(signals & rule->require_any)) ||
        ((signals & rule->require_all) != rule->require_all) ||
        (signals & rule->reject_any)) continue;
    return rule->route;
  }
  return ROUTE_OTHERS;
}

typedef uint64_t (*operation_fn)(const unsigned char *, size_t);
static uint64_t reference_ngram(const unsigned char *data, size_t length) { return ngram_signal(data, length, reference_ngram_word); }
static uint64_t xsr_ngram(const unsigned char *data, size_t length) { return ngram_signal(data, length, xsr_ngram_word); }
static uint64_t reference_bm25(const unsigned char *data, size_t length) { return bm25_signal(data, length, reference_lookup, 0); }
static uint64_t xsr_bm25(const unsigned char *data, size_t length) { return bm25_signal(data, length, xsr_lookup, 1); }

static void verify_routing(const struct workload *workload, const char *signal) {
  operation_fn reference = !strcmp(signal, "ngram") ? reference_ngram : reference_bm25;
  operation_fn xsr = !strcmp(signal, "ngram") ? xsr_ngram : xsr_bm25;
  for (size_t i = 0; i < workload->count; i++) {
    uint64_t expected = reference(workload->prompts[i].data, workload->prompts[i].length);
    uint64_t actual = xsr(workload->prompts[i].data, workload->prompts[i].length);
    if (expected != actual) {
      fprintf(stderr, "%s mismatch at prompt %zu: reference=%" PRIu64 " xsr=%" PRIu64 "\n",
              signal, i, expected, actual);
      exit(1);
    }
  }
  printf("{\"check\":\"routing-equivalence\",\"signal\":\"%s\",\"inputs\":%zu,\"mismatches\":0}\n",
         signal, workload->count);
}

static void verify_policy(void) {
  for (uint64_t signals = 0; signals < 32; signals++) {
    uint64_t expected = reference_policy(signals), actual = xsr_policy(signals);
    if (expected != actual) {
      fprintf(stderr, "policy mismatch for signals=%" PRIu64 "\n", signals); exit(1);
    }
  }
  printf("{\"check\":\"policy-equivalence\",\"signal_states\":32,\"mismatches\":0}\n");
}

static void dump_routing(const struct workload *workload, const char *signal,
                         const char *implementation) {
  operation_fn operation = NULL;
  if (!strcmp(signal, "ngram") && !strcmp(implementation, "reference")) operation = reference_ngram;
  if (!strcmp(signal, "ngram") && !strcmp(implementation, "xsr")) operation = xsr_ngram;
  if (!strcmp(signal, "bm25") && !strcmp(implementation, "reference")) operation = reference_bm25;
  if (!strcmp(signal, "bm25") && !strcmp(implementation, "xsr")) operation = xsr_bm25;
  if (!operation) { fprintf(stderr, "invalid dump implementation\n"); exit(2); }
  printf("{\"signal\":\"%s\",\"implementation\":\"%s\",\"signal_masks\":[",
         signal, implementation);
  for (size_t i = 0; i < workload->count; i++) {
    if (i) putchar(',');
    printf("%" PRIu64, operation(workload->prompts[i].data, workload->prompts[i].length));
  }
  printf("]}\n");
}

static void benchmark(operation_fn operation, const struct workload *workload,
                      double warmup_seconds, double duration_seconds,
                      const char *component, const char *implementation) {
  uint64_t warmup_end = now_ns() + (uint64_t)(warmup_seconds * 1e9);
  uint64_t checksum = 0, index = 0;
  while (now_ns() < warmup_end) {
    const struct prompt *prompt = &workload->prompts[index++ % workload->count];
    checksum += operation(prompt->data, prompt->length);
  }
  uint64_t start = now_ns(), end_at = start + (uint64_t)(duration_seconds * 1e9), operations = 0;
  do {
    for (unsigned batch = 0; batch < 64; batch++) {
      const struct prompt *prompt = &workload->prompts[index++ % workload->count];
      checksum += operation(prompt->data, prompt->length); operations++;
    }
  } while (now_ns() < end_at);
  uint64_t elapsed = now_ns() - start;
  benchmark_sink = checksum;
  printf("{\"component\":\"%s\",\"implementation\":\"%s\","
         "\"operations\":%" PRIu64 ",\"elapsed_ns\":%" PRIu64 ","
         "\"latency_ns_per_operation\":%.6f,\"operations_per_second\":%.6f,"
         "\"checksum\":%" PRIu64 "}\n", component, implementation,
         operations, elapsed, (double)elapsed / operations,
         (double)operations * 1e9 / elapsed, checksum);
}

static uint64_t policy_reference_op(const unsigned char *data, size_t length) { (void)length; return reference_policy(*data & 31); }
static uint64_t policy_xsr_op(const unsigned char *data, size_t length) { (void)length; return xsr_policy(*data & 31); }

static void usage(const char *program) {
  fprintf(stderr, "usage: %s verify-routing <ngram|bm25> INPUT | verify-policy | "
                  "dump-routing <ngram|bm25> <reference|xsr> INPUT | "
                  "routing <ngram|bm25> <reference|xsr> INPUT WARMUP_S DURATION_S | "
                  "policy <reference|xsr> WARMUP_S DURATION_S\n", program);
  exit(2);
}

int main(int argc, char **argv) {
  initialize_ngram_tables();
  if (argc == 2 && !strcmp(argv[1], "verify-policy")) { verify_policy(); return 0; }
  if (argc == 4 && !strcmp(argv[1], "verify-routing")) {
    struct workload workload = load_workload(argv[3]);
    if (strcmp(argv[2], "ngram") && strcmp(argv[2], "bm25")) usage(argv[0]);
    verify_routing(&workload, argv[2]); return 0;
  }
  if (argc == 5 && !strcmp(argv[1], "dump-routing")) {
    struct workload workload = load_workload(argv[4]);
    dump_routing(&workload, argv[2], argv[3]); return 0;
  }
  if (argc == 7 && !strcmp(argv[1], "routing")) {
    struct workload workload = load_workload(argv[4]);
    operation_fn operation = NULL;
    if (!strcmp(argv[2], "ngram") && !strcmp(argv[3], "reference")) operation = reference_ngram;
    if (!strcmp(argv[2], "ngram") && !strcmp(argv[3], "xsr")) operation = xsr_ngram;
    if (!strcmp(argv[2], "bm25") && !strcmp(argv[3], "reference")) operation = reference_bm25;
    if (!strcmp(argv[2], "bm25") && !strcmp(argv[3], "xsr")) operation = xsr_bm25;
    if (!operation) usage(argv[0]);
    benchmark(operation, &workload, atof(argv[5]), atof(argv[6]), argv[2], argv[3]); return 0;
  }
  if (argc == 5 && !strcmp(argv[1], "policy")) {
    unsigned char states[32]; struct prompt prompts[32]; struct workload workload = {prompts, 32};
    for (unsigned i = 0; i < 32; i++) { states[i] = (unsigned char)i; prompts[i] = (struct prompt){&states[i], 1}; }
    operation_fn operation = !strcmp(argv[2], "reference") ? policy_reference_op :
                             !strcmp(argv[2], "xsr") ? policy_xsr_op : NULL;
    if (!operation) usage(argv[0]);
    benchmark(operation, &workload, atof(argv[3]), atof(argv[4]), "decision-policy", argv[2]); return 0;
  }
  usage(argv[0]);
}
