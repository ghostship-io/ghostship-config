"""Canary-tested, rollback-safe updates of the agent desktop image.

One run: discover upstream Chrome stable, BladeBro and the webtop base; plan
at most one candidate; build it under the exact tag a switch deploys; prove it
in lab canaries (functional gates on fresh profiles, then profile
compatibility on network-less copies of a read-only /srv snapshot); then
commit it to ghostship-config main, drain active agent runs, snapshot, deploy
through nixos-upgrade.service and verify production, rolling back on failure.

Trust: Chrome versions and checksums come only from an InRelease whose
signature gpgv verifies against the pinned Google Linux signing key (primary
fingerprint checked) and from Packages files whose SHA256 the signed
InRelease lists. BladeBro checksums are the release's published .sha256
assets, which must equal GitHub's own asset digests; the build re-verifies
every download. Webtop is pinned by its manifest-list digest, checked against
the bytes served. Every component soaks for --soak-hours after its upstream
release; nothing is ever downgraded; candidates a gate rejected are never
retried.

Gates never load a retailer site. Cookies are read with
Network.getAllCookies only (never Runtime.enable) and only domains and
counts leave the container.

Canaries run the production image with production's environment and
options, but they bind the desktop API to an address of their own: the
image's default is the production container's address, which exists only in
production's network namespace, and a canary could never bind it.

State: /var/lib/ghostship/agent-desktop-update/state.json.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("AGENT_DESKTOP_UPDATE_STATE", "/var/lib/ghostship/agent-desktop-update"))
REPO_URL = "https://github.com/ghostship-io/ghostship-config.git"
VERSIONS = "containers/agent-desktop/versions.json"
CONTEXT = "containers/agent-desktop"
TAG_EXPR = "modules/self-hosted/agent-desktop-image-tag.nix"
CHROME_REPO = "https://dl.google.com/linux/chrome/deb"
GOOGLE_PRIMARY_FPR = "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
BLADEBRO_API = "https://api.github.com/repos/dondai44423/bladebro/releases?per_page=30"
BLADEBRO_ASSETS = {"arm64": "bladebro-linux-arm64", "amd64": "bladebro-linux-x64"}
WEBTOP_REGISTRY = "https://ghcr.io"
WEBTOP_REPO = "linuxserver/webtop"
ARCHES = ("arm64", "amd64")

PRODUCTION = "agent-desktop"
PRODUCTION_UNIT = "podman-agent-desktop.service"
PRODUCTION_DATA = Path("/srv/apps/agent-desktop/config/agent-desktop")
CANARY = "agent-desktop-canary"
CANARY_IP = "10.89.7.40"
CANARY_NET = "agent_desktop_net"
# The desktop API binds the address it is given, and the image's default is
# the production container's own address on the desktop network. That address
# exists only in production's network namespace, so a canary could never bind
# it. A canary binds loopback instead: an address every container namespace
# has, including the network-less profile canary.
API_BIND_ENV = "AGENT_DESKTOP_API_BIND"
API_PORT_ENV = "AGENT_DESKTOP_API_PORT"
CANARY_API_BIND = "127.0.0.1"
CANARY_API_PORT = 7080
PROFILE_CANARY = "agent-desktop-canary-profiles"
LAB = Path("/srv/lab")
SNAPSHOTS = Path("/srv/.ghostship-snapshots")
SNAPSHOT_PREFIX = "agent-desktop-"
KEEP_SNAPSHOTS = 3
MAINTENANCE_LOCK = "/run/ghostship-maintenance.lock"
TOOLS = "/opt/ghostship-agent-desktop/tools"
PORTS = {"agent": 9222, "personal": 9223}
DRAIN_SECONDS = 30 * 60
COOKIE_HORIZON = 6 * 3600
AUTHOR = "ghostship-agent-desktop-update"
# GitHub token for this process only; it is never written to state.json.
TOKEN: str | None = None
AUTHOR_EMAIL = "ghostship-agent-desktop-update@users.noreply.github.com"
# Chrome's own wording when a profile was written by a newer or incompatible
# build; any of these in a canary's log fails profile compatibility.
PROFILE_ERRORS = re.compile(
    r"profile (?:can ?not|cannot) be used|newer version of (?:google )?chrome|profile error occurred"
    r"|profile_version|failed to (?:read|open) (?:the )?profile",
    re.IGNORECASE)


CANARY_APPARMOR: dict[str, str] = {}


class GateFailure(Exception):
    """A candidate failed a gate: reject it (canary) or roll back (production)."""

    def __init__(self, gate: str, detail: str = ""):
        super().__init__(f"{gate}: {detail}" if detail else gate)
        self.gate, self.detail = gate, detail


class Abort(Exception):
    """Stop this run without judging the candidate (it is tried again later)."""


# --------------------------------------------------------------------------
# Pure policy and parsing
# --------------------------------------------------------------------------

def deb_version_key(version: str) -> tuple:
    """Order Chrome Debian versions ("155.0.8059.84-1"): epoch, upstream, revision."""
    epoch, _, rest = version.rpartition(":") if ":" in version else ("0", "", version)
    upstream, _, revision = rest.rpartition("-") if "-" in rest else (rest, "", "0")
    def parts(text: str) -> tuple:
        return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.~+]", text))
    return (int(epoch or 0), parts(upstream), parts(revision))


def semver_key(version: str) -> tuple:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"not a stable semantic version: {version!r}")
    return tuple(int(part) for part in match.groups())


def chrome_full_version(deb_version: str) -> str:
    return deb_version.rsplit("-", 1)[0]


def validsig_primary(status: str) -> str | None:
    """Primary-key fingerprint of a good signature from gpgv --status-fd output."""
    for line in status.splitlines():
        fields = line.split()
        if fields[:2] == ["[GNUPG:]", "VALIDSIG"] and len(fields) >= 12:
            return fields[11].upper()
    return None


def release_sha256(release: str) -> dict[str, tuple[str, int]]:
    """SHA256 section of a (verified) Release text: path -> (sha256, size)."""
    entries: dict[str, tuple[str, int]] = {}
    in_section = False
    for line in release.splitlines():
        if not line.startswith(" "):
            in_section = line.strip() == "SHA256:"
            continue
        if in_section:
            sha, size, path = line.split()
            entries[path] = (sha.lower(), int(size))
    return entries


def verify_indexed(entries: dict[str, tuple[str, int]], path: str, data: bytes) -> None:
    if path not in entries:
        raise ValueError(f"{path} is not listed in the signed InRelease")
    sha, size = entries[path]
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        raise ValueError(f"{path} does not match the signed InRelease checksum")


def packages_stanza(packages: str, name: str) -> dict[str, str]:
    """Fields of the named package's stanza in a Debian Packages file."""
    for stanza in re.split(r"\n\s*\n", packages):
        fields: dict[str, str] = {}
        key = None
        for line in stanza.splitlines():
            if line[:1] in (" ", "\t") and key:
                fields[key] += "\n" + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                fields[key] = value.strip()
        if fields.get("Package") == name:
            return fields
    raise ValueError(f"package {name} missing from Packages")


def checksum_asset(text: str) -> str:
    """The digest in a published `<sha256>  <file>` checksum asset."""
    digest = text.split()[0].lower() if text.split() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("checksum asset holds no SHA-256 digest")
    return digest


def pick_bladebro(releases: list[dict], current: str, now: float, soak: float,
                  rejected: dict) -> dict | None:
    """Newest stable release that is newer than current, soaked, and not rejected."""
    best = None
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        try:
            key = semver_key(release.get("tag_name", ""))
        except ValueError:
            continue
        version = "%d.%d.%d" % key
        if key <= semver_key(current) or now - parse_time(release["published_at"]) < soak:
            continue
        if candidate_key({"bladebro": {"version": version}}) in rejected:
            continue
        if best is None or key > semver_key(best["tag_name"]):
            best = release
    return best


def parse_time(value: str) -> float:
    """RFC 3339 UTC time; registries write nanoseconds, which Python does not parse."""
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.strip()).replace("Z", "+00:00")
    return dt.datetime.fromisoformat(value).timestamp()


def component_label(name: str, found: dict) -> str:
    return f"{name}={found['digest'] if name == 'base' else found['version']}"


def candidate_key(updates: dict) -> str:
    return "+".join(component_label(name, updates[name]) for name in sorted(updates))


def plan_candidate(current: dict, found: dict, now: float, soak: float, rejected: dict) -> dict:
    """Pick the components of the next candidate (empty: up to date).

    Each found component must be strictly newer than current (never a
    downgrade), at least `soak` seconds past its upstream release and not
    rejected on its own. All such updates form one candidate; when that
    combination was rejected, the first component is tried alone so that one
    bad component cannot hold back the others.
    """
    updates = {}
    for name, item in found.items():
        if item is None or now - item["released"] < soak:
            continue
        if name == "base":
            newer = item["digest"] != current["base"]["digest"] and item["created"] > item.get("current_created", 0)
        elif name == "chrome":
            newer = deb_version_key(item["version"]) > deb_version_key(current["chrome"]["version"])
        else:
            newer = semver_key(item["version"]) > semver_key(current["bladebro"]["version"])
        if newer and candidate_key({name: item}) not in rejected:
            updates[name] = item
    if len(updates) > 1 and candidate_key(updates) in rejected:
        first = sorted(updates)[0]
        updates = {first: updates[first]}
    return updates


def apply_updates(current: dict, updates: dict) -> dict:
    result = json.loads(json.dumps(current))
    if "base" in updates:
        result["base"]["digest"] = updates["base"]["digest"]
    for name in ("chrome", "bladebro"):
        if name in updates:
            result[name] = {"version": updates[name]["version"], "sha256": dict(updates[name]["sha256"])}
    return result


def describe(current: dict, updates: dict) -> str:
    parts = []
    if "chrome" in updates:
        parts.append(f"Chrome {current['chrome']['version']} -> {updates['chrome']['version']}")
    if "bladebro" in updates:
        parts.append(f"BladeBro {current['bladebro']['version']} -> {updates['bladebro']['version']}")
    if "base" in updates:
        parts.append(f"webtop base {current['base']['digest'][:19]} -> {updates['base']['digest'][:19]}")
    return "; ".join(parts)


def drain_blockers(registry: dict[str, float | None], pauses: set[str], now: float) -> list[str]:
    """Wait for live recorded leases and human pauses; malformed records block conservatively."""
    blockers = [f"paused run {marker}" for marker in sorted(pauses)]
    for marker, expires in sorted(registry.items()):
        if type(expires) not in (int, float) or not math.isfinite(expires) or expires > now:
            blockers.append(f"active agent run {marker}")
    return blockers


def cookie_counts(cookies: list[dict], cutoff: float) -> dict[str, int]:
    """Persistent cookies per domain that are still valid at `cutoff`.

    Session cookies do not survive a Chrome restart and short-lived cookies
    may expire between two reads, so neither can show a lost sign-in.
    """
    counts: dict[str, int] = {}
    for cookie in cookies:
        if cookie.get("session") or (cookie.get("expires") or -1) <= cutoff:
            continue
        domain = cookie["domain"].lstrip(".")
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def cookie_shortfall(before: dict[str, int], after: dict[str, int], exact: bool) -> dict[str, list[int]]:
    """Domains whose count dropped (or, when exact, changed at all)."""
    domains = set(before) | (set(after) if exact else set())
    return {d: [before.get(d, 0), after.get(d, 0)] for d in sorted(domains)
            if (after.get(d, 0) != before.get(d, 0) if exact else after.get(d, 0) < before.get(d, 0))}


def rebase_fingerprint(baseline: dict, old_version: str, new_version: str) -> tuple[dict, list[str]]:
    """Baseline signals as the same browser at the candidate's Chrome version.

    A Chrome update must change the version in userAgent and the client
    hints, and nothing else. Within one major version the full version
    string is substituted; a major bump also changes the GREASE brand, so
    uaData is then allowed to differ (userAgent is still compared).
    """
    old_full, new_full = chrome_full_version(old_version), chrome_full_version(new_version)
    old_major, new_major = old_full.split(".")[0], new_full.split(".")[0]
    text = json.dumps(baseline).replace(old_full, new_full)
    text = text.replace(f"Chrome/{old_major}.0.0.0", f"Chrome/{new_major}.0.0.0")
    return json.loads(text), ([] if old_major == new_major else ["uaData"])


def bump_version(version: str) -> str:
    major, minor, patch = (int(part) for part in version.strip().split("."))
    return f"{major}.{minor}.{patch + 1}"


def changelog_entry(changelog: str, version: str, date: str, line: str) -> str:
    head, marker, rest = changelog.partition("\n## ")
    return f"{head.rstrip()}\n\n## [{version}] - {date}\n\n- {line}\n{marker}{rest}" if marker else \
        f"{changelog.rstrip()}\n\n## [{version}] - {date}\n\n- {line}\n"


# Phases persisted in state.json. Only these transitions exist: a candidate
# reaches main only after a passing canary, and an interrupted run resumes
# from the persisted phase instead of starting a new candidate.
TRANSITIONS = {
    ("idle", "candidate"): "canary",
    ("canary", "reject"): "idle",
    ("canary", "pass"): "approved",
    ("approved", "dry-run"): "idle",
    ("approved", "abort"): "idle",
    ("approved", "pushed"): "deploying",
    ("deploying", "deployed"): "verifying",
    ("deploying", "fail"): "rolling-back",
    ("verifying", "pass"): "idle",
    ("verifying", "fail"): "rolling-back",
    ("rolling-back", "restored"): "idle",
    ("rolling-back", "fail"): "rollback-failed",
    ("rollback-failed", "reset"): "idle",
}


def transition(phase: str, event: str) -> str:
    try:
        return TRANSITIONS[(phase, event)]
    except KeyError:
        raise ValueError(f"no transition from {phase} on {event}") from None


def resume_action(phase: str) -> str:
    """What a new run does with the phase an earlier run left behind."""
    if phase in ("idle", "canary", "approved"):
        return "start"          # nothing outward happened; plan afresh
    if phase in ("deploying", "verifying"):
        return "deploy"         # the commit is on main: deploy and verify it
    if phase == "rolling-back":
        return "rollback"
    return "halt"               # rollback-failed needs a person


# --------------------------------------------------------------------------
# Process, network and state helpers
# --------------------------------------------------------------------------

def log(message: str) -> None:
    print(f"[agent-desktop-update] {message}", flush=True)


def run(cmd: list[str], *, check: bool = True, timeout: float = 600, capture: bool = True,
        input: str | None = None, env: dict | None = None, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout, input=input,
                            env=env, cwd=cwd)
    if check and result.returncode != 0:
        tail = ((result.stdout or "") + (result.stderr or ""))[-1500:] if capture else ""
        raise RuntimeError(f"{' '.join(cmd[:4])} exited {result.returncode}: {tail}")
    return result


def http(url: str, headers: dict | None = None, method: str = "GET", timeout: float = 60) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers={"User-Agent": AUTHOR, **(headers or {})}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


def http_json(url: str, headers: dict | None = None) -> object:
    return json.loads(http(url, headers)[0])


def load_state() -> dict:
    try:
        state = json.loads((STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        state = {}
    state.setdefault("phase", "idle")
    state.setdefault("rejected", {})
    state.setdefault("first_seen", {})
    state.setdefault("history", [])
    return state


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, STATE_DIR / "state.json")


def advance(state: dict, event: str, **extra) -> None:
    state["phase"] = transition(state["phase"], event)
    state.update(extra)
    save_state(state)
    log(f"phase -> {state['phase']} ({event})")


def record(state: dict, outcome: str, detail: str = "") -> None:
    state["last_outcome"] = {"outcome": outcome, "detail": detail, "at": now_iso(),
                             "candidate": (state.get("candidate") or {}).get("key")}
    state["history"] = (state["history"] + [state["last_outcome"]])[-30:]
    save_state(state)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def github_token(config: dict) -> str | None:
    path = config.get("github_env")
    if not path:
        return os.environ.get("GITHUB_TOKEN")
    for line in Path(path).read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("TOKEN", "GITHUB_TOKEN"):
            return value.strip().strip("'\"")
    return None


class Notifier:
    def __init__(self, command: str | None, enabled: bool):
        self.command, self.enabled = command, enabled

    def send(self, topic: str, priority: int, title: str, message: str, dedupe: str | None = None,
             incident: bool = False) -> None:
        cmd = [self.command or "ghostship-notify", "--topic", topic, "--priority", str(priority),
               "--source", "agent-desktop-update", "--title", title]
        if dedupe:
            cmd += ["--dedupe", dedupe]
        if incident:
            cmd.append("--incident")
        cmd.append(message)
        if not self.enabled:
            log(f"notify (disabled): {json.dumps(cmd[1:])}")
            return
        run(cmd, timeout=60)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def discover_chrome(keyring: str, state: dict) -> dict | None:
    inrelease, _ = http(f"{CHROME_REPO}/dists/stable/InRelease")
    with tempfile.TemporaryDirectory() as tmp:
        signed = Path(tmp) / "InRelease"
        signed.write_bytes(inrelease)
        result = run(["gpgv", "--keyring", keyring, "--status-fd", "2", "--output", "-", str(signed)],
                     check=False, timeout=60)
    primary = validsig_primary(result.stderr)
    if result.returncode != 0 or primary != GOOGLE_PRIMARY_FPR:
        raise RuntimeError(f"Chrome InRelease signature not verified (primary {primary}); "
                           "refresh the pinned Google key only from an authoritative source")
    # Only the text gpgv verified (its --output) is parsed, never the raw file.
    entries = release_sha256(result.stdout)
    found: dict[str, dict] = {}
    for arch in ARCHES:
        path = f"main/binary-{arch}/Packages"
        data, _ = http(f"{CHROME_REPO}/dists/stable/{path}")
        verify_indexed(entries, path, data)
        found[arch] = packages_stanza(data.decode(), "google-chrome-stable")
    versions = {found[arch]["Version"] for arch in ARCHES}
    if len(versions) != 1:
        log(f"Chrome stable differs between architectures ({sorted(versions)}); waiting")
        return None
    version = versions.pop()
    released = 0.0
    for arch in ARCHES:
        _, headers = http(f"{CHROME_REPO}/{found[arch]['Filename']}", method="HEAD")
        modified = headers.get("last-modified")
        stamp = dt.datetime.strptime(modified, "%a, %d %b %Y %H:%M:%S GMT").replace(
            tzinfo=dt.timezone.utc).timestamp() if modified else first_seen(state, f"chrome={version}")
        released = max(released, stamp)
    return {"version": version, "sha256": {arch: found[arch]["SHA256"].lower() for arch in ARCHES},
            "released": max(released, 0.0)}


def first_seen(state: dict, key: str) -> float:
    return state["first_seen"].setdefault(key, time.time())


def discover_bladebro(token: str | None, current: str, now: float, soak: float, rejected: dict) -> tuple[dict | None, str | None]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases = http_json(BLADEBRO_API, headers)
    stable = [r for r in releases if not r.get("draft") and not r.get("prerelease")]
    latest = max((r["tag_name"].lstrip("v") for r in stable if re.fullmatch(r"v?\d+\.\d+\.\d+", r["tag_name"])),
                 key=semver_key, default=None)
    release = pick_bladebro(releases, current, now, soak, rejected)
    if release is None:
        return None, latest
    assets = {asset["name"]: asset for asset in release["assets"]}
    sha256 = {}
    for arch, name in BLADEBRO_ASSETS.items():
        if name not in assets or f"{name}.sha256" not in assets:
            raise RuntimeError(f"BladeBro {release['tag_name']} lacks {name} or its published checksum")
        published = checksum_asset(http(assets[f"{name}.sha256"]["browser_download_url"])[0].decode())
        github = (assets[name].get("digest") or "").removeprefix("sha256:")
        if github and github != published:
            raise RuntimeError(f"BladeBro {release['tag_name']} {name}: published checksum != GitHub digest")
        sha256[arch] = published
    return {"version": release["tag_name"].lstrip("v"), "sha256": sha256,
            "released": parse_time(release["published_at"])}, latest


def registry_token() -> str:
    reply = http_json(f"{WEBTOP_REGISTRY}/token?scope=repository:{WEBTOP_REPO}:pull")
    return reply["token"]


def manifest(reference: str, token: str, accept: str) -> tuple[bytes, dict]:
    return http(f"{WEBTOP_REGISTRY}/v2/{WEBTOP_REPO}/manifests/{reference}",
                {"Authorization": f"Bearer {token}", "Accept": accept})


INDEX_TYPES = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"
MANIFEST_TYPES = "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"


def image_created(digest: str, token: str) -> float:
    """Creation time of the linux/arm64 image of a manifest list."""
    body, _ = manifest(digest, token, INDEX_TYPES)
    if hashlib.sha256(body).hexdigest() != digest.removeprefix("sha256:"):
        raise RuntimeError(f"registry served a manifest list that does not match {digest}")
    entry = next(m for m in json.loads(body)["manifests"]
                 if m.get("platform", {}).get("architecture") == "arm64")
    image, _ = manifest(entry["digest"], token, MANIFEST_TYPES)
    config_digest = json.loads(image)["config"]["digest"]
    blob, _ = http(f"{WEBTOP_REGISTRY}/v2/{WEBTOP_REPO}/blobs/{config_digest}", {"Authorization": f"Bearer {token}"})
    return parse_time(json.loads(blob)["created"])


def discover_base(current: dict) -> dict:
    image = current["base"]["image"]
    tag = image.rsplit(":", 1)[1]
    if not image.startswith(("lscr.io/linuxserver/webtop:", "ghcr.io/linuxserver/webtop:")):
        raise RuntimeError(f"unsupported base image {image}")
    token = registry_token()
    body, headers = manifest(tag, token, INDEX_TYPES)
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    if headers.get("docker-content-digest") not in (None, digest):
        raise RuntimeError("registry digest header does not match the manifest list served")
    created = image_created(digest, token)
    current_created = image_created(current["base"]["digest"], token) if current["base"]["digest"] != digest else created
    return {"digest": digest, "created": created, "current_created": current_created, "released": created}


def discover(config: dict, state: dict, current: dict, soak: float) -> dict:
    now = time.time()
    found: dict = {"chrome": None, "bladebro": None, "base": None}
    errors = {}
    for name, probe in (("chrome", lambda: discover_chrome(config["keyring"], state)),
                        ("base", lambda: discover_base(current))):
        try:
            found[name] = probe()
        except Exception as exc:  # one broken upstream must not block the others
            errors[name] = str(exc)
    try:
        found["bladebro"], latest = discover_bladebro(github_token(config), current["bladebro"]["version"],
                                                      now, soak, state["rejected"])
        state["bladebro_latest"] = latest
    except Exception as exc:
        errors["bladebro"] = str(exc)
    if errors:
        state["discovery_errors"] = errors
    else:
        state.pop("discovery_errors", None)
    return found


# --------------------------------------------------------------------------
# Repository and image
# --------------------------------------------------------------------------

class Repo:
    def __init__(self, path: Path, url: str, ref: str, token: str | None):
        self.path, self.url, self.ref, self.token = path, url, ref, token

    def git(self, *args: str, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess:
        auth = []
        if self.token and self.url.startswith("https://"):
            basic = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
            auth = ["-c", f"http.extraHeader=Authorization: Basic {basic}"]
        return run(["git", "-c", "safe.directory=*", *auth, "-C", str(self.path), *args], check=check, timeout=timeout)

    def sync(self) -> str:
        """Check out the tip of the ref, clean, and return its commit."""
        if not (self.path / ".git").exists():
            self.path.mkdir(parents=True, exist_ok=True)
            run(["git", "init", "-q", str(self.path)])
            self.git("remote", "add", "origin", self.url)
        self.git("remote", "set-url", "origin", self.url)
        self.git("fetch", "-q", "--no-tags", "origin", self.ref)
        self.git("checkout", "-q", "-f", "-B", "agent-desktop-update", "FETCH_HEAD")
        self.git("clean", "-q", "-ffdx")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def read(self, rel: str) -> str:
        return (self.path / rel).read_text()

    def write(self, rel: str, text: str) -> None:
        (self.path / rel).write_text(text)


def write_versions(repo: Repo, versions: dict) -> None:
    repo.write(VERSIONS, json.dumps(versions, indent=2) + "\n")


def image_tag(repo: Repo) -> tuple[str, str]:
    """The tag a switch to this checkout deploys, and its build context path."""
    path = str(repo.path)
    tag = run(["nix", "eval", "--impure", "--raw", "--expr",
               f"import {path}/{TAG_EXPR} {{ path = {path}/{CONTEXT}; }}"], timeout=300).stdout.strip()
    context = run(["nix", "eval", "--impure", "--raw", "--expr",
                   f'builtins.path {{ path = {path}/{CONTEXT}; name = "ghostship-agent-desktop-context"; }}'],
                  timeout=300).stdout.strip()
    if not tag.startswith("localhost/ghostship-agent-desktop:") or not tag.endswith(context[11:23]):
        raise RuntimeError(f"tag {tag} does not belong to build context {context}")
    return tag, context


def build_args(versions: dict) -> list[str]:
    # Mirrors build-args in agent-desktop.nix.
    return [
        f"--build-arg=BASE_IMAGE={versions['base']['image']}@{versions['base']['digest']}",
        f"--build-arg=CHROME_VERSION={versions['chrome']['version']}",
        f"--build-arg=CHROME_SHA256_ARM64={versions['chrome']['sha256']['arm64']}",
        f"--build-arg=CHROME_SHA256_AMD64={versions['chrome']['sha256']['amd64']}",
        f"--build-arg=BLADEBRO_VERSION={versions['bladebro']['version']}",
        f"--build-arg=BLADEBRO_SHA256_ARM64={versions['bladebro']['sha256']['arm64']}",
        f"--build-arg=BLADEBRO_SHA256_AMD64={versions['bladebro']['sha256']['amd64']}",
    ]


def build_image(tag: str, context: str, versions: dict) -> str:
    if run(["podman", "image", "exists", tag], check=False).returncode != 0:
        log(f"building {tag}")
        run(["podman", "build", "--pull=always", *build_args(versions), "--tag", tag,
             "--file", f"{context}/Containerfile", context], timeout=5400)
    return image_id(tag)


def image_id(reference: str) -> str:
    return run(["podman", "image", "inspect", reference, "--format", "{{.Id}}"]).stdout.strip()


# --------------------------------------------------------------------------
# Containers and gates
# --------------------------------------------------------------------------

COOKIE_SCRIPT = r"""
import base64, json, os, socket, struct, sys, urllib.request

port = int(sys.argv[1])
ws_url = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=10))["webSocketDebuggerUrl"]
path = ws_url.split(str(port), 1)[1]
sock = socket.create_connection(("127.0.0.1", port), timeout=30)
key = base64.b64encode(os.urandom(16)).decode()
sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
stream = sock.makefile("rb")
while stream.readline() not in (b"\r\n", b""):
    pass

def read(n):
    data = stream.read(n)
    if len(data) != n:
        raise SystemExit("DevTools connection closed")
    return data

def send(message):
    payload, mask = json.dumps(message).encode(), os.urandom(4)
    size = len(payload)
    head = bytes([0x81]) + (bytes([0x80 | size]) if size < 126 else
                            bytes([0x80 | 126]) + struct.pack(">H", size) if size < 65536 else
                            bytes([0x80 | 127]) + struct.pack(">Q", size))
    sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

def receive():
    message = b""
    while True:
        first, second = read(2)
        size = second & 0x7F
        size = struct.unpack(">H", read(2))[0] if size == 126 else struct.unpack(">Q", read(8))[0] if size == 127 else size
        data = read(size)
        if first & 0x0F == 8:
            raise SystemExit("DevTools connection closed")
        if first & 0x0F in (0, 1):
            message += data
            if first & 0x80:
                return json.loads(message)

counter = 0
def call(method, params=None, session=None):
    global counter
    counter += 1
    message = {"id": counter, "method": method, "params": params or {}}
    if session:
        message["sessionId"] = session
    send(message)
    while True:
        reply = receive()
        if reply.get("id") == counter:
            if "error" in reply:
                raise SystemExit(f"{method}: {reply['error']}")
            return reply["result"]

# Only Target.* and Network.getAllCookies; the Runtime domain is never enabled.
target = call("Target.createTarget", {"url": "about:blank", "newWindow": True, "background": True})["targetId"]
try:
    session = call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
    cookies = call("Network.getAllCookies", session=session)["cookies"]
finally:
    call("Target.closeTarget", {"targetId": target})
# Domains and lifetimes only: cookie names and values never leave Chrome.
print(json.dumps([{"domain": c["domain"], "session": c.get("session", False),
                   "expires": c.get("expires", -1)} for c in cookies]))
"""


class Desktop:
    """One agent desktop container (canary or production) seen from the host."""

    def __init__(self, name: str, api_bind: str | None = None):
        self.name = name
        # The address the desktop API answers on, when this container was
        # given one (a canary). Production binds its own address and is
        # probed as it was before.
        self.api_bind = api_bind

    def exec(self, *args: str, user: str = "abc", timeout: float = 600, check: bool = False,
             input: str | None = None) -> subprocess.CompletedProcess:
        return run(["podman", "exec", "-i", "-u", user, "-e", "HOME=/config", "-e", "CHROME_ENSURE_TIMEOUT_SECONDS=300",
                    self.name, *args], check=check, timeout=timeout, input=input)

    def api_ready(self) -> bool:
        """The desktop API answers on the address this container was given."""
        if not self.api_bind:
            return True
        url = f"http://{self.api_bind}:{CANARY_API_PORT}/healthz"
        return self.exec("curl", "-fsS", "--max-time", "5", "-o", "/dev/null", url,
                         timeout=30).returncode == 0

    def wait_ready(self, timeout: float = 600) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.exec("curl", "-fsS", "--max-time", "5", "-o", "/dev/null", "http://127.0.0.1:3000/",
                         timeout=30).returncode == 0 and \
                    self.exec("test", "-r", "/config/agent-desktop/session-env", timeout=30).returncode == 0 and \
                    self.api_ready():
                return
            time.sleep(5)
        raise GateFailure("startup", f"{self.name} did not become ready in {int(timeout)}s")

    def gate(self, name: str, *args: str, timeout: float = 3600) -> str:
        log(f"{self.name}: gate {name}")
        result = self.exec(*args, timeout=timeout)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            raise GateFailure(name, output.strip()[-600:])
        return output

    def tool(self, name: str, script: str, *args: str, timeout: float = 3600) -> str:
        return self.gate(name, "python3", f"{TOOLS}/{script}", *args, timeout=timeout)

    def ensure_chrome(self, identity: str) -> None:
        self.gate(f"chrome-ensure {identity}", "chrome-ensure", identity, timeout=400)

    def cookies(self, identity: str) -> list[dict]:
        result = self.exec("python3", "-", str(PORTS[identity]), input=COOKIE_SCRIPT, timeout=120)
        if result.returncode != 0:
            raise GateFailure(f"cookies {identity}", (result.stderr or "")[-400:])
        return json.loads(result.stdout)

    def versions(self) -> dict:
        chrome = self.exec("dpkg-query", "-W", "-f=${Version}", "google-chrome-stable", user="root").stdout.strip()
        blade = self.exec("/usr/local/bin/bladebro", "--version", user="root", timeout=60).stdout
        match = re.search(r"v(\d+\.\d+\.\d+)", blade or "")
        return {"chrome": chrome, "bladebro": match.group(1) if match else ""}


def check_versions(desktop: Desktop, versions: dict) -> None:
    seen = desktop.versions()
    want = {"chrome": versions["chrome"]["version"], "bladebro": versions["bladebro"]["version"]}
    if seen != want:
        raise GateFailure("versions", f"running {seen}, expected {want}")


def remove_container(name: str) -> None:
    # Chrome loses recent cookies on SIGTERM or compositor death: stop it the
    # way production's preStop does before the container goes, so the next
    # image opens a cleanly closed profile.
    run(["podman", "exec", name, "/opt/ghostship-agent-desktop/chrome-stop-all"], check=False, timeout=180)
    run(["podman", "stop", "-t", "60", name], check=False, timeout=180)
    run(["podman", "rm", "-f", name], check=False, timeout=120)


def apparmor_option(options: list[str]) -> tuple[list[str], str]:
    """Production's AppArmor profile when it is loaded, else Podman's default."""
    wanted = next((o.split("=", 2)[2] for o in options if o.startswith("--security-opt=apparmor=")), None)
    try:
        loaded = Path("/sys/kernel/security/apparmor/profiles").read_text()
    except OSError:
        loaded = ""
    wanted = wanted or "ghostship-agent-desktop"
    if re.search(rf"^{re.escape(wanted)} \(", loaded, re.MULTILINE):
        return [f"--security-opt=apparmor={wanted}"], wanted
    return [], "container-default"


def start_canary(config: dict, name: str, image: str, data: Path, network: list[str]) -> Desktop:
    remove_container(name)
    (data / "config").mkdir(parents=True, exist_ok=True)
    os.chown(data, 3000, 3000)
    os.chown(data / "config", 3000, 3000)
    options = [o for o in config.get("canary_options", []) if not o.startswith("--security-opt=apparmor=")]
    security, profile = apparmor_option(config.get("canary_options", []))
    env = []
    for key, value in sorted(config.get("canary_environment", {}).items()):
        if key in (API_BIND_ENV, API_PORT_ENV):
            continue  # the canary binds its own address, never production's
        env += ["-e", f"{key}={value}"]
    env += ["-e", f"{API_BIND_ENV}={CANARY_API_BIND}", "-e", f"{API_PORT_ENV}={CANARY_API_PORT}"]
    run(["podman", "run", "-d", "--name", name, "--label", "ghostship.lab=1",
         "--label", "ghostship.agent-desktop-update=canary", *security, *network, *env,
         "-e", f"AGENT_DESKTOP_API_TOKEN={secrets.token_hex(16)}",
         "-v", f"{data / 'config'}:/config:rw", *options, image], timeout=300)
    log(f"started {name} from {image[:12]} (apparmor {profile})")
    CANARY_APPARMOR[name] = profile
    desktop = Desktop(name, api_bind=CANARY_API_BIND)
    desktop.wait_ready()
    return desktop


def ensure_fingerprint_baseline(config: dict, accepted_image: str, accepted_versions: dict) -> Path:
    """The accepted image's signals, recorded once on a fresh profile.

    The accepted image is the build of main's current versions.json (what
    production runs). Failing to record it is a pipeline error, not a
    verdict on the candidate.
    """
    baseline = STATE_DIR / "fingerprint-baseline.json"
    if baseline.exists():
        return baseline
    log("no fingerprint baseline; recording one from the accepted image on a fresh profile")
    data = LAB / CANARY
    try:
        shutil.rmtree(data, ignore_errors=True)
        desktop = start_canary(config, CANARY, accepted_image, data, [f"--network={CANARY_NET}:ip={CANARY_IP}"])
        desktop.ensure_chrome("agent")
        dump = desktop.tool("fingerprint dump", "bench_fingerprint.py", "--dump", str(PORTS["agent"]), timeout=300)
    except GateFailure as failure:
        raise RuntimeError(f"recording the fingerprint baseline failed: {failure}") from None
    finally:
        remove_container(CANARY)
        shutil.rmtree(data, ignore_errors=True)
    write_baseline(json.loads(dump), accepted_versions["chrome"]["version"], accepted_image)
    return baseline


def write_baseline(signals: dict, chrome_version: str, image: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "fingerprint-baseline.json").write_text(json.dumps(signals, indent=1, sort_keys=True) + "\n")
    (STATE_DIR / "fingerprint-baseline.meta.json").write_text(json.dumps(
        {"chrome_version": chrome_version, "image": image, "recorded": now_iso()}) + "\n")


def fingerprint_gate(desktop: Desktop, versions: dict) -> dict:
    meta = json.loads((STATE_DIR / "fingerprint-baseline.meta.json").read_text())
    baseline = json.loads((STATE_DIR / "fingerprint-baseline.json").read_text())
    rebased, allow = rebase_fingerprint(baseline, meta["chrome_version"], versions["chrome"]["version"])
    staged = "/tmp/ghostship-fingerprint-baseline.json"
    desktop.exec("sh", "-c", f"cat > {staged}", input=json.dumps(rebased), check=True)
    args = ["--baseline", staged, "--candidate", str(PORTS["agent"])]
    if allow:
        args += ["--allow", ",".join(allow)]
    desktop.tool("fingerprint", "bench_fingerprint.py", *args, timeout=300)
    dump = desktop.tool("fingerprint dump", "bench_fingerprint.py", "--dump", str(PORTS["agent"]), timeout=300)
    return json.loads(dump)


def functional_canary(config: dict, image: str, versions: dict, simulate: str | None) -> dict:
    """Gates on fresh profiles. Returns the candidate's fingerprint signals."""
    data = LAB / CANARY
    shutil.rmtree(data, ignore_errors=True)
    try:
        desktop = start_canary(config, CANARY, image, data, [f"--network={CANARY_NET}:ip={CANARY_IP}"])
        if simulate == "canary":
            raise GateFailure("simulated-failure", "--simulate-failure canary")
        check_versions(desktop, versions)
        desktop.ensure_chrome("agent")
        signals = fingerprint_gate(desktop, versions)
        desktop.tool("bench_input 8x250", "bench_input.py", "--port", str(PORTS["agent"]),
                     "--agents", "8", "--rounds", "250")
        desktop.tool("bench_bladebro 4x20", "bench_bladebro.py", "--port", str(PORTS["agent"]),
                     "--workers", "4", "--rounds", "20")
        desktop.tool("check_cdp_regression", "check_cdp_regression.py", timeout=1800)
        desktop.tool("bench_botcheck", "bench_botcheck.py", "--port", str(PORTS["agent"]), timeout=900)
        viewer_gate(desktop)
        return signals
    finally:
        remove_container(CANARY)
        shutil.rmtree(data, ignore_errors=True)


def viewer_gate(desktop: Desktop) -> None:
    """The viewer is up behind nginx and refuses a request without an Access token."""
    code = desktop.exec("curl", "-sS", "--max-time", "10", "-o", "/dev/null", "-w", "%{http_code}",
                        "http://127.0.0.1:3000/api/runs", timeout=60).stdout.strip()
    if code != "401":
        raise GateFailure("viewer /api/runs", f"HTTP {code} without an Access token (expected 401)")


def profile_canary(config: dict, snapshot: Path, current_image: str, candidate_image: str) -> dict:
    """Open copies of the real profiles with the current image, then with the candidate.

    The copies come from the read-only snapshot and run with --network none,
    so no refresh token on a copy can rotate and sign the person out. Every
    domain's cookie count after the candidate opened the profile must equal
    the count the current image produced on the same copy.
    """
    data = LAB / PROFILE_CANARY
    shutil.rmtree(data, ignore_errors=True)
    chrome = data / "config/agent-desktop/chrome"
    chrome.mkdir(parents=True)
    for path in (data, data / "config", data / "config/agent-desktop", chrome):
        os.chown(path, 3000, 3000)
    source = snapshot / "apps/agent-desktop/config/agent-desktop/chrome"
    counts: dict = {}
    cutoff = time.time() + COOKIE_HORIZON  # one cutoff, so expiry between the two runs cannot differ
    try:
        for identity in PORTS:
            run(["cp", "-a", "--reflink=auto", str(source / identity), str(chrome / identity)], timeout=1800)
        for label, image in (("current", current_image), ("candidate", candidate_image)):
            desktop = start_canary(config, PROFILE_CANARY, image, data, ["--network=none"])
            counts[label] = {}
            for identity in PORTS:
                desktop.ensure_chrome(identity)
                time.sleep(5)
                counts[label][identity] = cookie_counts(desktop.cookies(identity), cutoff)
            logs = run(["podman", "logs", PROFILE_CANARY], check=False, timeout=120)
            match = PROFILE_ERRORS.search((logs.stdout or "") + (logs.stderr or ""))
            remove_container(PROFILE_CANARY)
            if match:
                raise GateFailure("profile-compatibility", f"{label} image logged: {match.group(0)}")
        for identity in PORTS:
            diff = cookie_shortfall(counts["current"][identity], counts["candidate"][identity], exact=True)
            if diff:
                raise GateFailure("profile-cookies", f"{identity}: per-domain counts changed {dict(list(diff.items())[:10])}")
        return {identity: sum(counts["candidate"][identity].values()) for identity in PORTS}
    finally:
        remove_container(PROFILE_CANARY)
        shutil.rmtree(data, ignore_errors=True)


# --------------------------------------------------------------------------
# Snapshot, drain, deploy and rollback
# --------------------------------------------------------------------------

def take_snapshot() -> Path:
    SNAPSHOTS.mkdir(mode=0o700, exist_ok=True)
    target = SNAPSHOTS / (SNAPSHOT_PREFIX + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    with open(MAINTENANCE_LOCK, "w") as lock:
        deadline = time.time() + 300
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    raise Abort("maintenance lock busy for 5 minutes; snapshot skipped") from None
                time.sleep(5)
        run(["btrfs", "subvolume", "snapshot", "-r", "/srv", str(target)], timeout=300)
    existing = sorted(p for p in SNAPSHOTS.iterdir() if p.name.startswith(SNAPSHOT_PREFIX))
    for old in existing[:-KEEP_SNAPSHOTS]:
        run(["btrfs", "subvolume", "delete", str(old)], check=False, timeout=600)
    log(f"snapshot {target}")
    return target


def drain(notifier: Notifier, wait: float = DRAIN_SECONDS) -> None:
    production = Desktop(PRODUCTION)
    deadline = time.time() + wait
    while True:
        runs = PRODUCTION_DATA / "runs"
        registry = {}
        for path in runs.glob("*.json") if runs.is_dir() else []:
            try:
                registry[path.stem] = json.loads(path.read_text()).get("expires_at")
            except (OSError, ValueError, AttributeError):
                registry[path.stem] = None
        pauses = {p.name[:-6] for p in runs.glob("*.pause")} if runs.is_dir() else set()
        blockers = drain_blockers(registry, pauses, time.time())
        if not blockers:
            return
        if time.time() >= deadline:
            notifier.send("operations", 3, "Agent desktop update restarting during active work",
                          f"Drain timed out after {int(wait / 60)} min; restarting anyway: {', '.join(blockers[:5])}",
                          dedupe="agent-desktop-update-forced-drain")
            return
        log(f"waiting for {', '.join(blockers[:5])}")
        time.sleep(30)


def production_cookie_counts() -> dict:
    production = Desktop(PRODUCTION)
    counts = {}
    cutoff = time.time() + COOKIE_HORIZON
    for identity in PORTS:
        production.ensure_chrome(identity)
        counts[identity] = cookie_counts(production.cookies(identity), cutoff)
    return counts


def deploy() -> None:
    log("starting nixos-upgrade.service")
    result = run(["systemctl", "start", "nixos-upgrade.service"], check=False, timeout=4 * 3600)
    if result.returncode != 0:
        # A switch also exits non-zero when an unrelated unit fails to start.
        # Whether the desktop deployed is decided by verify_production (the
        # running image must be the tested candidate), not by this exit code.
        log(f"nixos-upgrade exited {result.returncode}; verifying the desktop itself")
    run(["systemctl", "start", PRODUCTION_UNIT], check=False, timeout=1200)


def wait_healthy(timeout: float = 900) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = run(["podman", "inspect", PRODUCTION, "--format", "{{.State.Health.Status}}"],
                     check=False, timeout=30).stdout.strip()
        if status == "healthy":
            return
        time.sleep(10)
    raise GateFailure("production health", f"{PRODUCTION} not healthy after {int(timeout)}s")


def verify_production(candidate: dict, simulate: str | None) -> None:
    wait_healthy()
    running = run(["podman", "inspect", PRODUCTION, "--format", "{{.Image}}"]).stdout.strip()
    if running != candidate["image_id"]:
        raise GateFailure("production image", f"running {running[:12]}, candidate {candidate['image_id'][:12]}")
    production = Desktop(PRODUCTION)
    production.wait_ready()
    check_versions(production, candidate["versions"])
    if simulate == "postdeploy":
        raise GateFailure("simulated-failure", "--simulate-failure postdeploy")
    production.ensure_chrome("agent")
    production.tool("bench_input 2x25", "bench_input.py", "--port", str(PORTS["agent"]), "--agents", "2", "--rounds", "25")
    production.tool("check_cdp_regression", "check_cdp_regression.py", timeout=1800)
    production.tool("bench_botcheck", "bench_botcheck.py", "--port", str(PORTS["agent"]), timeout=900)
    after = production_cookie_counts()
    for identity, before in candidate.get("pre_cookies", {}).items():
        lost = cookie_shortfall(before, after.get(identity, {}), exact=False)
        if lost:
            raise GateFailure("production cookies", f"{identity}: {dict(list(lost.items())[:10])}")
    # The promoted image is the new accepted fingerprint.
    candidate["fingerprint"] = json.loads(production.tool(
        "fingerprint dump", "bench_fingerprint.py", "--dump", str(PORTS["agent"]), timeout=300))


def commit_change(repo: Repo, base_commit: str, versions: dict, expected_tag: str, message: str,
                  changelog_line: str, push: bool) -> str:
    """Commit versions.json with a VERSION bump and CHANGELOG line on main; push.

    Rebuilds the commit on the newest main when main moved, provided the
    image build context still yields the tested tag.
    """
    for attempt in range(3):
        head = repo.sync()
        if head != base_commit:
            write_versions(repo, versions)
            tag, _ = image_tag(repo)
            if tag != expected_tag:
                raise Abort(f"main changed the desktop build context since {base_commit[:10]}; re-run the canary")
        write_versions(repo, versions)
        version = bump_version(repo.read("VERSION"))
        repo.write("VERSION", version + "\n")
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        repo.write("CHANGELOG.md", changelog_entry(repo.read("CHANGELOG.md"), version, today, changelog_line))
        repo.git("add", VERSIONS, "VERSION", "CHANGELOG.md")
        repo.git("-c", f"user.name={AUTHOR}", "-c", f"user.email={AUTHOR_EMAIL}", "commit", "-q", "-m", message)
        commit = repo.git("rev-parse", "HEAD").stdout.strip()
        if not push:
            return commit
        if repo.git("push", "-q", "origin", "HEAD:refs/heads/main", check=False).returncode == 0:
            log(f"pushed {commit[:10]} to main")
            return commit
        log(f"push rejected; retrying on the new main (attempt {attempt + 2})")
    raise Abort("could not push to main after 3 attempts")


def rollback(state: dict, notifier: Notifier, reason: str) -> None:
    candidate = state["candidate"]
    previous = candidate["previous_versions"]
    repo = Repo(STATE_DIR / "repo", REPO_URL, "main", TOKEN)
    head = repo.sync()
    current = json.loads(repo.read(VERSIONS))
    if current != previous:
        # A forward commit restoring versions.json (instead of git revert)
        # keeps VERSION and CHANGELOG monotonic when main moved meanwhile.
        commit_change(repo, head, previous, image_tag_for(repo, previous),
                      f"revert: chore(agent-desktop): update {candidate['summary']}",
                      f"Agent desktop: rolled back {candidate['summary']} after a failed production check "
                      f"({reason[:120]}).", push=True)
    deploy()
    if candidate.get("profiles_opened") and "chrome" in candidate["updates"]:
        snapshot = Path(candidate["snapshot"])
        log(f"restoring Chrome profiles from {snapshot}")
        run(["systemctl", "stop", PRODUCTION_UNIT], timeout=600)
        for identity in PORTS:
            source = snapshot / f"apps/agent-desktop/config/agent-desktop/chrome/{identity}/"
            # Trailing slashes on both sides: copy the profile's contents, not a
            # nested chrome/<identity>/<identity> directory (Path drops them).
            run(["rsync", "-a", "--delete", str(source) + "/", str(PRODUCTION_DATA / "chrome" / identity) + "/"],
                timeout=3600)
        run(["systemctl", "start", PRODUCTION_UNIT], timeout=1200)
    wait_healthy()
    running = run(["podman", "inspect", PRODUCTION, "--format", "{{.Image}}"]).stdout.strip()
    if running != candidate["previous_image_id"]:
        raise RuntimeError(f"rollback runs {running[:12]}, expected {candidate['previous_image_id'][:12]}")
    Desktop(PRODUCTION).wait_ready()
    check_versions(Desktop(PRODUCTION), previous)


def image_tag_for(repo: Repo, versions: dict) -> str:
    write_versions(repo, versions)
    tag, _ = image_tag(repo)
    repo.git("checkout", "-q", "--", VERSIONS)
    return tag


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def production_image() -> str:
    return run(["podman", "inspect", PRODUCTION, "--format", "{{.Image}}"]).stdout.strip()


def reject(state: dict, notifier: Notifier, failure: GateFailure, dry_run: bool) -> None:
    candidate = state["candidate"]
    if failure.gate != "simulated-failure":
        state["rejected"][candidate["key"]] = {"at": now_iso(), "gate": failure.gate, "detail": failure.detail[:400]}
    advance(state, "reject")
    record(state, "rejected", str(failure)[:400])
    notifier.send("operations", 3, f"Agent desktop update rejected: {candidate['summary']}",
                  f"Gate {failure.gate} failed{' (dry run)' if dry_run else ''}: {failure.detail[:600]}",
                  dedupe=f"agent-desktop-update-reject-{candidate['key']}")
    image = candidate.get("image_id")
    if failure.gate != "simulated-failure" and image and image != candidate["previous_image_id"] and not run(
            ["podman", "ps", "-a", "--filter", f"ancestor={image}", "-q"], check=False).stdout.strip():
        run(["podman", "rmi", candidate["tag"]], check=False)


def promote(state: dict, notifier: Notifier, repo: Repo, simulate: str | None) -> None:
    candidate = state["candidate"]
    commit = commit_change(repo, candidate["base_commit"], candidate["versions"], candidate["tag"],
                           f"chore(agent-desktop): update {candidate['summary']}",
                           f"Agent desktop: {candidate['summary']} (canary-tested by ghostship-agent-desktop-update).",
                           push=True)
    candidate["commit"] = commit
    advance(state, "pushed", candidate=candidate)
    deploy_and_verify(state, notifier, simulate)


def deploy_and_verify(state: dict, notifier: Notifier, simulate: str | None) -> None:
    candidate = state["candidate"]
    try:
        # A resumed run keeps the first snapshot and cookie baseline: by then the
        # candidate may already have opened (and migrated) the profiles.
        if not candidate.get("snapshot"):
            drain(notifier)
            candidate["pre_cookies"] = production_cookie_counts()
            candidate["snapshot"] = str(take_snapshot())
            save_state(state)
        candidate["profiles_opened"] = True  # the new Chrome opens them as soon as it starts
        deploy()  # idempotent: a resumed run re-applies the same main
        advance(state, "deployed", candidate=candidate)
        verify_production(candidate, simulate)
    except (GateFailure, RuntimeError, subprocess.TimeoutExpired) as exc:
        reason = str(exc)
        log(f"production check failed: {reason}")
        advance(state, "fail")
        try:
            rollback(state, notifier, reason)
        except Exception as rollback_exc:
            advance(state, "fail")
            record(state, "rollback-failed", f"{reason}; rollback: {rollback_exc}")
            notifier.send("operations", 5, "Agent desktop rollback failed",
                          f"{candidate['summary']}: {reason[:300]}; rollback: {str(rollback_exc)[:300]}", incident=True)
            raise
        advance(state, "restored")
        record(state, "rolled-back", reason[:400])
        state["rejected"][candidate["key"]] = {"at": now_iso(), "gate": "production", "detail": reason[:400]}
        save_state(state)
        notifier.send("operations", 4, f"Agent desktop update rolled back: {candidate['summary']}",
                      f"Production check failed: {reason[:500]}. Main restored, previous image running"
                      f"{', profiles restored from ' + candidate['snapshot'] if candidate.get('profiles_opened') and 'chrome' in candidate['updates'] else ''}.",
                      incident=True)
        return
    if candidate.get("fingerprint"):
        write_baseline(candidate["fingerprint"], candidate["versions"]["chrome"]["version"], candidate["image_id"])
    advance(state, "pass")
    record(state, "promoted", candidate["summary"])
    notifier.send("informational", 2, f"Agent desktop updated: {candidate['summary']}",
                  f"Canary and production checks passed; image {candidate['tag']}.")


def discovery_status(state: dict) -> int:
    """Fail the unit (and so notify) while any upstream could not be checked."""
    for name, error in state.get("discovery_errors", {}).items():
        log(f"discovery of {name} failed: {error}")
    return 1 if state.get("discovery_errors") else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", help="JSON settings written by the NixOS module")
    parser.add_argument("--discover-only", action="store_true", help="print upstream candidates and exit")
    parser.add_argument("--dry-run", action="store_true", help="stop before committing or touching production")
    parser.add_argument("--simulate-failure", choices=("canary", "postdeploy"), help="force that gate to fail")
    parser.add_argument("--soak-hours", type=float, default=24.0)
    parser.add_argument("--components", default="base,chrome,bladebro",
                        help="comma-separated components this run may update")
    parser.add_argument("--repo", default=REPO_URL, help="ghostship-config remote (a local path for lab runs)")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--notify", choices=("auto", "on", "off"), default="auto",
                        help="auto: off for --dry-run, on otherwise")
    parser.add_argument("--reset", action="store_true", help="clear a rollback-failed halt after manual repair")
    args = parser.parse_args(argv)
    if args.dry_run is False and args.repo != REPO_URL:
        parser.error("--repo is for --dry-run lab runs; promotion always uses ghostship-config main")
    config = json.loads(Path(args.config).read_text()) if args.config else {}
    notifier = Notifier(config.get("notify"), args.notify == "on" or (args.notify == "auto" and not args.dry_run))
    soak = args.soak_hours * 3600

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "run.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another update run is in progress")
            return 1
        global TOKEN
        state = load_state()
        TOKEN = token = github_token(config)
        action = resume_action(state["phase"])
        if args.reset and state["phase"] == "rollback-failed":
            advance(state, "reset")
            action = "start"
        if action == "halt":
            log("halted after a failed rollback; repair production, then run with --reset")
            return 1
        if action in ("deploy", "rollback") and not args.discover_only:
            if args.dry_run:
                log(f"an interrupted promotion is in phase {state['phase']}; refusing a dry run")
                return 1
            if action == "deploy":
                state["phase"] = "deploying"
                deploy_and_verify(state, notifier, args.simulate_failure)
            else:
                rollback(state, notifier, "resumed after interruption")
                advance(state, "restored")
            return 0
        state["phase"] = "idle"

        repo = Repo(STATE_DIR / ("repo" if args.repo == REPO_URL else "repo-lab"), args.repo, args.ref, token)
        base_commit = repo.sync()
        current = json.loads(repo.read(VERSIONS))
        found = discover(config, state, current, soak)
        allowed = set(args.components.split(","))
        found = {name: (item if name in allowed else None) for name, item in found.items()}
        updates = plan_candidate(current, found, time.time(), soak, state["rejected"])
        save_state(state)
        if args.discover_only:
            for item in found.values():
                if item:
                    item["age_hours"] = round((time.time() - item["released"]) / 3600, 1)
            print(json.dumps({"current": current, "found": found, "bladebro_latest": state.get("bladebro_latest"),
                              "errors": state.get("discovery_errors", {}), "soak_hours": args.soak_hours,
                              "candidate": {name: found[name] for name in updates}}, indent=1, default=str))
            return 0
        if not updates and args.simulate_failure is None:
            record(state, "up-to-date", json.dumps(state.get("discovery_errors", {}))[:400])
            log("up to date")
            return discovery_status(state)
        if not updates:
            updates, summary, key = {}, "simulated candidate (current versions)", "simulated"
        else:
            summary, key = describe(current, updates), candidate_key(updates)
        # The accepted image: main's current versions.json, built exactly as a
        # switch would (production already runs it when main is deployed).
        accepted_tag, accepted_context = image_tag(repo)
        versions = apply_updates(current, updates)
        write_versions(repo, versions)
        tag, context = image_tag(repo)
        previous = production_image()
        candidate = {"key": key, "summary": summary, "updates": updates, "versions": versions, "tag": tag,
                     "previous_versions": current, "previous_image_id": previous, "base_commit": base_commit}
        advance(state, "candidate", candidate=candidate)
        log(f"candidate {summary} as {tag}")
        try:
            candidate["image_id"] = build_image(tag, context, versions)
            save_state(state)
            accepted = build_image(accepted_tag, accepted_context, current)
            ensure_fingerprint_baseline(config, accepted, current)
            candidate["fingerprint"] = functional_canary(config, candidate["image_id"], versions, args.simulate_failure)
            snapshot = take_snapshot()
            candidate["profile_cookies"] = profile_canary(config, snapshot, accepted, candidate["image_id"])
        except GateFailure as failure:
            log(f"candidate rejected: {failure}")
            reject(state, notifier, failure, args.dry_run)
            return discovery_status(state)
        except Exception:
            state["phase"] = "idle"
            save_state(state)
            raise
        candidate["canary_apparmor"] = dict(CANARY_APPARMOR)
        advance(state, "pass", candidate=candidate)
        if args.dry_run:
            advance(state, "dry-run")
            record(state, "approved-dry-run", summary)
            log(f"dry run: {summary} passed every canary gate; not promoting")
            return discovery_status(state)
        try:
            promote(state, notifier, Repo(STATE_DIR / "repo", REPO_URL, "main", token), args.simulate_failure)
        except Abort as abort:
            if state["phase"] == "approved":
                advance(state, "abort")
            record(state, "aborted", str(abort))
            log(f"aborted: {abort}")
        return discovery_status(state)


if __name__ == "__main__":
    sys.exit(main())
