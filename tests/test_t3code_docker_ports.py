"""Exercise the real Unix-to-localhost data path and listener restrictions."""

import asyncio
import contextlib
import errno
import importlib.util
import json
import os
import socket
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "packages/t3code/docker-sandbox/ports.py"
SPEC = importlib.util.spec_from_file_location("docker_ports", SOURCE)
ports = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ports)


async def echo(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    writer.close()


class SocketProxy:
    """Stand in for the socket module while recording inherited sockets."""

    def __init__(self, module, created):
        self._module = module
        self._created = created

    def __getattr__(self, name):
        return getattr(self._module, name)

    def socket(self, *args, **kwargs):
        inherited = self._module.socket(*args, **kwargs)
        self._created.append(inherited)
        return inherited


def inherit_fd_three(listener):
    """Publish a listener on fd 3 the way systemd socket activation does."""
    try:
        saved = os.dup(3)
    except OSError:
        saved = None
    os.dup2(listener.fileno(), 3)
    return saved


def restore_fd_three(saved):
    if saved is None:
        with contextlib.suppress(OSError):
            os.close(3)
        return
    os.dup2(saved, 3)
    os.close(saved)


async def connect_gateway(gateway, gateway_path):
    for _ in range(100):
        if gateway.done():
            gateway.result()
        try:
            return await asyncio.open_unix_connection(gateway_path)
        except (ConnectionRefusedError, FileNotFoundError):
            await asyncio.sleep(0.01)
    raise AssertionError("gateway did not accept connections")


async def read_or_fail(gateway, reader, count):
    """Read a reply, surfacing a gateway startup failure instead of hanging."""
    read = asyncio.create_task(reader.readexactly(count))
    done, _ = await asyncio.wait({read, gateway}, return_when=asyncio.FIRST_COMPLETED)
    if gateway in done and not gateway.cancelled() and gateway.exception():
        read.cancel()
        gateway.result()
    return await asyncio.wait_for(read, 5)


class PortBridge(unittest.IsolatedAsyncioTestCase):
    async def test_reset_closes_idle_opposite_stream(self):
        # Defect: swallowing a reset retains the idle opposite connection and
        # consumes gateway descriptors indefinitely.
        upstream_writers = []
        connected = asyncio.Event()
        finished = asyncio.Event()

        async def idle(_reader, writer):
            upstream_writers.append(writer)
            connected.set()

        upstream = await asyncio.start_server(idle, "127.0.0.1", 0)
        port = upstream.sockets[0].getsockname()[1]

        async def connect(_reader):
            return await asyncio.open_connection("127.0.0.1", port)

        def proxy(reader, writer):
            task = ports.start_forward(reader, writer, connect)
            task.add_done_callback(lambda _task: finished.set())

        gateway = await asyncio.start_server(proxy, "127.0.0.1", 0)
        _, client = await asyncio.open_connection(
            "127.0.0.1", gateway.sockets[0].getsockname()[1]
        )
        try:
            await connected.wait()
            client.get_extra_info("socket").setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
            client.transport.abort()
            await asyncio.wait_for(finished.wait(), 1)
        finally:
            client.close()
            for writer in upstream_writers:
                writer.close()
            upstream.close()
            gateway.close()
            await upstream.wait_closed()
            await gateway.wait_closed()

    async def test_random_published_port_flows_through_unix_gateway(self):
        # Defect: Compose-assigned ports are not discovered or the Unix hop
        # loses bytes/half-close. These are real sockets, with no Docker mocks.
        with tempfile.TemporaryDirectory() as directory:
            gateway_path = str(Path(directory) / "gateway.sock")
            api_path = str(Path(directory) / "api.sock")
            target = await asyncio.start_server(echo, "127.0.0.1", 0)
            target_port = target.sockets[0].getsockname()[1]
            # Bridge and gateway normally occupy distinct network namespaces.
            # Pick a second port for this single-namespace unit test and patch
            # only the gateway's target selection, retaining the Unix protocol.
            reservation = socket.socket()
            reservation.bind(("127.0.0.1", 0))
            public_port = reservation.getsockname()[1]
            reservation.close()

            async def connect(reader):
                requested = struct.unpack("!H", await reader.readexactly(2))[0]
                self.assertEqual(requested, public_port)
                return await asyncio.open_connection("127.0.0.1", target_port)

            gateway = await asyncio.start_unix_server(
                lambda r, w: ports.start_forward(r, w, connect), gateway_path
            )

            async def api(reader, writer):
                await reader.readuntil(b"\r\n\r\n")
                body = json.dumps(
                    [
                        {
                            "Ports": [
                                {
                                    "Type": "tcp",
                                    "IP": "0.0.0.0",
                                    "PublicPort": public_port,
                                }
                            ]
                        }
                    ]
                ).encode()
                writer.write(
                    b"HTTP/1.0 200 OK\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )
                await writer.drain()
                writer.close()

            api_server = await asyncio.start_unix_server(api, api_path)
            bridge = asyncio.create_task(ports.bridge(api_path, gateway_path))
            try:
                for attempt in range(100):
                    try:
                        reader, writer = await asyncio.open_connection(
                            "127.0.0.1", public_port
                        )
                        break
                    except ConnectionRefusedError:
                        await asyncio.sleep(0.01)
                else:
                    self.fail("bridge did not discover assigned port")
                writer.write(b"compose-random-port\x00\xff")
                await writer.drain()
                writer.write_eof()
                self.assertEqual(
                    await asyncio.wait_for(reader.read(), 3),
                    b"compose-random-port\x00\xff",
                )
                writer.close()
            finally:
                bridge.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await bridge
                for server in (gateway, api_server, target):
                    server.close()
                    await server.wait_closed()

    async def test_gateway_accepts_only_high_loopback_destinations(self):
        # Defect: an apps client uses the gateway for privileged or arbitrary
        # host/LAN destinations. The wire protocol cannot encode an address.
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!H", 22))
        with self.assertRaises(ValueError):
            await ports.gateway_connect(reader)
        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!H", port))
        try:
            _, writer = await ports.gateway_connect(reader)
            self.assertEqual(writer.get_extra_info("peername"), ("127.0.0.1", port))
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    def test_discovery_rejects_udp_privileged_and_address_specific_ports(self):
        containers = [
            {
                "Ports": [
                    {"Type": kind, "IP": address, "PublicPort": port}
                    for kind, address, port in [
                        ("tcp", "0.0.0.0", 32768),
                        ("tcp", "127.0.0.1", 8080),
                        ("udp", "0.0.0.0", 9000),
                        ("tcp", "0.0.0.0", 22),
                        ("tcp", "192.0.2.2", 9090),
                        ("tcp", "::", 9001),
                    ]
                ]
            }
        ]
        self.assertEqual(ports.published_ports(containers), {32768, 8080})


class GatewaySocketActivation(unittest.TestCase):
    """The gateway inherits its listener from systemd on file descriptor 3."""

    def test_gateway_serves_when_inherited_socket_cannot_be_stated(self):
        # Defect: systemd owns the AF_UNIX listener and its path, and the
        # dynamic user cannot stat that path. asyncio's default socket
        # cleanup stat raised PermissionError, so the gateway never served.
        with tempfile.TemporaryDirectory() as directory:
            gateway_path = str(Path(directory) / "ports.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(gateway_path)
            listener.listen(128)
            saved = inherit_fd_three(listener)
            try:
                # The event loop must start after fd 3 is taken, exactly like
                # a systemd-activated service that inherits the listener.
                with asyncio.Runner() as runner:
                    runner.run(self.serve_gateway(gateway_path))
            finally:
                restore_fd_three(saved)
                listener.close()

    async def serve_gateway(self, gateway_path):
        target = await asyncio.start_server(echo, "127.0.0.1", 0)
        target_port = target.sockets[0].getsockname()[1]
        self.assertGreaterEqual(target_port, 1024)
        created = []
        real_stat = os.stat

        def guarded_stat(path, *args, **kwargs):
            if isinstance(path, (str, bytes)) and os.fspath(path) == gateway_path:
                raise PermissionError(errno.EACCES, "Permission denied", gateway_path)
            return real_stat(path, *args, **kwargs)

        try:
            with (
                mock.patch.object(os, "stat", guarded_stat),
                mock.patch.object(ports, "socket", SocketProxy(socket, created)),
                mock.patch.dict(
                    os.environ,
                    {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1"},
                ),
            ):
                gateway = asyncio.create_task(ports.gateway())
                try:
                    reader, writer = await connect_gateway(gateway, gateway_path)
                    writer.write(struct.pack("!H", target_port) + b"ping")
                    await writer.drain()
                    self.assertEqual(await read_or_fail(gateway, reader, 4), b"ping")
                    writer.close()
                finally:
                    gateway.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await gateway
            # systemd owns the socket path; the gateway must not unlink it.
            self.assertTrue(os.path.exists(gateway_path))
        finally:
            for inherited in created:
                inherited.close()
            target.close()
            await target.wait_closed()


if __name__ == "__main__":
    unittest.main()
