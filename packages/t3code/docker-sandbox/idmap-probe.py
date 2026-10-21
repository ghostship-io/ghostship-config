"""Verify the bind ownership mapping on the real host kernel, using fresh data.

Run as host root. This creates no accounts and touches no project or T3 state.
The nonroot write results are reported as compatibility evidence, not hidden.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise SystemExit("run on the target host as root")
    with tempfile.TemporaryDirectory(prefix="t3-idmap-", dir="/var/tmp") as directory:
        root = Path(directory)
        root.chmod(0o755)
        source, target = root / "source", root / "mapped"
        source.mkdir()
        target.mkdir()
        os.chown(source, 3000, 3000)
        subprocess.run(
            [
                "mount",
                "--bind",
                "-o",
                "X-mount.idmap=b:3000:62040:1",
                str(source),
                str(target),
            ],
            check=True,
        )
        try:
            results = {
                "source_uid": source.stat().st_uid,
                "mapped_uid": target.stat().st_uid,
                "writes": {},
            }
            for container_uid, host_uid in [
                (0, 62040),
                (3000, 2002999),
                (1000, 2000999),
            ]:
                path = target / f"uid-{container_uid}"
                code = "import os,sys; from pathlib import Path; os.setgroups([]); os.setgid(int(sys.argv[1])); os.setuid(int(sys.argv[1])); Path(sys.argv[2]).write_text('probe')"
                result = subprocess.run(
                    [sys.executable, "-c", code, str(host_uid), str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                results["writes"][str(container_uid)] = {
                    "success": result.returncode == 0,
                    "source_uid": (source / path.name).stat().st_uid
                    if path.exists()
                    else None,
                }
            print(json.dumps(results, indent=2))
            return (
                0
                if results["mapped_uid"] == 62040
                and results["writes"]["0"]["success"]
                and results["writes"]["0"]["source_uid"] == 3000
                else 1
            )
        finally:
            subprocess.run(["umount", str(target)], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
