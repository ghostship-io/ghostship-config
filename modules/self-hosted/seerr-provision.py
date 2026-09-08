"""First-run Seerr setup using its API and the existing Servarr profiles."""

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


def main():
    marker = Path("/srv/apps/seerr/.ghostship-provisioned")
    if marker.exists():
        return
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
        definitions.append((name, settings))

    api("POST", "/auth/plex", {"authToken": os.environ["PLEX_TOKEN"]})
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
        # Released Seerr uses a mutating GET: omitting enable disables libraries.
        enabled = {
            str(library["id"])
            for library in plex.get("libraries", [])
            if library.get("enabled")
        }
        libraries = api(
            "GET",
            "/settings/plex/library",
            params={"sync": "true", "enable": ",".join(sorted(enabled))},
        )
        enabled.update(
            str(library["id"])
            for library in libraries
            if library.get("type") in ("movie", "show")
        )
        libraries = api(
            "GET",
            "/settings/plex/library",
            params={"enable": ",".join(sorted(enabled))},
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
    for name, settings in definitions:
        if not api("GET", f"/settings/{name}"):
            api("POST", f"/settings/{name}/test", settings)
            api("POST", f"/settings/{name}", settings)
    api("POST", "/settings/initialize")
    marker.touch(mode=0o600)
    print("Seerr configured with administrator approval required for ordinary users")


if __name__ == "__main__":
    main()
