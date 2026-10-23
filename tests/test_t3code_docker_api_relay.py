"""Exercise the API relay's peer-credential authorization on real sockets.

The relay is the only path from the apps group to the rootless engine API.
The engine's socket path is writable by the untrusted container, so the relay
must authorize the peer of every upstream connection instead of trusting the
path. These tests use real Unix sockets in a temporary directory; no host
Podman, Nix or Docker socket is ever contacted.
"""

import asyncio
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = (
    Path(__file__).resolve().parents[1] / "packages/t3code/docker-sandbox/api-relay.py"
)
SPEC = importlib.util.spec_from_file_location("docker_api_relay", SOURCE)
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)

# Hand the listener to the relay the way systemd does: on fd 3, with the
# listening PID and descriptor count in the environment.
BOOTSTRAP = (
    "import os,sys;"
    "os.dup2(int(sys.argv[1]),3);"
    "os.environ['LISTEN_PID']=str(os.getpid());"
    "os.environ['LISTEN_FDS']='1';"
    "os.execv(sys.argv[2],sys.argv[2:])"
)


class Upstream:
    """A real Unix stream socket that records every byte it receives."""

    def __init__(self, path):
        self.path = str(path)
        self.received = bytearray()
        self.connections = 0
        self.closed = 0
        self._stop = threading.Event()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(self.path)
        self._socket.listen(8)
        self._socket.settimeout(0.1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.connections += 1
            with connection:
                connection.settimeout(0.1)
                while not self._stop.is_set():
                    try:
                        data = connection.recv(4096)
                    except TimeoutError:
                        continue
                    except OSError:
                        break
                    if not data:
                        # The peer closed its side.
                        self.closed += 1
                        break
                    self.received += data
                    try:
                        connection.sendall(b"pong:" + data)
                    except OSError:
                        break

    def close(self):
        self._stop.set()
        self._thread.join(timeout=5)
        self._socket.close()


def listening(path):
    """Create the listening socket systemd would hand to the relay."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen(8)
    return sock


def start_relay(listener, upstream, uid):
    """Start the relay with a systemd style listener on fd 3."""
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            BOOTSTRAP,
            str(listener.fileno()),
            sys.executable,
            str(SOURCE),
            "--upstream",
            str(upstream),
            "--engine-uid",
            str(uid),
        ],
        pass_fds=(listener.fileno(),),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_relay(process):
    """Stop the relay and return what it reported."""
    process.terminate()
    try:
        _, errors = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        _, errors = process.communicate(timeout=10)
    return errors


def read_exactly(client, size):
    """Read a fixed number of bytes from a connected client."""
    data = b""
    while len(data) < size:
        chunk = client.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


class RelayAuthorization(unittest.TestCase):
    """The relay must trust the peer credentials, never the socket path."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        self.upstream = Upstream(self.root / "engine.sock")
        self.addCleanup(self.upstream.close)
        self.listener = listening(self.root / "relay.sock")
        self.addCleanup(self.listener.close)

    def connect(self, path=None):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(10)
        client.connect(str(path or self.root / "relay.sock"))
        self.addCleanup(client.close)
        return client

    @unittest.skipIf(os.getuid() == 0, "the engine peer must be an unprivileged UID")
    def test_dedicated_peer_forwards_bytes(self):
        # The engine peer is the configured UID, so the relay forwards both
        # directions over real Unix sockets.
        process = start_relay(self.listener, self.upstream.path, os.getuid())
        try:
            client = self.connect()
            client.sendall(b"ping")
            self.assertEqual(read_exactly(client, len(b"pong:ping")), b"pong:ping")
            self.assertEqual(bytes(self.upstream.received), b"ping")
        finally:
            errors = stop_relay(process)
        self.assertEqual(process.returncode, 0, errors)

    def test_rejected_peer_never_reaches_upstream(self):
        # The configured engine UID is a different unprivileged account, so the
        # upstream peer is not the engine and must be refused.
        process = start_relay(self.listener, self.upstream.path, os.getuid() + 1)
        try:
            client = self.connect()
            client.sendall(b"ping")
            try:
                answer = client.recv(64)
            except ConnectionResetError:
                answer = b""
            self.assertEqual(answer, b"")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not self.upstream.received:
                time.sleep(0.05)
            self.assertEqual(bytes(self.upstream.received), b"")
        finally:
            errors = stop_relay(process)
        self.assertEqual(process.returncode, 0, errors)

    def test_symlinked_upstream_is_refused_by_peer_credentials(self):
        # The container owns the engine path and may replace it with a symlink
        # to another socket. Following the link is allowed; the peer check is
        # what refuses the connection.
        attacker = self.root / "attacker"
        attacker.mkdir()
        link = attacker / "docker.sock"
        link.symlink_to(self.upstream.path)
        process = start_relay(self.listener, link, os.getuid() + 1)
        try:
            client = self.connect()
            client.sendall(b"ping")
            try:
                answer = client.recv(64)
            except ConnectionResetError:
                answer = b""
            self.assertEqual(answer, b"")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not self.upstream.received:
                time.sleep(0.05)
            self.assertEqual(bytes(self.upstream.received), b"")
        finally:
            errors = stop_relay(process)
        self.assertEqual(process.returncode, 0, errors)

    def test_relay_never_removes_the_systemd_listener(self):
        # systemd owns the listener socket and its path. A relay that stops
        # while a client is connected must leave the path alone: asyncio's
        # default socket cleanup unlinks the socket it never created.
        process = start_relay(self.listener, self.upstream.path, os.getuid())
        path = self.root / "relay.sock"
        inode = path.stat().st_ino
        try:
            client = self.connect()
            client.sendall(b"ping")
            self.assertEqual(read_exactly(client, len(b"pong:ping")), b"pong:ping")
        finally:
            errors = stop_relay(process)
        self.assertTrue(path.exists(), errors)
        self.assertEqual(path.stat().st_ino, inode, errors)
        self.assertEqual(process.returncode, 0, errors)

    def test_relay_starts_when_the_listener_path_cannot_be_stat_ed(self):
        # systemd may hand over a listener whose path the relay cannot stat.
        # asyncio's default socket cleanup stats that path before the server
        # starts and refuses to run, so the cleanup must be off. The client
        # reaches the listener through a hard link in a readable directory.
        private = self.root / "private"
        private.mkdir()
        public = self.root / "public"
        public.mkdir()
        listener = listening(private / "relay.sock")
        self.addCleanup(listener.close)
        os.link(private / "relay.sock", public / "relay.sock")
        os.chmod(private, 0o000)
        self.addCleanup(os.chmod, private, 0o700)
        process = start_relay(listener, self.upstream.path, os.getuid())
        try:
            client = self.connect(public / "relay.sock")
            client.sendall(b"ping")
            self.assertEqual(read_exactly(client, len(b"pong:ping")), b"pong:ping")
        finally:
            errors = stop_relay(process)
        self.assertEqual(process.returncode, 0, errors)

    def test_systemd_activation_is_required(self):
        # Without systemd's activation environment the relay must not serve.
        result = subprocess.run(
            [
                sys.executable,
                str(SOURCE),
                "--upstream",
                self.upstream.path,
                "--engine-uid",
                str(os.getuid()),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("systemd", result.stderr)

    def test_non_unix_listener_is_refused(self):
        # The listener must be the Unix socket systemd passed on fd 3.
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.bind(("127.0.0.1", 0))
        tcp.listen(1)
        self.addCleanup(tcp.close)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                BOOTSTRAP,
                str(tcp.fileno()),
                sys.executable,
                str(SOURCE),
                "--upstream",
                self.upstream.path,
                "--engine-uid",
                str(os.getuid()),
            ],
            pass_fds=(tcp.fileno(),),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, errors = process.communicate(timeout=30)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("Unix socket", errors)

    def test_root_engine_uid_is_refused(self):
        # UID 0 must never be an authorized peer.
        result = subprocess.run(
            [
                sys.executable,
                str(SOURCE),
                "--upstream",
                self.upstream.path,
                "--engine-uid",
                "0",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unprivileged", result.stderr)

    def test_only_the_configured_engine_uid_is_authorized(self):
        self.assertTrue(relay.authorized(62040, 62040))
        self.assertFalse(relay.authorized(62041, 62040))
        self.assertFalse(relay.authorized(0, 62040))
        self.assertFalse(relay.authorized(0, 0))
        with self.assertRaises(ValueError):
            relay.engine_uid("0")
        with self.assertRaises(ValueError):
            relay.engine_uid("-1")
        with self.assertRaises(ValueError):
            relay.engine_uid("engine")


class RelayUpstream(unittest.IsolatedAsyncioTestCase):
    """The authorization decision happens before any byte is forwarded."""

    @unittest.skipIf(os.getuid() == 0, "the engine peer must be an unprivileged UID")
    async def test_authorized_peer_is_connected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "engine.sock"
            upstream = Upstream(path)
            self.addCleanup(upstream.close)
            reader, writer = await relay.open_upstream(path, os.getuid())
            try:
                writer.write(b"ping")
                await writer.drain()
                answer = await asyncio.wait_for(reader.read(64), 10)
                self.assertEqual(answer, b"pong:ping")
            finally:
                writer.close()

    async def test_foreign_peer_is_refused_without_forwarding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "engine.sock"
            upstream = Upstream(path)
            self.addCleanup(upstream.close)
            with self.assertRaises(PermissionError):
                await relay.open_upstream(path, os.getuid() + 1)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not upstream.received:
                await asyncio.sleep(0.05)
            self.assertEqual(bytes(upstream.received), b"")

    async def test_failed_peer_credentials_close_the_upstream_socket(self):
        # A peer credential read that fails must close the upstream socket
        # instead of leaving it to the garbage collector, which keeps the
        # refused peer connected and the descriptor open.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "engine.sock"
            upstream = Upstream(path)
            self.addCleanup(upstream.close)
            before = len(os.listdir("/proc/self/fd"))
            with (
                patch.object(relay, "peer_credentials", side_effect=OSError("no peer")),
                patch.object(relay, "close_writer", wraps=relay.close_writer) as closer,
                self.assertRaises(OSError),
            ):
                await relay.open_upstream(path, os.getuid())
            self.assertEqual(closer.call_count, 1)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not upstream.closed:
                await asyncio.sleep(0.05)
            self.assertTrue(upstream.closed, "the upstream socket stayed open")
            self.assertLessEqual(len(os.listdir("/proc/self/fd")), before)


if __name__ == "__main__":
    unittest.main()
