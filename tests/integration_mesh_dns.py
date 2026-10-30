"""Exercise the shipped DNS routing rules with real, isolated DNS servers."""
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "modules/common/mesh-dns.conf"


class MeshDNS(unittest.TestCase):
    def test_private_outage_does_not_break_or_leak_to_ordinary_dns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            children = []
            logs = []

            def port():
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    return listener.getsockname()[1]

            def start(number, extra):
                log = (root / f"server-{len(logs)}.log").open("w+")
                logs.append(log)
                process = subprocess.Popen(
                    ["dnsmasq", "--no-daemon", "--no-resolv", "--no-hosts",
                     "--bind-interfaces", "--listen-address=127.0.0.1",
                     f"--port={number}", "--cache-size=0", "--pid-file=",
                     *extra], stdout=log, stderr=log,
                )
                children.append(process)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        self.fail(log.read())
                    try:
                        with socket.create_connection(("127.0.0.1", number), timeout=0.1):
                            return process
                    except OSError:
                        time.sleep(0.02)
                self.fail("DNS server did not become ready")

            def query(number, name):
                return subprocess.run(
                    ["dig", "@127.0.0.1", "-p", str(number), name, "A",
                     "+tries=1", "+time=1", "+short"],
                    capture_output=True, text=True, timeout=3,
                )

            def answer(number, name, expected):
                result = query(number, name)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

            try:
                ordinary_port = port()
                upstream_log = root / "ordinary-queries.log"
                start(ordinary_port, [
                    "--host-record=public.example.test,192.0.2.42",
                    "--host-record=nas.lan,192.168.1.9",
                    "--log-queries", f"--log-facility={upstream_log}",
                ])
                private_port = port()
                private_args = [
                    "--host-record=launch-octopus.mesh.ghostship.io,100.96.0.2",
                    "--local=/mesh.ghostship.io/",
                ]
                private = start(private_port, private_args)
                config = root / "mesh-dns.conf"
                config.write_text(SOURCE.read_text().replace(
                    "127.0.2.2", f"127.0.0.1#{private_port}",
                ))
                dispatcher = port()
                start(dispatcher, [
                    f"--conf-file={config}",
                    f"--server=127.0.0.1#{ordinary_port}",
                ])

                answer(dispatcher, "public.example.test", "192.0.2.42")
                answer(dispatcher, "nas.lan", "192.168.1.9")
                answer(dispatcher, "launch-octopus.mesh.ghostship.io", "100.96.0.2")
                answer(dispatcher, "unknown.mesh.ghostship.io", "")

                private.terminate()
                private.wait(timeout=2)
                offline = query(dispatcher, "offline.mesh.ghostship.io")
                self.assertNotIn("100.96.0.2", offline.stdout)
                answer(dispatcher, "public.example.test", "192.0.2.42")
                answer(dispatcher, "nas.lan", "192.168.1.9")
                self.assertNotIn("mesh.ghostship.io", upstream_log.read_text())

                start(private_port, private_args)
                answer(dispatcher, "launch-octopus.mesh.ghostship.io", "100.96.0.2")
            finally:
                for process in reversed(children):
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                for log in logs:
                    log.close()


if __name__ == "__main__":
    unittest.main()
