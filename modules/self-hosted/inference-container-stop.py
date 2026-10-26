"""Stop one process inside the worker container, then let its Podman client exit.

systemd stops a `podman exec` unit by signalling the Podman attachment, which
reports exit 1 even for an orderly stop and leaves conmon behind. Signal the
container process instead and wait for both identities to finish, so a clean
stop keeps the main process's real exit status (0) and a crash still fails.
"""

import argparse
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def stop(podman, main_pid, timeout, *, container, module, arguments=()):
    try:
        attachment = os.pidfd_open(main_pid)
    except ProcessLookupError:
        return
    descriptors = [attachment]
    # The entrypoint execs the interpreter, so argv[0] is python and the
    # module and its fixed arguments follow.
    expected = [b"-m", module.encode(), *(argument.encode() for argument in arguments)]
    try:
        output = subprocess.check_output(
            [podman, "top", container, "hpid"], text=True, timeout=10
        )
        targets = []
        for value in output.splitlines()[1:]:
            if not value.strip().isdigit():
                continue
            pid = int(value.strip())
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                try:
                    argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                except FileNotFoundError:
                    continue
                if argv[1 : 1 + len(expected)] == expected:
                    targets.append(descriptor)
                    descriptors.append(descriptor)
            finally:
                if descriptor not in targets:
                    os.close(descriptor)
        if len(targets) != 1:
            raise RuntimeError(f"expected one {module} process, found {len(targets)}")
        # A pidfd pins process identity even if it exits during inspection.
        try:
            signal.pidfd_send_signal(targets[0], signal.SIGTERM)
        except ProcessLookupError:
            pass
        poller = select.poll()
        pending = {attachment, targets[0]}
        for descriptor in pending:
            poller.register(descriptor, select.POLLIN)
        deadline = time.monotonic() + timeout
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{module} or its Podman attachment did not finish shutdown"
                )
            for descriptor, _ in poller.poll(max(1, int(remaining * 1000))):
                pending.remove(descriptor)
                poller.unregister(descriptor)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("podman")
    parser.add_argument("main_pid")
    parser.add_argument("container")
    parser.add_argument("timeout", type=float)
    parser.add_argument("module")
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args(argv)
    # systemd unsets MAINPID if the attachment has already exited. Its recorded
    # exit status still determines the unit result; there is nothing left to stop.
    if args.main_pid:
        stop(
            args.podman,
            int(args.main_pid),
            args.timeout,
            container=args.container,
            module=args.module,
            arguments=args.arguments,
        )


if __name__ == "__main__":
    main()
