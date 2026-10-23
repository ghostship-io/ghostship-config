"""Reconcile Seerr wiring while preserving valid user-selected profiles."""

import os
import subprocess
from pathlib import Path

import requests


def address(container, port):
    ip = subprocess.check_output(
        [
            "podman",
            "inspect",
            container,
            "--format",
            '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}',
        ],
        text=True,
    ).strip()
    return f"http://{ip}:{port}"


def reconcile_instance(api, name, desired, profiles, roots):
    path = f"/settings/{name}"
    instances = api("GET", path)
    if not instances:
        api("POST", path + "/test", desired)
        api("POST", path, desired)
        instances = api("GET", path)
    matches = [item for item in instances if item.get("name") == desired["name"]]
    if len(matches) != 1:
        raise RuntimeError(f"Ambiguous managed {name} instance; preserve settings")
    current = matches[0]
    if current.get("hostname") != name or current.get("port") != desired["port"]:
        raise RuntimeError(f"Managed {name} endpoint changed; preserve settings")
    if not any(root["path"] == current.get("activeDirectory") for root in roots):
        raise RuntimeError(f"Managed {name} root is missing; preserve settings")
    updated = dict(current, apiKey=desired["apiKey"])
    for prefix in ("active", "activeAnime"):
        id_key, name_key = prefix + "ProfileId", prefix + "ProfileName"
        profile_id = current.get(id_key)
        if profile_id in (None, 0) and prefix == "activeAnime":
            continue
        if not any(profile["id"] == profile_id for profile in profiles):
            replacements = [p for p in profiles if p["name"] == current.get(name_key)]
            if len(replacements) != 1:
                raise RuntimeError(
                    f"Managed {name} profile is ambiguous; preserve settings"
                )
            updated[id_key] = replacements[0]["id"]
    if updated != current:
        api("POST", path + "/test", updated)
        api("PUT", f"{path}/{current['id']}", updated)
        saved = next(
            (item for item in api("GET", path) if item["id"] == current["id"]), {}
        )
        if any(saved.get(key) != value for key, value in updated.items()):
            raise RuntimeError(f"Managed {name} update did not persist")


def reconcile_notifications(api):
    path = "/settings/notifications/ntfy"
    current = api("GET", path)
    options = current.get("options", {})
    # Adopt the unconfigured default; leave an independently configured agent alone.
    if options.get("topic") and (
        options.get("url") != "http://ntfy:8080" or options["topic"] != "operations"
    ):
        return
    desired = {
        **current,
        "enabled": True,
        # Pending, approved, available, failed, declined and automatic approval.
        "types": 2 | 4 | 8 | 16 | 64 | 128,
        "options": {
            **options,
            "url": "http://ntfy:8080",
            "topic": "operations",
            "priority": 3,
            "locale": "en",
            "authMethodUsernamePassword": True,
            "authMethodToken": False,
            "username": "publisher",
            "password": os.environ["NTFY_PUBLISH_PASSWORD"],
        },
    }
    if desired != current:
        api("POST", path + "/test", desired)
        api("POST", path, desired)
        if api("GET", path) != desired:
            raise RuntimeError("Seerr notification update did not persist")


def main():
    marker = Path("/srv/apps/seerr/.ghostship-provisioned")
    first_run = not marker.exists()
    session = requests.Session()
    base = address("seerr", 5055) + "/api/v1"

    def api(method, path, data=None, params=None):
        response = session.request(
            method, base + path, json=data, params=params, timeout=30
        )
        if not response.ok:
            raise requests.HTTPError(
                f"Seerr {method} {path} failed ({response.status_code})",
                response=response,
            )
        return response.json() if response.content else None

    # Validate the existing profiles/roots before changing Seerr settings.
    definitions = []
    for name, port, root in [
        ("sonarr", 8989, "/tv"),
        ("radarr", 7878, "/movies"),
    ]:
        key = os.environ[f"{name.upper()}_API_KEY"]
        url = address(name, port) + "/api/v3"
        responses = [
            requests.get(url + path, headers={"X-Api-Key": key}, timeout=20)
            for path in ["/qualityprofile", "/rootfolder"]
        ]
        if any(not response.ok for response in responses):
            raise RuntimeError(f"Cannot read existing {name} configuration")
        profiles, roots = [response.json() for response in responses]
        profile = next((p for p in profiles if p["name"] == "Optimal"), None)
        if profile is None and len(profiles) == 1:
            profile = profiles[0]
        if profile is None or not any(r["path"] == root for r in roots):
            raise RuntimeError(
                f"Existing {name} profile/root is ambiguous; preserve it and resolve setup"
            )
        settings = {
            "name": f"Ghostship {name}",
            "hostname": name,
            "port": port,
            "apiKey": key,
            "useSsl": False,
            "baseUrl": "",
            "activeProfileId": profile["id"],
            "activeProfileName": profile["name"],
            "activeDirectory": root,
            "tags": [],
            "is4k": False,
            "isDefault": True,
            "syncEnabled": True,
            "preventSearch": False,
            "tagRequests": False,
            "overrideRule": [],
        }
        if name == "sonarr":
            settings.update(
                seriesType="standard",
                animeSeriesType="standard",
                enableSeasonFolders=True,
                monitorNewItems="all",
            )
        else:
            settings["minimumAvailability"] = "released"
        definitions.append((name, settings, profiles, roots))

    api("POST", "/auth/plex", {"authToken": os.environ["PLEX_TOKEN"]})
    if first_run:
        initialize_plex(api)
    for name, settings, profiles, roots in definitions:
        reconcile_instance(api, name, settings, profiles, roots)
    reconcile_notifications(api)
    if first_run:
        api("POST", "/settings/initialize")
        marker.touch(mode=0o600)
    print(
        "Seerr integration profiles, roots, Plex authentication and notifications verified"
    )


def initialize_plex(api):
    api(
        "POST",
        "/settings/main",
        {
            "applicationUrl": "https://requests.ghostship.io",
            # REQUEST only: no AUTO_APPROVE bits. Existing Plex users need explicit import.
            "defaultPermissions": 32,
            "newPlexLogin": False,
        },
    )
    plex = api("GET", "/settings/plex")
    if not plex.get("ip"):
        api(
            "POST",
            "/settings/plex",
            {"ip": "plex", "port": 32400, "useSsl": False},
        )
    try:
        libraries = api("POST", "/settings/plex/library/sync")
    except requests.HTTPError as error:
        if error.response.status_code != 404:
            raise
        # Released Seerr uses a mutating GET: omitting enable disables libraries,
        # but its validator rejects an empty value. Omit only an empty selection.
        enabled = {
            str(library["id"])
            for library in plex.get("libraries", [])
            if library.get("enabled")
        }
        sync_params = {"sync": "true"}
        if enabled:
            sync_params["enable"] = ",".join(sorted(enabled))
        libraries = api(
            "GET",
            "/settings/plex/library",
            params=sync_params,
        )
        enabled.update(
            str(library["id"])
            for library in libraries
            if library.get("type") in ("movie", "show")
        )
        libraries = api(
            "GET",
            "/settings/plex/library",
            params={"enable": ",".join(sorted(enabled))} if enabled else None,
        )
        if not enabled.issubset(
            {str(library["id"]) for library in libraries if library.get("enabled")}
        ):
            raise RuntimeError("Seerr did not enable the selected Plex libraries")
    else:
        for library in libraries:
            if library.get("type") in ("movie", "show"):
                api(
                    "PUT",
                    f"/settings/plex/library/{library['id']}",
                    {"enabled": True},
                )


if __name__ == "__main__":
    main()
