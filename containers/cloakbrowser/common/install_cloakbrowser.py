#!/usr/bin/env python3
import os
import stat
import subprocess
from pathlib import Path

from cloakbrowser.download import ensure_binary


target = Path('/opt/cloakbrowser/chrome')
target.parent.mkdir(parents=True, exist_ok=True)

original_binary_path = os.environ.pop('CLOAKBROWSER_BINARY_PATH', None)
try:
    source = Path(ensure_binary()).resolve()
finally:
    if original_binary_path is not None:
        os.environ['CLOAKBROWSER_BINARY_PATH'] = original_binary_path

if target.exists() or target.is_symlink():
    target.unlink()
target.symlink_to(source)

mode = source.stat().st_mode
source.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

version = subprocess.check_output([str(target), '--version'], text=True).strip()
print(f'Installed CloakBrowser binary at {target} -> {source}')
print(version)
