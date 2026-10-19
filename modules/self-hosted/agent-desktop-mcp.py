#!/usr/bin/env python3
"""Provision Bladebro SSH access from t3code to the agent desktop.

Writes SSH transport wrappers into the t3code home and pins the desktop host
key (the Ghostship desktop bridge publishes it to the MCP runtime). Coding
agents use Bladebro through the Ghostship browser tools, so this removes the
direct Bladebro MCP entries earlier versions merged into OpenCode, Codex,
Claude Code, Cursor, Antigravity / Gemini and Grok, without touching
unrelated settings.
"""

import argparse
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import time

import json5
import tomli_w
import tomllib

IDENTITIES = {"agent": "bladebro", "personal": "bladebro-personal"}
WRAPPER_TEMPLATE = """#!/bin/sh
exec ssh -T \\
  -i {home}/.ssh/id_agent_desktop \\
  -p {port} \\
  -o BatchMode=yes \\
  -o IdentitiesOnly=yes \\
  -o StrictHostKeyChecking=yes \\
  -o UserKnownHostsFile={home}/.ssh/known_hosts_agent_desktop \\
  -o LogLevel=ERROR \\
  -o ConnectTimeout=10 \\
  {user}@{host} bladebro-mcp-{identity}
"""


def log(message):
    print(f"[agent-desktop-mcp] {message}", file=sys.stderr, flush=True)


def file_mode(path, default=0o644):
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return default


def write_file(path, data, uid, gid, mode=None):
    if mode is None:
        mode = file_mode(path, 0o600)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchown(handle.fileno(), uid, gid)
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def backup(path):
    if not path.exists():
        return
    destination = path.with_name(path.name + ".pre-bladebro")
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as output, path.open("rb") as source:
        shutil.copyfileobj(source, output)


def wrapper_path(home, identity):
    return str(home / ".local" / "bin" / f"bladebro-mcp-{identity}")


def ensure_wrappers(home, args):
    binary_dir = home / ".local" / "bin"
    binary_dir.mkdir(parents=True, exist_ok=True)
    os.chown(binary_dir, args.uid, args.gid)
    for identity in IDENTITIES:
        path = binary_dir / f"bladebro-mcp-{identity}"
        content = WRAPPER_TEMPLATE.format(
            home=home,
            port=args.desktop_port,
            user=args.desktop_user,
            host=args.desktop_host,
            identity=identity,
        )
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            write_file(path, content, args.uid, args.gid, mode=0o755)


def pin_known_host(host_key, home, args):
    fields = host_key.read_text(encoding="utf-8").split()
    if len(fields) < 2:
        raise SystemExit(f"unexpected host key format: {host_key}")
    line = f"[{args.desktop_host}]:{args.desktop_port} {fields[0]} {fields[1]}\n"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chown(ssh_dir, args.uid, args.gid)
    os.chmod(ssh_dir, 0o700)
    path = ssh_dir / "known_hosts_agent_desktop"
    if not path.exists() or path.read_text(encoding="utf-8") != line:
        write_file(path, line, args.uid, args.gid, mode=0o600)


def load_json(path, parser=json.loads):
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return raw, {}
    return raw, parser(raw)


def save_json(path, raw, data, args):
    new = json.dumps(data, indent=2) + "\n"
    if new != raw:
        backup(path)
        write_file(path, new, args.uid, args.gid)
        log(f"updated {path}")


def is_wrapper(home, entry):
    """Whether an MCP entry is one this helper registered (a Bladebro SSH wrapper)."""
    if not isinstance(entry, dict):
        return False
    command = entry.get("command", "")
    if isinstance(command, list):
        command = command[0] if command else ""
    wrappers = {wrapper_path(home, identity) for identity in IDENTITIES}
    # Older runs wrote host-side paths; the wrapper names identify those too.
    names = {pathlib.Path(path).name for path in wrappers}
    return command in wrappers or pathlib.PurePath(str(command)).name in names


def drop_entries(home, servers):
    removed = False
    for name in IDENTITIES.values():
        if is_wrapper(home, servers.get(name)):
            del servers[name]
            removed = True
    return removed


def unregister_json(home, path, key, args, parser=json.loads):
    if not path.exists():
        return
    raw, data = load_json(path, parser)
    servers = data.get(key)
    if isinstance(servers, dict) and drop_entries(home, servers):
        backup(path)
        write_file(path, json.dumps(data, indent=2) + "\n", args.uid, args.gid, mode=file_mode(path, 0o600))
        log(f"removed Bladebro MCP entries from {path}")


def unregister_toml(home, path, args):
    if not path.exists():
        return
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    servers = data.get("mcp_servers")
    if isinstance(servers, dict) and drop_entries(home, servers):
        backup(path)
        write_file(path, tomli_w.dumps(data), args.uid, args.gid)
        log(f"removed Bladebro MCP entries from {path}")


def unregister_clients(home, args):
    """Agents reach Bladebro through the Ghostship browser tools; direct entries only cost context."""
    opencode = home / ".config" / "opencode" / "opencode.json"
    if not opencode.exists():
        opencode = opencode.with_suffix(".jsonc")
    unregister_json(home, opencode, "mcp", args, json5.loads)
    unregister_json(home, home / ".claude.json", "mcpServers", args)
    unregister_json(home, home / ".gemini" / "config" / "mcp_config.json", "mcpServers", args)
    unregister_json(home, home / ".cursor" / "mcp.json", "mcpServers", args)
    unregister_toml(home, home / ".codex" / "config.toml", args)
    unregister_toml(home, home / ".grok" / "config.toml", args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--host-key", required=True, dest="host_key")
    parser.add_argument("--desktop-host", default="10.89.7.2")
    parser.add_argument("--desktop-port", default="2222")
    parser.add_argument("--desktop-user", default="abc")
    parser.add_argument("--uid", type=int, default=3000)
    parser.add_argument("--gid", type=int, default=3000)
    parser.add_argument("--wait", type=int, default=180)
    args = parser.parse_args()

    # Never traverse a container-writable home with host-root privileges,
    # including when this helper is invoked outside its systemd service.
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(args.gid)
        os.setuid(args.uid)

    home = pathlib.Path(args.home).resolve()
    host_key = pathlib.Path(args.host_key)
    deadline = time.time() + args.wait
    while not host_key.exists() and time.time() < deadline:
        time.sleep(2)
    if not host_key.exists():
        log(f"desktop host key never appeared: {host_key}")
        return 1

    ensure_wrappers(home, args)
    pin_known_host(host_key, home, args)
    unregister_clients(home, args)
    log("Bladebro SSH access provisioned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
