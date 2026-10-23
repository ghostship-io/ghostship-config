"""Write the trimmed models.dev catalog T3 Code's OpenCode reads.

OpenCode 2 ignores provider whitelist/blacklist in its v2 model API, so T3
Code points OPENCODE_MODELS_PATH at this file instead. It is rebuilt from
OpenCode's own models.dev cache, so newly released models appear on the next
run and models age out without a maintained list. Only the enabled
subscription providers are trimmed; every other provider passes through,
less the retired ones. OpenRouter left T3 Code and stays in the free pool,
which reads the untrimmed cache, so its provider is dropped here and from
OpenCode's config, and a configured default naming it is repointed.
"""

import argparse
import datetime
import json
import os
import pathlib
import sys
import tempfile

TRIMMED = ("ollama-cloud", "opencode-go")
RETIRED = ("openrouter",)
REPLACEMENTS = {
    "model": "ollama-cloud/deepseek-v4.1-flash",
    "small_model": "ollama-cloud/minimax-m3.1-flash",
}
MAX_AGE_DAYS = 183


def log(message):
    print(f"[opencode-model-catalog] {message}", file=sys.stderr, flush=True)


def pinned(config_path):
    """The configured default and small models, kept regardless of age."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {config[key] for key in ("model", "small_model") if isinstance(config.get(key), str)}


def keep(provider, model, cutoff, pins):
    if f"{provider}/{model.get('id')}" in pins:
        return True
    if model.get("status") == "deprecated" or not model.get("tool_call"):
        return False
    return str(model.get("release_date") or "") >= cutoff


def trim(catalog, today, pins):
    cutoff = (today - datetime.timedelta(days=MAX_AGE_DAYS)).isoformat()
    result = {provider: entry for provider, entry in catalog.items() if provider not in RETIRED}
    for provider in TRIMMED:
        entry = catalog.get(provider)
        if not isinstance(entry, dict) or not isinstance(entry.get("models"), dict):
            continue
        models = {key: model for key, model in entry["models"].items()
                  if isinstance(model, dict) and keep(provider, model, cutoff, pins)}
        result[provider] = {**entry, "models": models}
    return result


def retire(config):
    """The same config with OpenRouter and any default naming it removed."""
    result = dict(config)
    providers = result.get("enabled_providers")
    if isinstance(providers, list):
        result["enabled_providers"] = [name for name in providers if name not in RETIRED]
    provider = result.get("provider")
    if isinstance(provider, dict) and any(name in provider for name in RETIRED):
        result["provider"] = {name: entry for name, entry in provider.items() if name not in RETIRED}
    for key, replacement in REPLACEMENTS.items():
        value = result.get(key)
        if isinstance(value, str) and value.split("/", 1)[0] in RETIRED:
            result[key] = replacement
    return result


def config_edited(config_path):
    """Retire the provider from OpenCode's config; return whether it changed."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as error:
        log(f"config unavailable ({error}); kept {config_path}")
        return False
    try:
        config = json.loads(text)
    except ValueError as error:
        log(f"config is not JSON ({error}); kept {config_path}")
        return False
    if not isinstance(config, dict):
        log(f"config is not an object; kept {config_path}")
        return False
    updated = retire(config)
    if updated == config:
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".opencode.", dir=config_path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, config_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    log(f"retired {', '.join(RETIRED)} from {config_path}")
    return True


def main(argv=None):
    home = pathlib.Path.home()
    cache = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    config = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    state = pathlib.Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=pathlib.Path, default=cache / "opencode/models.json")
    parser.add_argument("--config", type=pathlib.Path, default=config / "opencode/opencode.jsonc")
    parser.add_argument("--output", type=pathlib.Path, default=state / "t3code-opencode/models.json")
    args = parser.parse_args(argv)
    try:
        catalog = json.loads(args.source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        # Keep the previous trimmed catalog; OpenCode refreshes its cache hourly.
        log(f"catalog unavailable ({error}); kept {args.output}")
        return 0
    if not isinstance(catalog, dict) or not all(isinstance(v, dict) for v in catalog.values()):
        log("catalog is not a provider map; kept the previous output")
        return 0
    trimmed = trim(catalog, datetime.date.today(), pinned(args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".models.", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(trimmed, handle, separators=(",", ":"))
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    counts = ", ".join(f"{p} {len(trimmed[p]['models'])}/{len(catalog[p]['models'])}"
                       for p in TRIMMED if p in trimmed and p in catalog)
    log(f"wrote {args.output}: {counts}")
    config_edited(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
