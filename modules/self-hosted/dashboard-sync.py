"""Reconcile only registry-owned dashboard entries; preserve unrelated content."""

import json
import runpy
import sys
from pathlib import Path


def homepage_entries(data, apps, previous, resolve):
    owned = set(previous) | {app["name"] for app in apps}
    existing = {}
    groups = {}
    for group in data or []:
        for name, entries in group.items():
            groups.setdefault(name, [])
            for entry in entries:
                for label, settings in entry.items():
                    if label in owned:
                        existing[label] = settings or {}
                    else:
                        groups[name].append({label: settings})
    for app in apps:
        item = existing.get(app["name"], {})
        for key in [
            "href",
            "icon",
            "description",
            "container",
            "server",
            "widget",
        ]:
            item.pop(key, None)
        item.update(
            icon=app["icon"],
            description=app["description"],
            container=app["container"],
            server="chill-penguin",
        )
        if app["hostname"]:
            item["href"] = "https://" + app["hostname"]
        if app["widget"]:
            item["widget"] = {
                key: resolve(value) if isinstance(value, str) else value
                for key, value in app["widget"].items()
            }
            if app["origin"] and "url" not in item["widget"]:
                item["widget"]["url"] = app["origin"]
        groups.setdefault(app["group"], []).append({app["name"]: item})
    return [{name: entries} for name, entries in groups.items() if entries]


def muximux_entries(config, apps, previous):
    owned = set(previous) | {app["name"] for app in apps}
    old = {
        name: dict(config[name]) for name in owned if config.has_section(name)
    }
    for name in owned:
        config.remove_section(name)
    for app in apps:
        mux = app["muximux"]
        if not mux["enable"]:
            continue
        settings = old.get(app["name"], {})
        settings.update(
            name=app["name"],
            url=mux["url"],
            icon=mux["icon"],
            color=mux["color"],
            enabled="true",
            scale="1",
            dd=str(mux["dropdown"]).lower(),
            default=str(app["container"] == "homepage").lower(),
        )
        config[app["name"]] = settings


def main():
    config_script, spec, kind, target, state, *secret_files = sys.argv[1:]
    namespace = runpy.run_path(config_script)
    apps = sorted(
        json.loads(Path(spec).read_text()).values(),
        key=lambda app: (app["order"], app["name"]),
    )
    state_path = Path(state)
    previous = (
        json.loads(state_path.read_text()) if state_path.exists() else []
    )
    path = Path(target)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[]\n"
            if kind == "homepage"
            else "<?php die('Access denied'); ?>\n"
        )
        path.chmod(0o600)
    manager = namespace["ConfigManager"](target)
    manager.load()
    if kind == "homepage":
        resolver = namespace["ValueResolver"](secret_files)
        manager.driver.data = homepage_entries(
            manager.driver.data, apps, previous, resolver.resolve
        )
    elif kind == "muximux":
        muximux_entries(manager.driver.config, apps, previous)
    else:
        raise ValueError("Unknown dashboard")
    manager.driver.dirty = True
    manager.save()
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".new")
    temporary.write_text(json.dumps([app["name"] for app in apps]))
    temporary.chmod(0o600)
    temporary.replace(state_path)


if __name__ == "__main__":
    main()
