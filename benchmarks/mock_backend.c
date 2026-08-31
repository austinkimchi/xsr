/*
 * High-performance multi-threaded C mock HTTP backend server.
 * Stream-buffer enabled to support pipelined HTTP keep-alive requests cleanly.
 */

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#define DEFAULT_PORT 18081
#define DEFAULT_BACKEND "others"
#define NUM_WORKERS 512

static int server_fd = -1;
static volatile int running = 1;
static const char *backend_name = DEFAULT_BACKEND;

static int contains_close_token(const char *value, size_t len) {
  const char needle[] = "close";
  size_t pos = 0;

  for (size_t i = 0; i < len; i++) {
    char c = value[i];
    if (c >= 'A' && c <= 'Z')
      c = (char)(c + ('a' - 'A'));

    if (c == needle[pos]) {
      pos++;
      if (pos == sizeof(needle) - 1)
        return 1;
    } else {
      pos = (c == needle[0]) ? 1 : 0;
    }
  }
  return 0;
}

static void handle_sigint(int sig) {
  (void)sig;
  running = 0;
  if (server_fd >= 0)
    close(server_fd);
}

static void extract_route_seq(const char *body, size_t body_len, char *out,
                              size_t out_len) {
  const char key[] = "\"x_route_seq\"";
  const char *body_end = body + body_len;
  const char *p = body;

  if (out_len == 0)
    return;
  out[0] = '\0';

  while (p + sizeof(key) - 1 <= body_end) {
    if (strncmp(p, key, sizeof(key) - 1) == 0)
      break;
    p++;
  }
  if (p + sizeof(key) - 1 > body_end)
    return;

  p += sizeof(key) - 1;
  while (p < body_end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
    p++;
  if (p >= body_end || *p != ':')
    return;
  p++;
  while (p < body_end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'))
    p++;
  if (p >= body_end || *p != '"')
    return;
  p++;

  size_t used = 0;
  while (p < body_end && *p != '"' && used + 1 < out_len) {
    out[used++] = *p++;
  }
  out[used] = '\0';
}

static void extract_header_value(const char *headers, size_t header_len,
                                 const char *name, char *out, size_t out_len) {
  const char *line = headers;
  const char *end = headers + header_len;
  size_t name_len = strlen(name);

  if (out_len == 0)
    return;
  out[0] = '\0';

  while (line < end) {
    const char *next = strstr(line, "\r\n");
    const char *line_end = next && next < end ? next : end;
    size_t line_len = line_end - line;

    if (line_len > name_len && strncasecmp(line, name, name_len) == 0) {
      const char *p = line + name_len;
      while (p < line_end && (*p == ' ' || *p == '\t'))
        p++;

      size_t used = 0;
      while (p < line_end && used + 1 < out_len)
        out[used++] = *p++;
      out[used] = '\0';
      return;
    }

    if (!next || next >= end)
      break;
    line = next + 2;
  }
}

static void *worker_thread(void *arg) {
  int sfd = *(int *)arg;
  char buf[65536];

  while (running) {
    struct sockaddr_in client_addr;
    socklen_t addr_len = sizeof(client_addr);
    int client_fd = accept(sfd, (struct sockaddr *)&client_addr, &addr_len);
    if (client_fd < 0) {
      if (!running)
        break;
      continue;
    }

    int flag = 1;
    setsockopt(client_fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

    size_t buf_used = 0;

    while (running) {
      char *headers_end = NULL;

      while (running) {
        buf[buf_used] = '\0';
        headers_end = strstr(buf, "\r\n\r\n");
        if (headers_end)
          break;

        if (buf_used >= sizeof(buf) - 1)
          break;

        ssize_t n = read(client_fd, buf + buf_used, sizeof(buf) - 1 - buf_used);
        if (n <= 0)
          goto close_client;
        buf_used += (size_t)n;
      }

      if (!headers_end)
        goto close_client;

      size_t header_len = (headers_end - buf) + 4;
      size_t content_length = 0;
      int keep_alive = 1;

      // Parse Content-Length and Connection headers without mutating buf
      const char *line = buf;
      while (line < headers_end) {
        const char *next = strstr(line, "\r\n");
        if (!next || next > headers_end)
          break;
        size_t line_len = next - line;
        if (line_len >= 15 && strncasecmp(line, "Content-Length:", 15) == 0) {
          content_length = (size_t)strtoull(line + 15, NULL, 10);
        } else if (line_len >= 11 &&
                   strncasecmp(line, "Connection:", 11) == 0) {
          if (contains_close_token(line + 11, line_len - 11)) {
            keep_alive = 0;
          }
        }
        line = next + 2;
      }

      size_t total_req_len = header_len + content_length;

      // Read remaining body bytes if payload is larger than what we have read
      // so far
      while (running && buf_used < total_req_len) {
        size_t want = sizeof(buf) - 1 - buf_used;
        if (want == 0)
          break;
        ssize_t n = read(client_fd, buf + buf_used, want);
        if (n <= 0)
          goto close_client;
        buf_used += (size_t)n;
      }

      if (buf_used < total_req_len)
        goto close_client;

      char route_seq[64];
      char body[192];
      char response[512];
      extract_header_value(buf, header_len, "x-route-seq:", route_seq,
                           sizeof(route_seq));
      if (route_seq[0] == '\0')
        extract_route_seq(buf + header_len, content_length, route_seq,
                          sizeof(route_seq));
      int body_len =
          route_seq[0] != '\0'
              ? snprintf(body, sizeof(body),
                         "{\"backend\":\"%s\",\"x_route_seq\":\"%s\"}\n",
                         backend_name, route_seq)
              : snprintf(body, sizeof(body), "{\"backend\":\"%s\"}\n",
                         backend_name);
      int response_len =
          snprintf(response, sizeof(response),
                   "HTTP/1.1 200 OK\r\n"
                   "Content-Type: application/json\r\n"
                   "Content-Length: %d\r\n"
                   "Connection: %s\r\n"
                   "\r\n"
                   "%s",
                   body_len, keep_alive ? "keep-alive" : "close", body);
      ssize_t w = write(client_fd, response, (size_t)response_len);
      if (w <= 0)
        goto close_client;

      // Shift unconsumed bytes (pipelined requests) to the start of buf
      size_t leftover = buf_used - total_req_len;
      if (leftover > 0) {
        memmove(buf, buf + total_req_len, leftover);
      }
      buf_used = leftover;

      if (!keep_alive)
        break;
    }

  close_client:
    close(client_fd);
  }
  return NULL;
}

int main(int argc, char *argv[]) {
  int port = DEFAULT_PORT;
  if (argc > 1) {
    port = atoi(argv[1]);
  }
  if (argc > 2) {
    backend_name = argv[2];
  }

  signal(SIGINT, handle_sigint);
  signal(SIGTERM, handle_sigint);

  server_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) {
    perror("socket");
    return 1;
  }

  int opt = 1;
  setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = INADDR_ANY;
  addr.sin_port = htons(port);

  if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
    perror("bind");
    return 1;
  }

  if (listen(server_fd, 4096) < 0) {
    perror("listen");
    return 1;
  }

  printf("High-performance C Mock HTTP Backend listening on 0.0.0.0:%d as %s\n",
         port, backend_name);
  fflush(stdout);

  pthread_t threads[NUM_WORKERS];
  for (int i = 0; i < NUM_WORKERS; i++) {
    pthread_create(&threads[i], NULL, worker_thread, &server_fd);
  }

  for (int i = 0; i < NUM_WORKERS; i++) {
    pthread_join(threads[i], NULL);
  }

  return 0;
}
