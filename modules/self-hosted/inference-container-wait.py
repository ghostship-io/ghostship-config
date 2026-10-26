"""Wait for an executable to appear in the worker container's published store.

Issue #639: a deploy switch restarted the bridge while the runtime publisher
was still copying the new closure, so `podman exec` reached a container without
the binary and exited 127, failing the switch. Wait for the exact executable
the unit is about to run, so the start proceeds only once the container can run
it; `after=` alone never gated that.
"""

import argparse
import subprocess
import sys
import time

# The container image links every published package binary into /bin, so this
# path exists for both the old and the new closure and never depends on the
# package that is still being published.
TEST = "/bin/test"


def ready(podman, container, path, *, run=subprocess.run):
    try:
        completed = run(
            [podman, "exec", "--user", "0:0", container, TEST, "-x", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        # A container that cannot accept an exec yet is not a reason to fail;
        # the timeout decides when the wait gives up.
        return False
    return completed.returncode == 0


def wait(
    podman,
    container,
    path,
    timeout,
    *,
    interval=2.0,
    run=subprocess.run,
    sleep=time.sleep,
    clock=time.monotonic,
):
    deadline = clock() + timeout
    while True:
        if ready(podman, container, path, run=run):
            return
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(
                f"{path} is not executable in {container} after {timeout:g}s"
            )
        sleep(min(interval, remaining))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("podman")
    parser.add_argument("container")
    parser.add_argument("path")
    # Matches the publish wait on the same unit, inside TimeoutStartSec.
    parser.add_argument("--timeout", type=float, default=1200)
    args = parser.parse_args(argv)
    try:
        wait(args.podman, args.container, args.path, args.timeout)
    except TimeoutError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
