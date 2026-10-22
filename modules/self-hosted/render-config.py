"""Render a JSON configuration template with values from a secret projection.

The template is JSON text that may contain ``{{NAME}}`` placeholders. A
placeholder that is the whole string value is replaced by the literal text of
the variable; a placeholder written as ``{{NAME:json}}`` is replaced by the
JSON value of the variable, so a list or an object can be injected.

Values come from a dotenv-style projection file. The file may quote a value
with shell syntax, matching the reader used for the secret units themselves.

The publication directory belongs to the effective user. Its ancestors belong
to that user or root, contain no symlinks, and cannot be renamed by another
account. Root-owned sticky ancestors (such as /tmp) are allowed. Directory
descriptors anchor creation and rename; metadata is applied to the open file
descriptor before publication. No metadata operation follows a pathname.
"""

import errno
import json
import os
import re
import secrets
import shlex
import stat
import sys
from pathlib import Path


def parse_env_file(path):
    values = {}
    for raw_line in Path(path).read_text().splitlines():
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


def substitute(text, values):
    """Replace embedded {{NAME}} placeholders in one string value."""
    for key, value in values.items():
        text = text.replace("{{%s}}" % key, value)
    return text


def render_node(node, values):
    if isinstance(node, dict):
        return {key: render_node(item, values) for key, item in node.items()}
    if isinstance(node, list):
        return [render_node(item, values) for item in node]
    if not isinstance(node, str):
        return node
    if node.startswith("{{") and node.endswith(":json}}"):
        name = node[2:-len(":json}}")]
        if name not in values:
            raise KeyError("Missing secret value for placeholder " + name)
        return json.loads(values[name])
    if node.startswith("{{") and node.endswith("}}"):
        name = node[2:-2]
        if name not in values:
            raise KeyError("Missing secret value for placeholder " + name)
        return values[name]
    return substitute(node, values)


def open_publication_directory(directory):
    """Walk without symlinks, validate ownership, and retain the directory fd."""
    directory = Path(directory).absolute()
    if ".." in directory.parts:
        raise ValueError("publication path contains parent traversal")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        parts = directory.parts[1:]
        for index, component in enumerate(parts):
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise ValueError("publication path contains a symbolic link or non-directory") from None
                raise
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            leaf = index == len(parts) - 1
            if info.st_uid not in (0, os.geteuid()) or (leaf and info.st_uid != os.geteuid()):
                raise ValueError("publication path is owned by another account")
            if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                sticky_ancestor = not leaf and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
                if not sticky_ancestor:
                    raise ValueError("publication path is writable by another account")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def publish(target, text, mode, owner):
    """Write the text into the target, safely.

    The temporary file is created exclusively under a random name, the final
    mode and ownership are applied to it while it is still private, and only
    then is it renamed into place.
    """
    target = Path(target)
    directory = open_publication_directory(target.parent)
    temporary = None
    try:
        for _ in range(100):
            candidate = "." + target.name + "." + secrets.token_hex(16)
            try:
                descriptor = os.open(
                    candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600, dir_fd=directory,
                )
            except FileExistsError:
                continue
            temporary = candidate
            break
        else:
            raise ValueError("could not create a private publication file")
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
            handle.flush()
            if owner:
                user, _, group = owner.partition(":")
                os.fchown(handle.fileno(), -1 if not user else int(user),
                          -1 if not group else int(group))
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
            os.replace(
                temporary, target.name, src_dir_fd=directory, dst_dir_fd=directory,
            )
            temporary = None
        os.fsync(directory)
    finally:
        try:
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)


def render(template_path, env_path, output_path, mode, owner):
    values = parse_env_file(env_path)
    template = json.loads(Path(template_path).read_text())
    rendered = render_node(template, values)
    text = json.dumps(rendered, indent=2) + "\n"
    leftover = re.search(r"\{\{[A-Za-z0-9_:-]+\}\}", text)
    if leftover:
        raise KeyError("Unresolved placeholder " + leftover.group(0))
    publish(output_path, text, mode, owner)


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: render-config.py <template.json> <env-file> <output.json>"
            " [--owner uid:gid] [--mode mode]",
            file=sys.stderr,
        )
        return 2
    mode = 0o600
    owner = ""
    arguments = sys.argv[1:]
    while "--owner" in arguments or "--mode" in arguments:
        if "--owner" in arguments:
            index = arguments.index("--owner")
            owner = arguments[index + 1]
            del arguments[index:index + 2]
        else:
            index = arguments.index("--mode")
            mode = int(arguments[index + 1], 8)
            del arguments[index:index + 2]
    try:
        render(arguments[0], arguments[1], arguments[2], mode, owner)
    except (KeyError, ValueError, OSError) as error:
        print("Could not render configuration: {0}".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
