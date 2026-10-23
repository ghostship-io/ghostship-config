"""Private Unix gateway + unprivileged T3 localhost bridge for published ports.

Gateway protocol is exactly two network-order bytes selecting a TCP port >=1024,
followed by the byte stream. Destination is ALWAYS namespace-local 127.0.0.1.
The gateway runs in the host-owned dev namespace and uses systemd socket
activation. Bridge runs inside T3, discovers Podman-published ports, and binds
only 127.0.0.1. It never replaces a listener already owned by another process.
"""

import argparse
import asyncio
import http.client
import json
import logging
import os
import socket
import struct

logger = logging.getLogger(__name__)
active_connections = set()


def start_forward(reader, writer, connect):
    # Keep a strong task reference through half-close: StreamReaderProtocol
    # releases its task when a transport closes, before both pumps settle.
    task = asyncio.create_task(forward(reader, writer, connect))
    active_connections.add(task)
    task.add_done_callback(active_connections.discard)
    return task


def published_ports(containers):
    return {
        port["PublicPort"]
        for container in containers or []
        for port in container.get("Ports") or []
        if port.get("Type") == "tcp"
        and port.get("IP", "") in ("", "0.0.0.0", "127.0.0.1")
        and 1024 <= port.get("PublicPort", 0) <= 65535
    }


class PodmanConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=5)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def discover(path):
    connection = PodmanConnection(path)
    try:
        connection.request("GET", "/containers/json")
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Podman API returned {response.status}")
        return published_ports(json.load(response))
    finally:
        connection.close()


async def pump(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


async def forward(reader, writer, connect):
    upstream = None
    tasks = []
    try:
        other_reader, upstream = await connect(reader)
        tasks = [
            asyncio.create_task(pump(reader, upstream)),
            asyncio.create_task(pump(other_reader, writer)),
        ]
        await asyncio.gather(*tasks)
    except (
        ConnectionError,
        OSError,
        asyncio.TimeoutError,
        asyncio.IncompleteReadError,
        ValueError,
    ) as error:
        logger.debug("port stream closed: %s", error)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        if upstream is not None:
            upstream.close()


async def gateway_connect(reader):
    port = struct.unpack("!H", await asyncio.wait_for(reader.readexactly(2), 5))[0]
    if port < 1024:
        raise ValueError("only high development ports are allowed")
    return await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 5)


async def gateway():
    if (
        os.environ.get("LISTEN_PID") != str(os.getpid())
        or os.environ.get("LISTEN_FDS") != "1"
    ):
        raise RuntimeError("gateway requires exactly one systemd Unix listening socket")
    listener = socket.socket(fileno=3)
    if listener.family != socket.AF_UNIX:
        raise RuntimeError("gateway listener must be a Unix socket")
    server = await asyncio.start_unix_server(
        lambda r, w: start_forward(r, w, gateway_connect),
        sock=listener,
        # systemd owns the listener and its socket path, and the dynamic user
        # cannot stat that path. asyncio would stat it to remember the inode
        # for unlinking, which fails with PermissionError, and it must not
        # unlink a socket it never created.
        cleanup_socket=False,
    )
    async with server:
        await server.serve_forever()


async def bridge(api_socket, gateway_socket):
    servers = {}

    def handler(port):
        async def connect(_reader):
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(gateway_socket), 5
            )
            writer.write(struct.pack("!H", port))
            await writer.drain()
            return reader, writer

        return lambda reader, writer: start_forward(reader, writer, connect)

    try:
        while True:
            try:
                desired = await asyncio.to_thread(discover, api_socket)
            except (
                OSError,
                ValueError,
                http.client.HTTPException,
                RuntimeError,
            ) as error:
                logger.warning("Podman port discovery failed: %s", error)
                desired = set()  # stale listeners must not expose a reused port
            for port in set(servers) - desired:
                servers.pop(port).close()
            for port in desired - set(servers):
                try:
                    servers[port] = await asyncio.start_server(
                        handler(port), "127.0.0.1", port
                    )
                    logger.info("forwarding 127.0.0.1:%s", port)
                except OSError as error:
                    logger.warning("cannot bind localhost port %s: %s", port, error)
            await asyncio.sleep(1)
    finally:
        for server in servers.values():
            server.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("gateway", "bridge"))
    parser.add_argument("--api-socket", default="/var/run/podman/podman.sock")
    parser.add_argument("--gateway-socket", default="/var/run/t3code-podman-ports.sock")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(
        gateway()
        if args.mode == "gateway"
        else bridge(args.api_socket, args.gateway_socket)
    )


if __name__ == "__main__":
    main()
