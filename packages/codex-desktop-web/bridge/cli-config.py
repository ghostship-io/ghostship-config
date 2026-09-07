"""Decode the desktop's CLI overrides for a persistent app-server connection."""

import json
import sys
import tomllib


def parse_overrides(arguments):
    overrides = {}
    arguments = iter(arguments)
    for argument in arguments:
        if argument in ("-c", "--config"):
            value = next(arguments)
        elif argument.startswith("--config="):
            value = argument.removeprefix("--config=")
        else:
            continue
        key, separator, value = value.partition("=")
        if not separator or not key.strip():
            raise ValueError("invalid desktop CLI configuration override")
        # Keep dotted keys intact: thread/start's config uses flattened paths.
        try:
            parsed = tomllib.loads("value = " + value.strip())["value"]
        except (tomllib.TOMLDecodeError, KeyError):
            # Match Codex CLI's literal-string fallback for e.g. model=gpt-5.
            parsed = value.strip().strip("\"'")
        key = key.strip()
        if key == "use_legacy_landlock":
            key = "features.use_legacy_landlock"
        overrides[key] = parsed
    return overrides


if __name__ == "__main__":
    json.dump(parse_overrides(json.load(sys.stdin)), sys.stdout)
