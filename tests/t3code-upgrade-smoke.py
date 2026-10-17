"""Exercise real T3/OpenCode releases with disposable state and no credentials.

Run inside the disposable T3 image, passing absolute candidate executable paths.
An optional SQLite backup tests OpenCode's migration without opening live state.
"""

import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, password=None, body=None):
    headers = {}
    if password:
        token = base64.b64encode(f"opencode:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, headers=headers, data=json.dumps(body).encode() if body else None
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        assert "application/json" in response.headers.get("Content-Type", "")
        return json.load(response)


def wait_for(proc, url, password=None):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"candidate exited with status {proc.returncode}")
        try:
            return request(url, password)
        except (OSError, ValueError):
            time.sleep(0.25)
    raise TimeoutError("candidate did not become ready within 90 seconds")


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--t3", required=True)
    parser.add_argument("--opencode", required=True)
    parser.add_argument("--t3-version", required=True)
    parser.add_argument("--opencode-version", required=True)
    parser.add_argument("--opencode-db", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="t3-upgrade-smoke-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        env = {
            key: os.environ[key]
            for key in ("PATH", "LD_LIBRARY_PATH", "SSL_CERT_FILE")
            if key in os.environ
        }
        env.update(
            HOME=directory,
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_CACHE_HOME=str(root / "cache"),
            OPENCODE_DISABLE_AUTOUPDATE="1",
            OPENCODE_SERVER_PASSWORD=secrets.token_hex(32),
        )
        legacy_id = None
        if args.opencode_db:
            with sqlite3.connect(
                args.opencode_db.as_uri() + "?mode=ro", uri=True
            ) as db:
                row = db.execute(
                    "SELECT id FROM session ORDER BY time_updated DESC LIMIT 1"
                ).fetchone()
                assert row, "migration rehearsal requires an existing V1 session"
                legacy_id = row[0]
            target = root / "data/opencode/opencode.db"
            target.parent.mkdir(parents=True)
            shutil.copyfile(args.opencode_db, target)
        for binary, expected in (
            (args.t3, f"t3 v{args.t3_version}"),
            (args.opencode, f"opencode v{args.opencode_version}"),
        ):
            result = subprocess.check_output(
                [binary, "--version"], env=env, cwd=root, text=True, timeout=30
            ).strip()
            assert result == expected, (result, expected)
            print(f"PASS version: {result}", flush=True)
        t3_port, oc_port = port(), port()
        password = env["OPENCODE_SERVER_PASSWORD"]
        with (root / "t3.log").open("w") as log:
            proc = subprocess.Popen(
                [
                    args.t3,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(t3_port),
                    "--base-dir",
                    str(root / "t3"),
                    "--no-browser",
                ],
                env=env,
                cwd=root,
                stdout=log,
                stderr=log,
            )
            try:
                info = wait_for(
                    proc, f"http://127.0.0.1:{t3_port}/.well-known/t3/environment"
                )
                assert info["serverVersion"] == args.t3_version
                assert info["orchestrationProtocolVersion"] == 2
                print(
                    "PASS T3 HTTP environment: expected version and orchestration V2",
                    flush=True,
                )
            finally:
                stop(proc)
        session_id = None
        for restart in range(2):
            with (root / "opencode.log").open("w") as log:
                proc = subprocess.Popen(
                    [
                        args.opencode,
                        "serve",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(oc_port),
                    ],
                    env=env,
                    cwd=root,
                    stdout=log,
                    stderr=log,
                )
                try:
                    url = f"http://127.0.0.1:{oc_port}/api"
                    info = wait_for(proc, f"{url}/info", password)
                    assert info["version"] == args.opencode_version
                    if legacy_id:
                        deadline = time.monotonic() + 180
                        while True:
                            migration = request(
                                f"{url}/experimental/migration/v1", password
                            )
                            if migration["status"] == "completed":
                                break
                            assert migration["status"] in ("running", "required"), (
                                "V1 migration failed"
                            )
                            if time.monotonic() >= deadline:
                                raise TimeoutError(
                                    "V1 migration did not finish within 180 seconds"
                                )
                            time.sleep(0.5)
                        imported = request(f"{url}/session/{legacy_id}", password)
                        assert imported["data"]["id"] == legacy_id
                        print(
                            "PASS existing V1 session readable through V2 API",
                            flush=True,
                        )
                    try:
                        request(f"{url}/session")
                    except urllib.error.HTTPError as error:
                        assert error.code == 401
                    else:
                        raise AssertionError(
                            "OpenCode accepted unauthenticated session access"
                        )
                    if session_id is None:
                        created = request(
                            f"{url}/session",
                            password,
                            {"directory": directory, "title": "upgrade smoke"},
                        )
                        session_id = created["data"]["id"]
                    saved = request(f"{url}/session/{session_id}", password)
                    assert saved["data"]["id"] == session_id
                    print(
                        f"PASS OpenCode authenticated session {'survives restart' if restart else 'create/read'}",
                        flush=True,
                    )
                finally:
                    stop(proc)
        print(
            "PASS isolated release smoke; temporary state removed on exit", flush=True
        )


if __name__ == "__main__":
    main()
