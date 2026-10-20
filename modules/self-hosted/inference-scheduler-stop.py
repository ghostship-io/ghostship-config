"""Stop only the container scheduler, then let its attached Podman client exit."""

import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def stop(podman, main_pid, timeout=890):
    try:
        attachment = os.pidfd_open(main_pid)
    except ProcessLookupError:
        return
    descriptors = [attachment]
    try:
        output = subprocess.check_output(
            [podman, "top", "t3code", "hpid"], text=True, timeout=10
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
                if argv[1:4] == [b"-m", b"ghostship_inference.cli", b"serve"]:
                    targets.append(descriptor)
                    descriptors.append(descriptor)
            finally:
                if descriptor not in targets:
                    os.close(descriptor)
        if len(targets) != 1:
            raise RuntimeError(f"expected one container scheduler, found {len(targets)}")
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
                raise TimeoutError("scheduler or Podman attachment did not finish shutdown")
            for descriptor, _ in poller.poll(max(1, int(remaining * 1000))):
                pending.remove(descriptor)
                poller.unregister(descriptor)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


if __name__ == "__main__":
    # systemd unsets MAINPID if the attachment has already exited. Its recorded
    # exit status still determines the unit result; there is nothing left to stop.
    if len(sys.argv) > 2 and sys.argv[2]:
        stop(sys.argv[1], int(sys.argv[2]))
