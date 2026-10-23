"""Change only Netavark's lease range under its backend lock; never touch IPAM.

A hash-checked receipt allows rollback without overwriting later changes. All
paths and expected network identity come from the root-owned Nix-generated spec.
"""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import stat
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def trusted_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if info.st_uid != 0 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise ValueError("network policy requires a root-owned, protected regular file")
    return fd


def changed_network(network, spec):
    if (network.get("name") != spec["name"] or network.get("driver") != "bridge"
            or network.get("ipv6_enabled") is not False
            or network.get("ipam_options", {}).get("driver") != "host-local"
            or len(network.get("subnets", [])) != 1):
        raise ValueError("unexpected shared network identity or backend")
    subnet = network["subnets"][0]
    if subnet.get("subnet") != spec["subnet"] or subnet.get("gateway") != spec["gateway"]:
        raise ValueError("unexpected shared subnet or gateway")
    pool = ipaddress.ip_network(spec["subnet"])
    start, end = map(ipaddress.ip_address, (spec["start"], spec["end"]))
    if not pool.network_address < start <= end < pool.broadcast_address:
        raise ValueError("lease range must be usable addresses within the subnet")
    if start <= ipaddress.ip_address(spec["gateway"]) <= end:
        raise ValueError("gateway overlaps lease range")
    updated = json.loads(json.dumps(network))
    updated["subnets"][0]["lease_range"] = {"start_ip": str(start), "end_ip": str(end)}
    return updated


def atomic_write(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix=".network-range-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as host root")
    spec = json.loads(args.spec.read_text())
    path = Path("/etc/containers/networks") / (spec["name"] + ".json")
    if spec["name"] != "ghostship_net":
        parser.error("only the shared network may be changed")
    # Refuse redirected parent directories as well as the leaf. Keep the same
    # lock inode Netavark uses; flock would not synchronize with its lockf.
    for directory in (path.parent, Path("/run/lock")):
        info = directory.stat()
        if directory.resolve() != directory or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("untrusted network or lock directory")
    lock = trusted_open("/run/lock/netavark.lock", os.O_CREAT | os.O_RDWR)
    with os.fdopen(lock, "r+b") as handle:
        fcntl.lockf(handle, fcntl.LOCK_EX)
        fd = trusted_open(path, os.O_RDONLY)
        with os.fdopen(fd, "rb") as current:
            info = os.fstat(current.fileno())
            before = current.read()
        network = json.loads(before)
        updated = changed_network(network, spec)
        if args.rollback:
            receipt_fd = trusted_open(args.rollback, os.O_RDONLY)
            with os.fdopen(receipt_fd) as receipt_file:
                receipt = json.load(receipt_file)
            if digest(before) != receipt["after_sha256"]:
                raise ValueError("network changed since migration; refusing rollback")
            original = receipt["before"].encode()
            # Validate the identity and scope even for an administrator's receipt.
            if changed_network(json.loads(original), spec) != updated:
                raise ValueError("rollback changes more than the lease range")
            atomic_write(path, original, stat.S_IMODE(info.st_mode))
        elif updated != network:
            after = (json.dumps(updated, indent=2) + "\n").encode()
            receipts = Path("/var/lib/ghostship/network-policy")
            receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
            if receipts.is_symlink() or receipts.stat().st_uid != 0 or receipts.stat().st_mode & 0o077:
                raise ValueError("untrusted receipt directory")
            receipt = {"before": before.decode(), "after_sha256": digest(after)}
            atomic_write(receipts / (digest(before) + ".json"), json.dumps(receipt).encode(), 0o600)
            atomic_write(path, after, stat.S_IMODE(info.st_mode))
        print("Shared network lease range verified; bridge and existing endpoints preserved")


if __name__ == "__main__":
    main()
