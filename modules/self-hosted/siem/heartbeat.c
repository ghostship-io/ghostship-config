/* AppArmor collector heartbeat for images with no cat or safe self-read
 * (Grafana's binary starts a server on any config). Reads the one file it
 * is given, discards it and exits; mounted read-only, it executes nothing. */
#include <fcntl.h>
#include <unistd.h>

int main(int argc, char **argv) {
  char buffer[256];
  if (argc != 2) return 2;
  int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
  if (fd < 0) return 1;
  while (read(fd, buffer, sizeof buffer) > 0) {}
  close(fd);
  return 0;
}
