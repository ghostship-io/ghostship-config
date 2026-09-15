#!/usr/bin/env python3
"""Delegate shared agent installation to its owner, ghostship-agent."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source", type=Path, default=Path("/workspace/ghostship-agent"))
    args, _ = parser.parse_known_args()
    installer = args.source / "tools/setup-container-agents.py"
    if not installer.is_file():
        raise SystemExit(f"Shared agent installer is missing: {installer}; update ghostship-agent")
    os.execv(sys.executable, [sys.executable, str(installer), *sys.argv[1:]])


if __name__ == "__main__":
    main()
