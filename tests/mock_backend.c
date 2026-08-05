/*
 * High-performance multi-threaded C mock HTTP backend server.
 * Capable of 100,000+ RPS without Python GIL bottlenecks.
 */

#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#define DEFAULT_PORT 18081
#define NUM_WORKERS 16

static const char HTTP_RESPONSE[] =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "Content-Length: 68\r\n"
    "Connection: keep-alive\r\n"
    "\r\n"
    "{\"id\":\"keyword-benchmark\",\"choices\":[{\"message\":{\"content\":\"ok\"}}]}\n";

static const char HTTP_RESPONSE_CLOSE[] =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "Content-Length: 68\r\n"
    "Connection: close\r\n"
    "\r\n"
    "{\"id\":\"keyword-benchmark\",\"choices\":[{\"message\":{\"content\":\"ok\"}}]}\n";

static int server_fd = -1;
static volatile int running = 1;

static int contains_close_token(const char *value) {
  const char needle[] = "close";
  size_t pos = 0;

  for (; *value; value++) {
    char c = *value;
    if (c >= 'A' && c <= 'Z')
      c = (char)(c + ('a' - 'A'));

    if (c == needle[pos]) {
      pos++;
      if (pos == sizeof(needle) - 1)
        return 1;
    } else {
      pos = c == needle[0] ? 1 : 0;
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
    struct timeval read_timeout = {
        .tv_sec = 0,
        .tv_usec = 100000,
    };
    setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO, &read_timeout,
               sizeof(read_timeout));

    while (running) {
      size_t used = 0;
      char *headers_end = NULL;

      while (running && used < sizeof(buf) - 1) {
        ssize_t n = read(client_fd, buf + used, sizeof(buf) - 1 - used);
        if (n <= 0)
          goto close_client;
        used += (size_t)n;
        buf[used] = '\0';
        headers_end = strstr(buf, "\r\n\r\n");
        if (headers_end)
          break;
      }

      if (!headers_end)
        goto close_client;

      size_t header_len = (headers_end - buf) + 4;
      size_t content_length = 0;
      int keep_alive = 1;

      char *line = buf;
      while (line < headers_end) {
        char *next = strstr(line, "\r\n");
        if (!next || next > headers_end)
          break;
        *next = '\0';
        if (strncasecmp(line, "Content-Length:", 15) == 0) {
          content_length = (size_t)strtoull(line + 15, NULL, 10);
        } else if (strncasecmp(line, "Connection:", 11) == 0 &&
                   contains_close_token(line + 11)) {
          keep_alive = 0;
        }
        line = next + 2;
      }

      while (running && used < header_len + content_length) {
        char drain[8192];
        size_t remaining = header_len + content_length - used;
        size_t want = remaining < sizeof(drain) ? remaining : sizeof(drain);
        ssize_t n = read(client_fd, drain, want);
        if (n <= 0)
          break;
        used += (size_t)n;
      }

      const char *response = keep_alive ? HTTP_RESPONSE : HTTP_RESPONSE_CLOSE;
      size_t response_len =
          keep_alive ? sizeof(HTTP_RESPONSE) - 1 : sizeof(HTTP_RESPONSE_CLOSE) - 1;
      ssize_t w = write(client_fd, response, response_len);
      (void)w;
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

  printf("High-performance C Mock HTTP Backend listening on 0.0.0.0:%d\n", port);
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
