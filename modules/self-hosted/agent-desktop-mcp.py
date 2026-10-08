#!/usr/bin/env python3
"""Provision Bladebro MCP access from t3code to the agent desktop.

Writes SSH transport wrappers into the t3code home, pins the desktop host
key, and merges the Bladebro MCP server entries into every installed coding
agent's configuration (OpenCode, Codex, Claude Code, Cursor, Antigravity /
Gemini and Grok) without touching unrelated settings.
"""

import argparse
import json
import os
import pathlib
import shutil
import stat
import sys
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
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(data)
    os.chown(tmp, uid, gid)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def backup(path):
    if path.exists() and not path.with_name(path.name + ".pre-bladebro").exists():
        shutil.copy2(path, path.with_name(path.name + ".pre-bladebro"))


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


def merge_opencode(home, args):
    config_dir = home / ".config" / "opencode"
    path = config_dir / "opencode.json"
    if not path.exists():
        path = config_dir / "opencode.jsonc"
    if not path.exists():
        return
    raw, data = load_json(path, json5.loads)
    servers = data.setdefault("mcp", {})
    changed = False
    for identity, name in IDENTITIES.items():
        entry = {
            "type": "local",
            "command": [wrapper_path(home, identity)],
            "enabled": True,
        }
        if servers.get(name) != entry:
            servers[name] = entry
            changed = True
    if changed:
        backup(path)
        write_file(path, json.dumps(data, indent=2) + "\n", args.uid, args.gid)
        log(f"updated {path}")


def merge_codex(home, args):
    path = home / ".codex" / "config.toml"
    if not path.exists():
        return
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    servers = data.setdefault("mcp_servers", {})
    changed = False
    for identity, name in IDENTITIES.items():
        entry = {"command": wrapper_path(home, identity)}
        if servers.get(name) != entry:
            servers[name] = entry
            changed = True
    if changed:
        backup(path)
        write_file(path, tomli_w.dumps(data), args.uid, args.gid)
        log(f"updated {path}")


def merge_claude(home, args):
    path = home / ".claude.json"
    if not path.exists():
        return
    raw, data = load_json(path)
    servers = data.setdefault("mcpServers", {})
    changed = False
    for identity, name in IDENTITIES.items():
        entry = {
            "type": "stdio",
            "command": wrapper_path(home, identity),
            "args": [],
            "env": {},
        }
        if servers.get(name) != entry:
            servers[name] = entry
            changed = True
    if changed:
        backup(path)
        write_file(path, json.dumps(data, indent=2) + "\n", args.uid, args.gid)
        log(f"updated {path}")


def merge_grok(home, args):
    path = home / ".grok" / "config.toml"
    if not path.exists():
        return
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    servers = data.setdefault("mcp_servers", {})
    changed = False
    for identity, name in IDENTITIES.items():
        entry = {"command": wrapper_path(home, identity), "enabled": True}
        if servers.get(name) != entry:
            servers[name] = entry
            changed = True
    if changed:
        backup(path)
        write_file(path, tomli_w.dumps(data), args.uid, args.gid)
        log(f"updated {path}")


def merge_gemini(home, args):
    path = home / ".gemini" / "config" / "mcp_config.json"
    if not path.parent.exists():
        return
    raw, data = load_json(path)
    servers = data.setdefault("mcpServers", {})
    changed = False
    for identity, name in IDENTITIES.items():
        entry = {"command": wrapper_path(home, identity), "args": []}
        if servers.get(name) != entry:
            servers[name] = entry
            changed = True
    if changed:
        backup(path)
        write_file(path, json.dumps(data, indent=2) + "\n", args.uid, args.gid, mode=file_mode(path, 0o644))
        log(f"updated {path}")


def merge_cursor(home, args):
    path = home / ".cursor" / "mcp.json"
    if not path.parent.exists():
        return
    raw, data = load_json(path) if path.exists() else ("", {})
    servers = data.setdefault("mcpServers", {})
    changed = False
    for identity, name in IDENTITIES.items():
        entry = {"command": wrapper_path(home, identity), "args": []}
        if servers.get(name) != entry:
            servers[name] = entry
            changed = True
    if changed:
        backup(path)
        write_file(path, json.dumps(data, indent=2) + "\n", args.uid, args.gid, mode=file_mode(path, 0o644))
        log(f"updated {path}")


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
    merge_opencode(home, args)
    merge_codex(home, args)
    merge_claude(home, args)
    merge_grok(home, args)
    merge_gemini(home, args)
    merge_cursor(home, args)
    log("Bladebro MCP access provisioned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
