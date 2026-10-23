"""Reject runtime backends outside the approved Podman contract.

Registry/image names, upstream API schemas and dockerTools image builders are
formats/interfaces, not runtime installations. Inspect executable configuration,
not vendor API documentation or historical release notes.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

PATTERNS = (
    r"\bdockerd\b",
    r"\bdocker(?:-desktop)?\.(?:enable|package)\b",
    r"\bvirtualisation\s*\.\s*docker\b",
    r"\bpkgs\s*\.\s*docker(?!Tools\b)[\w-]*",
    r"(?m)^\s*docker(?:-compose)?\s*$",
    r"(?:^|[\s\[\"'])docker(?:-compose)?(?:[\s\]\"']|$)",
    r"docker\.sock\b",
    r"\bdocker(?:Compat|Socket(?:\.enable)?)\s*=",
    r"(?:apt-get|apt|apk|dnf|yum).*\b(?:install|add)\b.*\bdocker(?:\.io|[\w-]*)",
    r"\b(?:users\.)?(?:groups|users)\s*\.\s*\"?(?:t3code-)?docker\b",
    r"\bt3code-docker\b",
)
CODE_SUFFIXES = {".nix", ".py", ".sh", ".yaml", ".yml", ".toml", ".service", ".socket"}


def findings(root):
    result = []
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or ".git" in path.parts
            or path.resolve() == Path(__file__).resolve()
        ):
            continue
        relative = path.relative_to(root).as_posix()
        # WSL2 Docker Desktop is an owner-required Windows integration.
        if relative.startswith("modules/wsl/"):
            continue
        if relative == "tests/t3code-podman.nix":
            continue
        if path.suffix not in CODE_SUFFIXES and path.name not in {
            "Containerfile",
            "Dockerfile",
        }:
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            # Comments describe the prohibition; they do not install a runtime.
            code = line.split("#", 1)[0]
            negative_reads = {
                "assertion = !(config.virtualisation.docker.enable or false);",
                "!(config.virtualisation.podman.dockerCompat or false)",
                "&& !(config.virtualisation.podman.dockerSocket.enable or false);",
            }
            if (
                relative == "modules/self-hosted/podman-only.nix"
                and code.strip() in negative_reads
            ):
                continue
            if re.fullmatch(
                r"RUN ! command -v docker && ! command -v dockerd", code.strip()
            ):
                continue
            if any(re.search(pattern, code) for pattern in PATTERNS):
                result.append(
                    f"{path.relative_to(root)}:{number}: forbidden container runtime"
                )
    return result


class RuntimePolicy(unittest.TestCase):
    def test_runtime_installations_are_rejected_and_image_builders_retained(self):
        bad = [
            "environment.systemPackages = with pkgs; [ docker ];",
            "environment.systemPackages = [ pkgs.docker ];",
            "environment.systemPackages = [ pkgs.docker-compose ];",
            "virtualisation.docker.enable = true;",
            "virtualisation.podman.dockerCompat = true;",
            "virtualisation.podman.dockerSocket.enable = true;",
            "RUN apt-get install -y docker.io",
            "wsl.docker-desktop.enable = true;",
            "users.groups.docker = {};",
            "users.users.t3code-docker = {};",
            "ExecStart=dockerd --host=unix:///run/docker.sock",
            "run: docker build .",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "runtime.nix"
            for code in bad:
                with self.subTest(code=code):
                    source.write_text(code)
                    self.assertTrue(findings(root))
            source.write_text(
                'image = pkgs.dockerTools.buildLayeredImage {};\nimageName = "docker.io/library/alpine";\nExecStart=podman system service;'
            )
            self.assertEqual(findings(root), [])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        unittest.main(argv=[sys.argv[0]])
    else:
        found = findings(
            Path(sys.argv[1])
            if len(sys.argv) > 1
            else Path(__file__).resolve().parents[1]
        )
        print("\n".join(found) if found else "Podman runtime policy passed")
        raise SystemExit(bool(found))
