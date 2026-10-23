"""Remove obsolete aliases of the dedicated service identity, retaining all data."""

import argparse
import grp
import os
import pwd
import subprocess


def retired_identities(users, groups, name, uid, home):
    canonical = next((entry for entry in users if entry.pw_name == name), None)
    canonical_group = next((entry for entry in groups if entry.gr_name == name), None)
    if (
        uid <= 0
        or canonical is None
        or canonical_group is None
        or (canonical.pw_uid, canonical.pw_gid, canonical.pw_dir) != (uid, uid, home)
        or canonical_group.gr_gid != uid
    ):
        raise ValueError(
            "canonical service identity does not match its configured UID and home"
        )
    prefix = name.rsplit("-", 1)[0] + "-"
    aliases = [
        entry for entry in users if entry.pw_uid == uid and entry.pw_name != name
    ]
    group_aliases = [
        entry for entry in groups if entry.gr_gid == uid and entry.gr_name != name
    ]
    for entry in aliases:
        if (
            not entry.pw_name.startswith(prefix)
            or entry.pw_gid != uid
            or entry.pw_dir != f"/var/lib/{entry.pw_name}/home"
            or not entry.pw_shell.endswith("/nologin")
        ):
            raise ValueError("unexpected account shares the dedicated service UID")
    for entry in group_aliases:
        if not entry.gr_name.startswith(prefix) or entry.gr_mem:
            raise ValueError("unexpected group shares the dedicated service GID")
    return [entry.pw_name for entry in aliases], [
        entry.gr_name for entry in group_aliases
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--home", required=True)
    parser.add_argument("--userdel", required=True)
    parser.add_argument("--groupdel", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as host root")
    users, groups = retired_identities(
        pwd.getpwall(), grp.getgrall(), args.name, args.uid, args.home
    )
    for name in users:
        # --force permits a duplicate numeric UID with running service processes.
        # No --remove: no home, engine store, volume or other data is deleted.
        subprocess.run([args.userdel, "--force", "--", name], check=True)
    for name in groups:
        try:
            grp.getgrnam(name)
        except KeyError:
            continue
        # The canonical group keeps this GID even while a stale name is removed.
        subprocess.run([args.groupdel, "--force", "--", name], check=True)
    remaining = retired_identities(
        pwd.getpwall(), grp.getgrall(), args.name, args.uid, args.home
    )
    if remaining != ([], []):
        raise ValueError("obsolete service aliases remain")
    print("Dedicated service account and group are unambiguous; all storage retained")


if __name__ == "__main__":
    main()
