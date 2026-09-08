import grp
import os
import pwd
import shlex
import sys
import tempfile
from pathlib import Path

# Injected by the Nix wrapper; tests provide an isolated specification.
SPEC = globals().get("SPEC", {})


def parse_env_file(path_str):
    path = Path(path_str)
    values = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')):
            try:
                parts = shlex.split(value, comments=False)
            except ValueError:
                raise ValueError(f"Invalid quoting for secret {key}") from None
            if len(parts) != 1:
                raise ValueError(f"Invalid quoting for secret {key}")
            value = parts[0]
        values[key] = value
    return values


def write_projection(name):
    projection = SPEC["projections"][name]
    rendered = {}
    cache = {}
    for target_key, source in projection["fields"].items():
        unit_name = source["unit"]
        source_key = source["key"]
        if unit_name not in cache:
            cache[unit_name] = parse_env_file(SPEC["units"][unit_name]["path"])
        value = cache[unit_name].get(source_key)
        if value is not None and value != "":
            rendered[target_key] = value

    for raw in (False, True):
        output_path = Path(projection["path"] + (".container" if raw else ""))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(output_path.parent), prefix=f"{name}."
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w") as handle:
                for key, value in rendered.items():
                    if any(c in value for c in ("\n", "\r", "\x00")):
                        raise ValueError(f"Unsupported multiline secret {key}")
                    encoded = value if raw else shlex.quote(value)
                    handle.write(f"{key}={encoded}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_path, int(projection["mode"], 8))
            os.chown(
                tmp_path,
                pwd.getpwnam(projection["owner"]).pw_uid,
                grp.getgrnam(projection["group"]).gr_gid,
            )
            tmp_path.replace(output_path)
        finally:
            tmp_path.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: ghostship-secret-project <projection-name>",
            file=sys.stderr,
        )
        return 1
    name = sys.argv[1]
    if name not in SPEC["projections"]:
        print(f"Unknown projection: {name}", file=sys.stderr)
        return 1
    write_projection(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
