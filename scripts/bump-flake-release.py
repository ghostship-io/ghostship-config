"""Give a changed lock file a patch release in the weekly maintenance PR."""

import datetime
import subprocess
from pathlib import Path

if subprocess.run(
    ["git", "diff", "--quiet", "--", "flake.lock"], check=False
).returncode:
    version_file = Path("VERSION")
    major, minor, patch = map(int, version_file.read_text().strip().split("."))
    version = f"{major}.{minor}.{patch + 1}"
    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    anchor = "## Unreleased\n"
    if text.count(anchor) != 1:
        raise SystemExit("Expected one Unreleased heading in CHANGELOG.md")
    date = datetime.datetime.now(datetime.UTC).date().isoformat()
    entry = (
        f"\n## [{version}] - {date}\n\n"
        "- Refresh coordinated Nix inputs; evaluate all hosts and run configuration checks.\n"
    )
    changelog.write_text(text.replace(anchor, anchor + entry, 1))
    version_file.write_text(version + "\n")
