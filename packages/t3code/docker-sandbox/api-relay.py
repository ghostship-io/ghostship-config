"""Relay the rootless Docker engine API over a peer-authorized Unix socket.

The engine API socket lives in the runtime directory that the untrusted
rootless container may write, so the path itself proves nothing: the container
can replace `docker.sock` with a symlink to any host socket, including the
root-only Podman or Nix daemon sockets. A relay that forwards to whatever the
path resolves to lends its own root privileges to those host services as a
confused deputy.

This relay therefore authorizes the peer, not the path. Every upstream
connection is checked with SO_PEERCRED before a single application byte is
forwarded: the peer UID must equal the configured engine UID, and UID 0 is
never authorized. A redirected path fails closed instead of handing root
credentials to a host service.

The listener is the socket systemd hands over on fd 3. systemd owns that
socket and its path, so this process never creates, binds or unlinks it. The
server therefore runs with asyncio's socket cleanup disabled, which otherwise
stats the listener path and unlinks it when the server closes.
"""

import argparse
import asyncio
import importlib.util
import logging
import os
import signal
import socket
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

LISTEN_FD = 3
PEERCRED = struct.Struct("3i")
CONNECT_TIMEOUT = 5


def load_ports():
    """Load the shared forwarding helpers that are packaged beside this file."""
    path = Path(__file__).with_name("ports.py")
    spec = importlib.util.spec_from_file_location("docker_ports", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ports = load_ports()


def peer_credentials(sock):
    """Return the (pid, uid, gid) of the process at the other end of a socket."""
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, PEERCRED.size)
    return PEERCRED.unpack(raw)


def engine_uid(value):
    """Parse the configured engine UID; UID 0 is never an authorized peer."""
    try:
        uid = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"engine UID must be an integer: {value!r}") from error
    if uid <= 0:
        raise ValueError("engine UID must be a positive unprivileged UID")
    return uid


def authorized(peer, expected):
    """Authorize only the configured unprivileged engine UID."""
    return expected != 0 and peer == expected


async def close_writer(writer):
    """Close a stream writer without letting a reset mask the decision."""
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


async def open_upstream(path, uid, timeout=CONNECT_TIMEOUT):
    """Connect to the engine API socket and authorize its peer by SO_PEERCRED.

    The peer of a connected Unix socket is the process that owns the listening
    endpoint, so this check follows the socket itself instead of the path. A
    symlink, a replaced socket or a swapped inode cannot change the answer.
    """
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), timeout)
    try:
        sock = writer.get_extra_info("socket")
        if sock is None:
            raise OSError("upstream connection carries no socket")
        pid, peer, _gid = peer_credentials(sock)
        if not authorized(peer, uid):
            logger.warning(
                "refusing upstream peer uid %d (pid %d): the engine uid is %d",
                peer,
                pid,
                uid,
            )
            raise PermissionError(
                f"upstream peer uid {peer} is not the engine uid {uid}"
            )
    except BaseException:
        # Every refused or failed upstream closes its socket here, so a peer
        # that is not the engine cannot hold a descriptor open.
        await close_writer(writer)
        raise
    return reader, writer


def upstream_connect(path, uid):
    """Build the connect callback that the shared forwarder expects."""

    async def connect(_reader):
        return await open_upstream(path, uid)

    return connect


async def serve(listener, path, uid):
    """Forward accepted clients to the engine API, authorized by peer UID."""
    connect = upstream_connect(path, uid)
    server = await asyncio.start_unix_server(
        lambda reader, writer: ports.start_forward(reader, writer, connect),
        sock=listener,
        # systemd owns the listener and its socket path. asyncio would stat
        # that path to remember its inode, which fails when the relay cannot
        # reach the directory, and it would unlink the socket it never
        # created when the server closes.
        cleanup_socket=False,
    )
    stop = asyncio.get_running_loop().create_future()

    def request_stop():
        if not stop.done():
            stop.set_result(None)

    for number in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(number, request_stop)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
    logger.info("relaying %s for engine uid %d", path, uid)
    try:
        await stop
    finally:
        server.close()
        try:
            # Wait for the open connections only briefly: a client that never
            # closes must not keep the relay alive past its stop.
            await asyncio.wait_for(server.wait_closed(), 1)
        except TimeoutError:
            logger.info("relay stopped with open connections")


def activated_listener(fd=LISTEN_FD):
    """Adopt the listening socket that systemd passed on fd 3."""
    if os.environ.get("LISTEN_PID") != str(os.getpid()):
        raise RuntimeError("relay requires a systemd activated socket")
    if os.environ.get("LISTEN_FDS") != "1":
        raise RuntimeError("relay requires exactly one systemd listening socket")
    sock = socket.socket(fileno=fd)
    try:
        if sock.family != socket.AF_UNIX:
            raise RuntimeError("relay listener must be a Unix socket")
        if sock.type != socket.SOCK_STREAM:
            raise RuntimeError("relay listener must be a stream socket")
        if not sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
            raise RuntimeError("relay listener must be a listening socket")
    except RuntimeError:
        sock.close()
        raise
    return sock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, help="engine API socket path")
    parser.add_argument(
        "--engine-uid", required=True, help="UID allowed to serve the engine API"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        uid = engine_uid(args.engine_uid)
    except ValueError as error:
        parser.error(str(error))
    try:
        listener = activated_listener()
    except RuntimeError as error:
        parser.error(str(error))
    asyncio.run(serve(listener, args.upstream, uid))


if __name__ == "__main__":
    main()
