#!/usr/bin/env python3
"""Turn a reviewed containment policy set into nftables rulesets.

Usage: generate-policy.py --policy <policy.json> --out <directory>

The policy set is a JSON object produced by modules/self-hosted/container-isolation.nix.
Every policy is admitted before anything is written: an unsupported topology,
a missing identity or a container that keeps NET_ADMIN stops the build instead
of producing a policy that cannot hold.

The output directory holds one ruleset per policy plus a manifest that lists
the approved edges and the observed dependencies that are still unresolved.
Observed edges never reach a ruleset.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import policy  # noqa: E402  (path is set above)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, help="policy set JSON")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)

    policies = policy.load(args.policy)
    try:
        policy.admit(policies)
    except policy.PolicyError as error:
        print(f"container-isolation: {error}", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    for name, entry in (policies.get("containers") or {}).items():
        rules = policy.render_container(name, entry)
        with open(os.path.join(args.out, f"{name}.nft"), "w") as handle:
            handle.write(rules)
        with open(os.path.join(args.out, f"{name}-unload.nft"), "w") as handle:
            handle.write(policy.render_unload(name))
    manifest = policy.manifest(policies)
    with open(os.path.join(args.out, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
        handle.write("\n")
    unresolved = sum(len(entry["unresolved"]) for entry in manifest["containers"].values())
    print(
        json.dumps(
            {
                "policies": len(manifest["containers"]),
                "unresolved": unresolved,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
