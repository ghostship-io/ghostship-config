"""Fill a service configuration template with the owner identity values.

The values name the accounts the services log in as. They are supplied by the
deployment in a file outside this repository and reach the services through
their environment, so this repository keeps only the placeholder names.

Usage: render-owner-config.py <template> <output>
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Placeholder in a configuration template, and the setting that fills it.
PLACEHOLDERS = {
    "@GHOSTSHIP_GITHUB_ACCOUNT@": "GHOSTSHIP_GITHUB_ACCOUNT",
    "@GHOSTSHIP_KEEP_PERSONAL_EMAIL@": "GHOSTSHIP_KEEP_PERSONAL_EMAIL",
    "@GHOSTSHIP_KUMA_USERNAME@": "GHOSTSHIP_KUMA_USERNAME",
    "@GHOSTSHIP_NTFY_ADMIN_USER@": "GHOSTSHIP_NTFY_ADMIN_USER",
}


class MissingIdentity(Exception):
    """A placeholder has no configured value."""


def used_placeholders(template: str) -> list[str]:
    """The placeholders a template uses, in the order they appear."""
    found: list[str] = []
    for placeholder in PLACEHOLDERS:
        if placeholder in template and placeholder not in found:
            found.append(placeholder)
    return found


def identity(template: str, environ: dict | None = None) -> dict[str, str]:
    """The values the template needs; a missing value is an error.

    A template never falls back to a default: an unconfigured identity is a
    deployment mistake, not something to guess.
    """
    environ = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for placeholder in used_placeholders(template):
        name = PLACEHOLDERS[placeholder]
        value = (environ.get(name) or "").strip()
        if not value:
            raise MissingIdentity(
                f"{name} is not set; the owner identity file must define it"
            )
        values[placeholder] = value
    return values


def render(template: str, environ: dict | None = None) -> str:
    """A template with every placeholder it uses replaced by its value."""
    rendered = template
    for placeholder, value in identity(template, environ).items():
        # The placeholder sits inside a JSON string, so the value is escaped
        # the way the surrounding document escapes it.
        escaped = json.dumps(value)[1:-1]
        rendered = rendered.replace(placeholder, escaped)
    return rendered


def write(template_path: str, output_path: str, environ: dict | None = None,
          mode: int = 0o600) -> None:
    """Render a template file into an output file, atomically."""
    template = Path(template_path).read_text(encoding="utf-8")
    rendered = render(template, environ)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(
            "Usage: render-owner-config.py <template> <output> [mode]",
            file=sys.stderr,
        )
        return 1
    mode = 0o600
    if len(sys.argv) == 4:
        try:
            mode = int(sys.argv[3], 8)
        except ValueError:
            print("error: the output mode must be an octal number", file=sys.stderr)
            return 1
    try:
        write(sys.argv[1], sys.argv[2], mode=mode)
    except MissingIdentity as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
