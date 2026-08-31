/* Probe the kernel SOCKMAP lifetime cases relied on by XSR cleanup. */
#define _GNU_SOURCE

#include <arpa/inet.h>
#include <bpf/bpf.h>
#include <errno.h>
#include <linux/bpf.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int connected_tcp_pair(int *peer_fd, int *owned_fd) {
  struct sockaddr_in address = {
      .sin_family = AF_INET,
      .sin_addr.s_addr = htonl(INADDR_LOOPBACK),
  };
  socklen_t address_len = sizeof(address);
  int listener = -1;

  listener = socket(AF_INET, SOCK_STREAM, 0);
  *peer_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (listener < 0 || *peer_fd < 0 ||
      bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 ||
      listen(listener, 1) != 0 ||
      getsockname(listener, (struct sockaddr *)&address, &address_len) != 0 ||
      connect(*peer_fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
    if (listener >= 0)
      close(listener);
    if (*peer_fd >= 0)
      close(*peer_fd);
    return -1;
  }
  *owned_fd = accept(listener, NULL, NULL);
  close(listener);
  return *owned_fd < 0 ? -1 : 0;
}

static int lookup_present(int map_fd, uint32_t slot) {
  uint64_t cookie = 0;

  return bpf_map_lookup_elem(map_fd, &slot, &cookie) == 0 && cookie != 0;
}

int main(void) {
  LIBBPF_OPTS(bpf_map_create_opts, options);
  uint32_t slot = 0;
  uint64_t socket_value;
  int map_fd;
  int peer_fd = -1;
  int owned_fd = -1;
  struct pollfd hangup = {.events = POLLRDHUP};
  struct sockaddr_storage address;
  socklen_t address_len = sizeof(address);

  map_fd = bpf_map_create(BPF_MAP_TYPE_SOCKMAP, "xsr_lifetime_probe",
                          sizeof(slot), sizeof(uint64_t), 1, &options);
  if (map_fd < 0) {
    perror("create SOCKMAP");
    return 1;
  }

  if (connected_tcp_pair(&peer_fd, &owned_fd) != 0) {
    perror("create connected sockets");
    return 1;
  }
  socket_value = (uint32_t)owned_fd;
  if (bpf_map_update_elem(map_fd, &slot, &socket_value, BPF_ANY) != 0) {
    perror("insert peer-close socket");
    return 1;
  }
  close(peer_fd);
  hangup.fd = owned_fd;
  if (poll(&hangup, 1, 1000) <= 0 || !(hangup.revents & POLLRDHUP)) {
    fprintf(stderr, "peer FIN was not observable as POLLRDHUP\n");
    return 1;
  }
  if (!lookup_present(map_fd, slot)) {
    fprintf(stderr, "SOCKMAP entry disappeared while userspace FD remained open\n");
    return 1;
  }
  puts("peer_close_userspace_fd_open=sockmap_entry_present");

  close(owned_fd);
  usleep(1000);
  if (lookup_present(map_fd, slot) || errno != ENOENT) {
    fprintf(stderr, "closing userspace FD did not unlink SOCKMAP entry: %s\n",
            strerror(errno));
    return 1;
  }
  puts("userspace_close=sockmap_entry_removed");

  if (connected_tcp_pair(&peer_fd, &owned_fd) != 0) {
    perror("create explicit-delete sockets");
    return 1;
  }
  socket_value = (uint32_t)owned_fd;
  if (bpf_map_update_elem(map_fd, &slot, &socket_value, BPF_ANY) != 0 ||
      bpf_map_delete_elem(map_fd, &slot) != 0) {
    perror("explicit SOCKMAP delete");
    return 1;
  }
  if (lookup_present(map_fd, slot) || errno != ENOENT) {
    fprintf(stderr, "explicit delete left a SOCKMAP entry\n");
    return 1;
  }
  if (getsockname(owned_fd, (struct sockaddr *)&address, &address_len) != 0) {
    fprintf(stderr, "explicit map delete unexpectedly closed userspace FD\n");
    return 1;
  }
  puts("explicit_delete=sockmap_entry_removed_userspace_fd_open");

  errno = 0;
  if (bpf_map_delete_elem(map_fd, &slot) == 0 || errno != EINVAL) {
    fprintf(stderr, "empty SOCKMAP slot did not report EINVAL\n");
    return 1;
  }
  puts("delete_empty_sockmap_slot=EINVAL");

  close(peer_fd);
  close(owned_fd);
  close(map_fd);
  return 0;
}
