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
        shared_tmp = source / "shared-tmp"
        shared_tmp.mkdir()
        shared_tmp.chmod(0o1777)
        subprocess.run(
            [
                "mount",
                "--bind",
                "-o",
                "X-mount.idmap=b:3000:62040:1 b:2000000:2000000:65536",
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
            # Root-owned sticky directories such as T3's /tmp still need a
            # mapped inode owner, even when mode bits allow every user to write.
            temporary_write = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    code,
                    "62040",
                    str(target / "shared-tmp" / "file"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            results["root_owned_tmp_write"] = temporary_write.returncode == 0
            # Explicit, project-local permissions support nonroot images. No
            # ownership changes or broad permissions are applied to real data.
            subprocess.run(
                [
                    "setfacl",
                    "-m",
                    "u:2002999:rwx,u:2000999:rwx,d:u:3000:rwx,d:u:2002999:rwx,d:u:2000999:rwx",
                    str(source),
                ],
                check=True,
            )
            results["explicit_acl"] = {}
            for container_uid, host_uid in [(3000, 2002999), (1000, 2000999)]:
                path = target / f"acl-{container_uid}"
                code = "import os,sys; from pathlib import Path; os.setgroups([]); os.setgid(int(sys.argv[1])); os.setuid(int(sys.argv[1])); p=Path(sys.argv[2]); p.mkdir(); (p/'file').write_text('shared')"
                result = subprocess.run(
                    [sys.executable, "-c", code, str(host_uid), str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                cleanup = "import os,sys,shutil; from pathlib import Path; os.setgroups([]); os.setgid(3000); os.setuid(3000); (Path(sys.argv[1])/'file').write_text('edited'); shutil.rmtree(sys.argv[1])"
                cleaned = (
                    subprocess.run(
                        [sys.executable, "-c", cleanup, str(source / path.name)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode == 0
                    else None
                )
                results["explicit_acl"][str(container_uid)] = (
                    result.returncode == 0
                    and cleaned is not None
                    and cleaned.returncode == 0
                )
            print(json.dumps(results, indent=2))
            return (
                0
                if results["mapped_uid"] == 62040
                and results["writes"]["0"]["success"]
                and results["writes"]["0"]["source_uid"] == 3000
                and results["root_owned_tmp_write"]
                and all(results["explicit_acl"].values())
                else 1
            )
        finally:
            subprocess.run(["umount", str(target)], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
