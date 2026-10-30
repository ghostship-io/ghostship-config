#!/usr/bin/env python3
"""Reconcile the desired Mesh connection without replacing an existing identity."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import time


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".health-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warp-cli", required=True)
    parser.add_argument("--systemctl", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--warp-state-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (args.state_dir / "health.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return reconcile(args)


def reconcile(args):
    def cli(*command):
        # Never emit CLI output: registration responses and errors may contain
        # credentials. Only bounded, explicitly selected health fields escape.
        try:
            return subprocess.run(
                [args.warp_cli, "--accept-tos", "--json", *command],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return subprocess.CompletedProcess(command, 1, "", "")

    def value(result):
        try:
            parsed = json.loads(result.stdout) if result.returncode == 0 else {}
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}

    state_file = args.state_dir / "health.json"
    try:
        previous = json.loads(state_file.read_text())
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    now = int(time.time())
    failures = previous.get("failures", 0)
    last_restart = previous.get("lastRestart", 0)
    if not isinstance(failures, int) or not isinstance(last_restart, int):
        failures, last_restart = 0, 0
    state = {"checkedAt": now, "failures": failures, "lastRestart": last_restart,
             "transport": "unknown", "peers": "unverified"}

    def refused(message):
        state["reason"] = message
        atomic_json(state_file, state)
        print(message)
        return 1

    registration = value(cli("registration", "show"))
    attempted = args.state_dir / "enrollment-attempted"
    if not registration:
        # A Type=simple daemon can be active before its RPC socket is ready.
        # Defer enrollment until a read-only RPC succeeds, without fencing an
        # attempt that was never sent to Cloudflare.
        fenced = attempted.exists() or (args.warp_state_dir / "reg.json").exists()
        if not fenced and cli("settings").returncode != 0:
            return refused("WARP daemon not ready; enrollment deferred")
        # A failed/unknown enrollment is reconciled, never repeated blindly.
        # Native registration state also fences an interrupted first install.
        if not fenced:
            try:
                info = args.token_file.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077):
                    raise ValueError("Mesh node token must be owner-only and owned by the service user")
                token = args.token_file.read_text().strip()
                if not token:
                    raise ValueError("Mesh node token is empty")
            except (OSError, ValueError):
                return refused("Mesh enrollment requires an owner-only node token; no identity changed")
            # Persist the fence before the external effect, including across
            # an interrupted WSL shutdown or lost CLI acknowledgment.
            atomic_json(attempted, {"attemptedAt": now})
            result = cli("connector", "new", token)
            if result.returncode != 0:
                return refused("Mesh enrollment outcome unknown; reconcile registration before retrying enrollment")
            registration = value(cli("registration", "show"))

    # Account identity, not a generic managed flag, selects the network.
    # Unknown schemas fail closed until the installed client is reconciled.
    account = registration.get("account", {})
    team_account = (isinstance(account, dict) and account.get("type") == "team"
                    and account.get("organization") == "ghostshipio")
    if registration and not team_account:
        return refused("WARP registration is not the ghostshipio team; refusing to replace it")

    status = value(cli("status")).get("status") if registration else None
    if status != "Connected" and registration:
        cli("connect")
        status = value(cli("status")).get("status")
    if status != "Connected":
        state["failures"] += 1
        # A delayed resume, offline uplink or unknown CLI result is not a
        # reason to churn the daemon every minute. Keep the identity intact.
        if state["failures"] >= 3 and now - last_restart >= 600:
            try:
                subprocess.run([args.systemctl, "restart", "cloudflare-warp.service"],
                               capture_output=True, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            state["lastRestart"] = now
        state["transport"] = "disconnected" if status == "Disconnected" else "unknown"
        atomic_json(state_file, state)
        print("Mesh not connected; reconnect requested, registration preserved")
        return 1

    state.update(transport="connected", failures=0)
    peers_file = args.state_dir / "peers.json"
    if peers_file.exists():
        try:
            peers = json.loads(peers_file.read_text())
            if not isinstance(peers, list) or not peers:
                raise ValueError("Peer list must be nonempty")
            for peer in peers:
                address = ipaddress.ip_address(peer["host"])
                if address not in ipaddress.ip_network("100.96.0.0/12"):
                    raise ValueError("Peer address must be a Mesh IP")
                port = peer.get("port", 22)
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError("Invalid peer port")
                with socket.create_connection((str(address), port), timeout=3):
                    pass
            state["peers"] = "reachable"
        except (OSError, ValueError, KeyError, TypeError):
            state["peers"] = "unreachable-or-invalid"
            atomic_json(state_file, state)
            print("Mesh connected; peer probe failed; healthy local daemon left running")
            return 1
    atomic_json(state_file, state)
    print("Mesh connected; peer routing " + state["peers"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
