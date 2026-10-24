"""Expose Command Code's Provider API through T3 Code's OpenCode.

Runs before the T3 Code server starts. Two things happen there:

* the two Command Code providers are merged into OpenCode's own config, so
  OpenCode serves the same GOAT models the vendor's API serves. The catalog
  comes from the vendor's ``GET /provider/v1/models`` with the projected key.
  Every model the vendor lists for a provider's route is kept; nothing here
  filters by age, price, quality or name. A refresh that fails keeps the last
  good list. The API key is never written to the config: OpenCode resolves
  ``{env:COMMAND_CODE_API_KEY}`` from the projected secret at request time,
  and every request carries the vendor's ``x-cmd-zdr: 1`` zero-retention
  header. This process reads only that one variable from the projection file,
  with a plain value parse; it never sources the file or runs a shell.
* the retired ACP ``commandCode`` instance is removed from T3 Code's settings
  only after both replacement providers carry a catalog, so a broken or
  unreachable configuration never leaves T3 without any Command Code route.

The script is idempotent and never rewrites a file whose content is unchanged.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_URL = "https://api.commandcode.ai/provider/v1"
KEY_ENV = "COMMAND_CODE_API_KEY"
TIMEOUT_SECONDS = 10
USER_AGENT = "ghostship-t3code-command-code/1"
SECRETS_FILE = Path("/run/secrets/t3code.env")
MANAGED_INSTANCE = "commandCode"
MANAGED_INSTANCE_CONFIG = {"source": "local", "commandArgs": ["acp"]}


def log(message):
    print(f"[command-code] {message}", file=sys.stderr, flush=True)


def read_json(path):
    """A plain JSON file, or None when it is absent or not an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log(f"{path.name} is not readable JSON ({type(error).__name__})")
        return None
    return value if isinstance(value, dict) else None


def strip_jsonc(text):
    """JSONC text as JSON: comments and trailing commas outside strings.

    OpenCode's config is JSONC, so an owner comment or a trailing comma is a
    valid file, not a broken one. Nothing else is changed.
    """
    out = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    stripped = "".join(out)
    result = []
    index = 0
    in_string = False
    escaped = False
    while index < len(stripped):
        char = stripped[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            following = index + 1
            while following < len(stripped) and stripped[following] in " \t\r\n":
                following += 1
            if following < len(stripped) and stripped[following] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)


def read_config(path):
    """An OpenCode config object, parsing valid JSONC, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        log(f"{path.name} is not readable ({type(error).__name__}); left unchanged")
        return None
    try:
        value = json.loads(strip_jsonc(text))
    except ValueError:
        log(f"{path.name} is not valid JSONC; left unchanged")
        return None
    return value if isinstance(value, dict) else None


def replacement_ready(config, fragment):
    """True when every managed provider carries a nonempty catalog."""
    providers = config.get("providers")
    if not isinstance(providers, dict):
        return False
    for name in fragment["providers"]:
        entry = providers.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("models"), dict) or not entry["models"]:
            return False
    return True


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".command-code-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch_models(key, base_url=BASE_URL, timeout=TIMEOUT_SECONDS):
    """The vendor's model list, or None when the API cannot be read."""
    request = urllib.request.Request(
        f"{base_url}/models",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except Exception as error:  # network, TLS, HTTP status, malformed body
        log(f"model list unavailable ({type(error).__name__}); kept the previous list")
        return None
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or not entries:
        log("model list was empty; kept the previous list")
        return None
    return entries


def model_catalog(entries, routes):
    """Each provider's models, from the vendor's names and route support."""
    catalog = {provider: {} for provider in routes}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        endpoints = entry.get("supported_endpoints")
        endpoints = endpoints if isinstance(endpoints, list) else []
        model = {"name": str(entry.get("name") or identifier)}
        context = entry.get("context_length")
        if isinstance(context, int) and context > 0:
            model["limit"] = {"context": context}
        for provider, endpoint in routes.items():
            if endpoint in endpoints:
                catalog[provider][identifier] = model
    return {provider: models for provider, models in catalog.items() if models}


def merge(config, fragment, models):
    """The config with both providers and their model lists, everything else kept."""
    result = json.loads(json.dumps(config))
    # OpenCode 2's native provider map. The legacy singular map rejects the
    # `limit` field, and this map carries both provider settings and headers.
    existing = result.get("providers")
    existing = existing if isinstance(existing, dict) else {}
    providers = dict(existing)
    added = []
    for name, spec in fragment["providers"].items():
        current = providers.get(name)
        current = current if isinstance(current, dict) else {}
        fresh = models.get(name)
        previous = current.get("models")
        chosen = fresh or (previous if isinstance(previous, dict) and previous else None)
        if not chosen:
            # Without a catalog there is nothing to offer; leave an existing
            # entry exactly as the last good run wrote it.
            if current:
                added.append(name)
            continue
        entry = json.loads(json.dumps(spec))
        entry["models"] = chosen
        providers[name] = entry
        added.append(name)
    if providers != existing:
        result["providers"] = providers
    enabled = result.get("enabled_providers")
    if isinstance(enabled, list):
        result["enabled_providers"] = enabled + [
            name for name in added if name not in enabled
        ]
    return result


def managed_acp(instance):
    if not isinstance(instance, dict) or instance.get("driver") != "acpRegistry":
        return False
    config = instance.get("config")
    if not isinstance(config, dict):
        return False
    command = config.get("commandPath")
    return (
        isinstance(command, str)
        and command.endswith("/.local/bin/cmd")
        and all(config.get(key) == value for key, value in MANAGED_INSTANCE_CONFIG.items())
    )


def retire(settings_path):
    """Remove the managed ACP instance; return whether the file changed."""
    data = read_json(settings_path)
    if data is None:
        return False
    instances = data.get("providerInstances")
    if not isinstance(instances, dict) or not managed_acp(instances.get(MANAGED_INSTANCE)):
        return False
    del instances[MANAGED_INSTANCE]
    atomic_json(settings_path, data)
    log("retired the managed ACP commandCode instance")
    return True


def parse_env(text):
    """KEY=VALUE pairs from a projection file, without a shell.

    Quoted values use shlex so the projection's own quoting is undone; shlex
    only parses, it never expands or executes, and the caller reads one name.
    """
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            try:
                parts = shlex.split(value, comments=False)
            except ValueError:
                continue
            if len(parts) != 1:
                continue
            value = parts[0]
        values[name.strip()] = value
    return values


def projected_key(path):
    """Only COMMAND_CODE_API_KEY from the projection, or an empty string."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return parse_env(text).get(KEY_ENV, "").strip()


def config_path(home, environ=os.environ):
    configured = environ.get("XDG_CONFIG_HOME")
    directory = Path(configured) if configured else home / ".config"
    directory = directory / "opencode"
    for name in ("opencode.jsonc", "opencode.json"):
        candidate = directory / name
        if candidate.exists():
            return candidate
    return directory / "opencode.jsonc"


def main(home=None, source=ROOT, key=None, fetch=fetch_models, environ=None,
         secrets_file=SECRETS_FILE):
    environ = environ if environ is not None else os.environ
    home = Path(home or Path.home())
    fragment = json.loads((Path(source) / "provider.json").read_text(encoding="utf-8"))
    # Only this one variable is read, from the projection file itself. The
    # file is never sourced, so no other secret reaches this process and no
    # value is ever evaluated by a shell.
    key = (key if key is not None else projected_key(secrets_file)).strip()
    entries = None
    if key:
        try:
            entries = fetch(key)
        except Exception as error:  # a fetch seam that cannot answer
            log(f"model list unavailable ({type(error).__name__}); kept the previous list")
    if key and entries is None:
        log("no catalog this start")
    models = model_catalog(entries, fragment["routes"]) if entries else {}

    path = config_path(home, environ)
    if path.exists():
        config = read_config(path)
        if config is None:
            # A broken owner file stays byte for byte as it was. The dead ACP
            # instance stays too: removing it without a replacement would
            # leave T3 with no Command Code route at all.
            log("kept the managed ACP instance; the replacement route was not configured")
            return 0
    else:
        config = {"$schema": "https://opencode.ai/config.json"}
    updated = merge(config, fragment, models)
    if updated != config:
        atomic_json(path, updated)
        log(f"configured {', '.join(sorted(fragment['providers']))} providers")
    if replacement_ready(updated, fragment):
        retire(home / ".t3/userdata/settings.json")
    else:
        log("replacement route has no catalog; kept the managed ACP instance")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Optional startup step: T3 still starts, and the previous config stays.
        log(f"configuration unavailable ({type(error).__name__}); T3 starts without it")
        raise SystemExit(1)
