"""Record live TCP canaries from a permitted host/control namespace."""

import argparse
import ipaddress
import json
import socket
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, action="append")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    endpoints = {}
    for endpoint in args.endpoint:
        address, port = endpoint.rsplit(":", 1)
        ipaddress.IPv4Address(address)
        with socket.create_connection((address, int(port)), timeout=3):
            endpoints[endpoint] = True
    args.output.write_text(
        json.dumps({"observed_at": time.time(), "endpoints": endpoints})
    )
    args.output.chmod(0o644)
    print(f"Verified {len(endpoints)} listening control endpoints")


if __name__ == "__main__":
    main()
