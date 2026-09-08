#!/usr/bin/env python3
"""Expose the existing Ghostship catalog to all T3 Code providers."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def install(home, source, package, preferences):
    """Plan first; never replace unrelated user files or provider settings."""
    state = home / ".local/state/t3code-shared-agents"
    manifest = state / "links.json"
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    links = {}
    normalized = {}
    commands = {}
    skills = sorted((source / "skills").glob("*/SKILL.md"))
    if not skills:
        raise ValueError(f"No shared skills found under {source / 'skills'}")
    if package is not None and not (package / "bin").is_dir():
        raise ValueError(f"No packaged commands found under {package / 'bin'}")

    for skill in skills:
        content = skill.read_text()
        if not content.startswith("---\n"):
            raise ValueError(f"Missing skill frontmatter: {skill}")
        metadata = content.split("---", 2)[1]
        if not re.search(r"^name:", metadata, re.MULTILINE):
            # Antigravity permits an omitted name; Codex/OpenCode require it.
            # Keep the source intact and provide a compatible installed copy.
            normalized[skill.parent.name] = content.replace(
                "---\n", f"---\nname: {skill.parent.name}\n", 1
            )
        canonical = home / ".agents/skills" / skill.parent.name
        links[canonical] = (
            state / "skills" / skill.parent.name
            if skill.parent.name in normalized
            else skill.parent.resolve()
        )
        # Codex and OpenCode natively read ~/.agents/skills. Antigravity ACP
        # 1.1.1 reads this cross-surface Gemini directory before CLI skills.
        links[home / ".gemini/config/skills" / skill.parent.name] = canonical

    # Include user-selected additions installed in the shared catalog, while
    # excluding retired links owned by our previous source inventory.
    selected = []
    for skill in sorted((home / ".agents/skills").glob("*/SKILL.md")):
        canonical = skill.parent
        if canonical not in links and str(canonical) not in previous:
            links[home / ".gemini/config/skills" / canonical.name] = canonical
            selected.append(canonical.name)

    if package is not None:
        for command in sorted((package / "bin").iterdir()):
            if command.is_file() and os.access(command, os.X_OK):
                wrapper = state / "bin" / command.name
                # The container exports native libraries for npm providers.
                # Nix packages carry their own RPATHs; mixing libc versions
                # makes even their shell interpreters segfault before startup.
                commands[wrapper] = (
                    "#!/bin/sh\nunset LD_LIBRARY_PATH\n"
                    + (
                        'export AGENT_BROWSER_ENGINE="${AGENT_BROWSER_ENGINE:-chrome}"\n'
                        'if [ -z "${AGENT_BROWSER_EXECUTABLE_PATH:-}" ]; then\n'
                        "  export AGENT_BROWSER_EXECUTABLE_PATH="
                        + shlex.quote(
                            str(home / ".local/state/t3code-agent-browser/bin/chromium")
                        )
                        + "\nfi\n"
                        if command.name == "agent-browser"
                        else ""
                    )
                    + "exec "
                    + shlex.quote(str(command))
                    + ' "$@"\n'
                )
                links[home / ".local/bin" / command.name] = wrapper
    else:
        links.update(
            {
                Path(k): Path(v)
                for k, v in previous.items()
                if Path(k).parent == home / ".local/bin"
            }
        )

    guidance = state / "AGENTS.md"
    for native in [
        ".codex/AGENTS.md",
        ".config/opencode/AGENTS.md",
        ".gemini/GEMINI.md",
    ]:
        links[home / native] = guidance

    conflicts = []
    for dest, target in links.items():
        if not dest.exists() and not dest.is_symlink():
            continue
        if dest.is_symlink():
            current = os.readlink(dest)
            if current == str(target) or previous.get(str(dest)) == current:
                continue
            # Migrate only the two source launchers owned by T3 Code setup.
            if dest.name in ("agent", "ghostship-cloakbrowser") and current == str(
                home / "tools/bin" / dest.name
            ):
                continue
        conflicts.append(str(dest))
    if conflicts:
        raise ValueError(
            "Existing unmanaged files would be replaced: " + ", ".join(conflicts)
        )

    state.mkdir(parents=True, exist_ok=True)
    for wrapper, content in commands.items():
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        temporary = wrapper.with_suffix(".tmp")
        temporary.write_text(content)
        temporary.chmod(0o755)
        temporary.replace(wrapper)
    for name, content in normalized.items():
        directory = state / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(content)
        for resource in (source / "skills" / name).iterdir():
            dest = directory / resource.name
            if (
                resource.name != "SKILL.md"
                and not dest.exists()
                and not dest.is_symlink()
            ):
                dest.symlink_to(resource.resolve())
    text = (
        preferences.read_text()
        + f"""

## T3 Code container

- The shared user home is `{home}`. Workspaces live under `/workspace`.
- All providers share skills in `{home}/.agents/skills` and packaged commands
  in `{home}/.local/bin`. Read the matching SKILL.md before using a workflow.
- Shared tool and skill sources live at `{source}`. Use `agent`, `agent pp`,
  `agent-browser`, `bw`, and the installed Printing Press clients as needed.
- Older shared skills describe OpenChamber's home, helpers, or activation.
  Here use the current home and `t3code-user-units`, `t3code-tunnel`, and
  `t3code-apply-config`. Do not activate the OpenChamber Home Manager profile.
- Use repo-local Nix shells for project dependencies. Provider authentication
  and plugins remain managed independently by each provider.
"""
    )
    temporary = guidance.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(guidance)
    for dest, target in links.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            if os.readlink(dest) == str(target):
                continue
            dest.unlink()
        dest.symlink_to(target)
    # Prune only links still matching this installer's previous manifest.
    for name, target in previous.items():
        dest = Path(name)
        if (
            dest.is_relative_to(home)
            and dest not in links
            and dest.is_symlink()
            and os.readlink(dest) == target
        ):
            dest.unlink()
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({str(k): str(v) for k, v in links.items()}, indent=2) + "\n"
    )
    temporary.replace(manifest)
    return len(skills) + len(selected), sum(
        dest.parent == home / ".local/bin" for dest in links
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("/workspace/ghostship-agent")
    )
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--tools-package",
        type=Path,
        help="Use an already built package instead of building it",
    )
    parser.add_argument(
        "--skills-only",
        action="store_true",
        help="Refresh skills and guidance without building tools",
    )
    parser.add_argument(
        "--preferences",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "home/config/AGENTS.md",
    )
    args = parser.parse_args()
    home, source = args.home.resolve(), args.source.resolve()
    state = home / ".local/state/t3code-shared-agents"
    launcher = home / ".local/bin/t3code-shared-agents"
    hook = home / ".t3code-container/hooks/bootstrap.d/50-shared-agents"
    marker = "# Managed by nixos-config setup-container-agents.py"
    for path in (launcher, hook):
        if (path.exists() or path.is_symlink()) and (
            path.is_symlink() or marker not in path.read_text()
        ):
            raise ValueError(f"Existing unmanaged launcher would be replaced: {path}")
    package = args.tools_package
    if package is None and not args.skills_only:
        package = home / ".local/state/t3code-agent-tools-package"
        package.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "nix",
                "build",
                "--no-write-lock-file",
                "-L",
                f"{source}#default",
                "--out-link",
                str(package),
            ],
            check=True,
        )
        # Chrome for Testing has no Linux ARM64 build. Use the repository's
        # packaged Chromium instead of invoking a distro installer in Nix.
        repository = Path(__file__).resolve().parents[1]
        if not (repository / "flake.nix").exists():
            repository = Path("/workspace/nixos-config")
        subprocess.run(
            [
                "nix",
                "build",
                "--no-write-lock-file",
                "-L",
                f"{repository}#container-browser",
                "--out-link",
                str(home / ".local/state/t3code-agent-browser"),
            ],
            check=True,
        )
    skills, commands = install(
        home, source, package.absolute() if package else None, args.preferences
    )
    # Keep the live setup independent of a disposable development worktree.
    files = {
        state / "setup.py": Path(__file__).read_text(),
        state / "preferences.md": args.preferences.read_text(),
        launcher: "#!/bin/sh\n"
        + marker
        + "\nunset LD_LIBRARY_PATH\nexec "
        + shlex.join(
            [
                sys.executable,
                str(state / "setup.py"),
                "--home",
                str(home),
                "--source",
                str(source),
                "--preferences",
                str(state / "preferences.md"),
            ]
        )
        + ' "$@"\n',
        hook: "#!/bin/sh\n"
        + marker
        + "\n"
        + shlex.quote(str(launcher))
        + " --skills-only || printf 'warning: shared skills need attention\\n' >&2\n",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(content)
        temporary.chmod(0o755 if path in (launcher, hook) else 0o644)
        temporary.replace(path)
    print(f"Shared {skills} skills and {commands} commands across T3 Code providers.")


if __name__ == "__main__":
    main()
