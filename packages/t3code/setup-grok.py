"""Install Grok Build and its persistent T3 container update hooks."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    home = Path.home()
    prefix = home / ".local/share/t3code-tools/grok"
    prefix.mkdir(parents=True, exist_ok=True)
    # The npm launcher resolves its optional platform package without postinstall.
    # Keep it isolated from T3's npm prefix and never install Grok's "agent" alias.
    subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(prefix),
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "@xai-official/grok@latest",
        ],
        check=True,
        timeout=180,
    )
    executable = prefix / "node_modules/.bin/grok"
    subprocess.run([executable, "--version"], check=True, timeout=30)
    target = home / ".local/bin/grok"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".grok-install")
    temporary.write_text(
        '#!/bin/sh\nset -eu\nexec "$HOME/.local/share/t3code-tools/grok/node_modules/.bin/grok" "$@"\n'
    )
    temporary.chmod(0o755)
    os.replace(temporary, target)
    if "--update" in sys.argv[1:]:
        return
    root = home / ".t3code-container"
    root.mkdir(parents=True, exist_ok=True)
    script = root / "setup-grok.py"
    if Path(__file__).resolve() != script.resolve():
        shutil.copyfile(__file__, script)
    for phase in ("bootstrap.d", "after-update.d"):
        hook = root / "hooks" / phase / "46-grok-cli-update"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            '#!/bin/sh\nexec python3 "$HOME/.t3code-container/setup-grok.py" --update\n'
        )
        hook.chmod(0o755)


if __name__ == "__main__":
    main()
