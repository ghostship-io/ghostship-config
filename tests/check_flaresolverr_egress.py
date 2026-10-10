"""Run as root with iproute2/nftables: isolated namespaces, no host rules changed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)


def main():
    prefix = "fs-review-" + str(os.getpid())
    router, fetcher, private, public = [prefix + "-" + n for n in ("r", "f", "i", "p")]
    namespaces = []
    servers = []
    ip = os.environ.get("IP_BINARY", "ip")
    nft = os.environ.get("NFT_BINARY", "nft")
    rules = Path(sys.argv[1]).read_text()
    def ns(name, *args, check=True):
        return run(ip, "netns", "exec", name, *args, check=check)
    def wire(peer, left, right, bridge=None):
        run(ip, "-n", router, "link", "add", left, "type", "veth", "peer", "name", right)
        run(ip, "-n", router, "link", "set", right, "netns", peer)
        if bridge:
            run(ip, "-n", router, "link", "set", left, "master", bridge)
        run(ip, "-n", router, "link", "set", left, "up")
        run(ip, "-n", peer, "link", "set", right, "up")
    def address(name, addr, dev):
        run(ip, "-n", name, "addr", "add", addr, "dev", dev)
    def server(name, port):
        servers.append(subprocess.Popen([ip, "netns", "exec", name, sys.executable,
            "-m", "http.server", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    def request(name, host, port, expected=True):
        source = "import urllib.request; print(urllib.request.urlopen('http://" + host + ":" + str(port) + "/', timeout=1).status)"
        result = ns(name, sys.executable, "-c", source, check=False)
        actual = result.returncode == 0 and result.stdout.strip() == "200"
        if actual != expected:
            raise AssertionError(f"{name} -> {host}:{port}: expected {expected}, got {actual}")
    try:
        for name in (router, fetcher, private, public):
            run(ip, "netns", "add", name)
            namespaces.append(name)
            run(ip, "-n", name, "link", "set", "lo", "up")
        run(ip, "-n", router, "link", "add", "br0", "type", "bridge")
        run(ip, "-n", router, "link", "set", "br0", "up")
        address(router, "10.89.0.1/24", "br0")
        wire(fetcher, "f0", "eth0", "br0")
        wire(private, "i0", "eth0", "br0")
        wire(public, "p0", "eth0")
        run(ip, "-n", fetcher, "link", "set", "eth0", "address", "02:89:00:00:00:16")
        for name, addr in [(fetcher, "10.89.0.16/24"), (private, "10.89.0.17/24"), (public, "1.1.1.2/24")]:
            address(name, addr, "eth0")
            gateway = "1.1.1.1" if name == public else "10.89.0.1"
            run(ip, "-n", name, "route", "add", "default", "via", gateway)
        address(router, "1.1.1.1/24", "p0")
        ns(router, "sysctl", "-qw", "net.ipv4.ip_forward=1")
        for name, port in [(fetcher,8191), (private,8080), (public,8080), (router,8080), (router,53)]:
            server(name, port)
        time.sleep(.5)
        # Establish that the private test endpoints work before loading policy.
        request(fetcher, "10.89.0.17", 8080)
        request(fetcher, "10.89.0.1", 8080)
        subprocess.run([ip,"netns","exec",router,nft,"-f","-"], input=rules, text=True, check=True)
        request(fetcher, "1.1.1.2", 8080)
        request(fetcher, "10.89.0.17", 8080, False)
        request(fetcher, "10.89.0.1", 8080, False)
        request(fetcher, "10.89.0.1", 53)
        request(private, "10.89.0.16", 8191)
        # Reloading the policy converges without duplicate rules or a gap.
        subprocess.run([ip,"netns","exec",router,nft,"-f","-"], input=rules, text=True, check=True)
        request(private, "10.89.0.16", 8191)
        request(fetcher, "10.89.0.17", 8080, False)
        print(json.dumps({"publicEgress":True,"privatePeerBlocked":True,
            "hostBlocked":True,"dnsAllowed":True,"apiRepliesAllowed":True,"reloadPassed":True}))
    finally:
        for process in servers:
            process.terminate()
            process.wait(timeout=5)
        for name in reversed(namespaces):
            run(ip,"netns","delete",name,check=False)


if __name__ == "__main__":
    main()
