"""Exercise the real Unix-to-localhost data path and listener restrictions."""

import asyncio
import importlib.util
import json
import socket
import struct
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "packages/t3code/docker-sandbox/ports.py"
SPEC = importlib.util.spec_from_file_location("docker_ports", SOURCE)
ports = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ports)


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
            target = await asyncio.start_server(self.echo, "127.0.0.1", 0)
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

    @staticmethod
    async def echo(reader, writer):
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        writer.close()

    async def test_gateway_accepts_only_high_loopback_destinations(self):
        # Defect: an apps client uses the gateway for privileged or arbitrary
        # host/LAN destinations. The wire protocol cannot encode an address.
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!H", 22))
        with self.assertRaises(ValueError):
            await ports.gateway_connect(reader)
        server = await asyncio.start_server(self.echo, "127.0.0.1", 0)
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


if __name__ == "__main__":
    unittest.main()
