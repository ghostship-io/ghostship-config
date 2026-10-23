"""Refuse an engine configuration whose scoped helper paths cannot serve workloads."""

import argparse
import os
import shutil
import tomllib

REQUIRED = ("rootlessport", "netavark", "aardvark-dns", "catatonit")


def check_helpers(config):
    directories = config.get("engine", {}).get("helper_binaries_dir", [])
    path = os.pathsep.join(directories)
    missing = [name for name in REQUIRED if not shutil.which(name, path=path)]
    if missing:
        raise ValueError(
            "Podman helper directories lack executable helpers: " + ", ".join(missing)
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    args = parser.parse_args()
    with open(args.config, "rb") as handle:
        config = tomllib.load(handle)
    try:
        check_helpers(config)
    except ValueError as error:
        parser.error(str(error))
    print("Required Podman helpers are executable in the configured directories")


if __name__ == "__main__":
    main()
