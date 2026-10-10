"""Provision through Kuma's v2 Socket.IO API; preserve existing named entries."""

import json
import os
import secrets
import sys
import threading
from pathlib import Path

import socketio
from engineio.payload import Payload

# Kuma emits heartbeat/stat packets for every monitor before acknowledging login.
# Its populated fleet can exceed Engine.IO's default 16-packet polling limit.
Payload.max_decode_packets = 256

RETIRED_APP_MONITORS = {
    "Ghostship OpenChamber": "OpenChamber",
    "Ghostship Synara": "Synara",
}


def is_retired_app_monitor(monitor, current_app_names):
    app_name = RETIRED_APP_MONITORS.get(monitor["name"])
    return (
        app_name is not None
        and app_name not in current_app_names
        and monitor["type"] == "http"
    )


def is_owned_stale_container_monitor(monitor, current_names, previous_tokens):
    prefix = "Ghostship container "
    expected = {prefix + name for name in current_names}
    return (
        monitor["name"].startswith(prefix)
        and monitor["name"] not in expected
        and monitor["type"] == "push"
        and monitor.get("pushToken") in previous_tokens
    )


def write_push_tokens(path, pushes):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(pushes))
    temporary.chmod(0o600)
    temporary.replace(path)


def enforce_access_only_auth(call, password):
    settings = call("getSettings")["data"]
    if settings.get("disableAuth") is True:
        return
    settings["disableAuth"] = True
    call("setSettings", (settings, password))


def reconcile_ntfy_notification(call, notifications, password):
    existing = next(
        (n for n in notifications if n["name"] == "Ghostship ntfy"), None
    )
    settings = {
        "name": "Ghostship ntfy",
        "type": "ntfy",
        "isDefault": False,
        "ntfyserverurl": "http://ntfy:8080",
        "ntfytopic": "operations",
        "ntfyAuthenticationMethod": "usernamePassword",
        "ntfyusername": "publisher",
        "ntfypassword": password,
        "ntfyPriority": 3,
    }
    if existing is not None and json.loads(existing["config"])["type"] != "ntfy":
        raise RuntimeError("Managed ntfy notification changed type")
    notification_id = existing["id"] if existing is not None else None
    return call("addNotification", (settings, notification_id))["id"]


def main():
    client = socketio.Client(request_timeout=15, reconnection=False)
    monitors = {}
    notifications = []
    monitor_event = threading.Event()
    notification_event = threading.Event()

    @client.on("monitorList")
    def monitor_list(data):
        nonlocal monitors
        monitors = dict(data)
        monitor_event.set()

    @client.on("notificationList")
    def notification_list(data):
        notifications[:] = data
        notification_event.set()

    def call(event, data=None):
        result = client.call(event, data, timeout=20)
        if not result or not result.get("ok"):
            # API messages can contain user input; keep credential errors redacted.
            raise RuntimeError(f"Kuma {event} failed; inspect service status")
        return result

    client.connect(os.environ["KUMA_URL"], transports=["polling"])
    try:
        # Query setup state explicitly; startup load can delay the setup event.
        if client.call("needSetup", timeout=20):
            call("setup", ("the owner", os.environ["KUMA_PASSWORD"]))
        # Kuma establishes an automatic session on connection when auth is off.
        settings_result = client.call("getSettings", timeout=20)
        if not settings_result or not settings_result.get("ok"):
            call(
                "login",
                {"username": "the owner", "password": os.environ["KUMA_PASSWORD"]},
            )
        enforce_access_only_auth(call, os.environ["KUMA_PASSWORD"])
        call("getMonitorList")
        if not monitor_event.wait(15) or not notification_event.wait(15):
            raise RuntimeError("Kuma did not provide its configuration lists")
        notification_id = reconcile_ntfy_notification(
            call, notifications, os.environ["NTFY_PUBLISH_PASSWORD"]
        )
        registry = json.loads(Path(sys.argv[1]).read_text())
        current_app_names = {app["name"] for app in registry.values()}
        for monitor in monitors.values():
            if is_retired_app_monitor(monitor, current_app_names):
                call("deleteMonitor", (monitor["id"], False))
        endpoints = {
            app["name"]: app["origin"].rstrip("/") + app["healthPath"]
            for app in registry.values()
            if app["healthPath"] is not None
        }
        names = {m["name"] for m in monitors.values()}
        for name, url in endpoints.items():
            existing = next(
                (
                    monitor
                    for monitor in monitors.values()
                    if monitor["name"] == f"Ghostship {name}"
                ),
                None,
            )
            if existing is not None:
                if existing["type"] != "http":
                    raise RuntimeError(f"Managed HTTP monitor {name} changed type")
                if existing.get("url") != url:
                    monitor = call("getMonitor", existing["id"])["monitor"]
                    monitor["url"] = url
                    call("editMonitor", monitor)
                continue
            call(
                "add",
                {
                    "name": f"Ghostship {name}",
                    "type": "http",
                    "conditions": [],
                    "url": url,
                    "interval": 60,
                    "retryInterval": 60,
                    "maxretries": 2,
                    "timeout": 15,
                    "method": "GET",
                    "maxredirects": 0,
                    "accepted_statuscodes": ["200-299"],
                    "notificationIDList": {str(notification_id): True},
                    "resendInterval": 0,
                    "ignoreTls": False,
                    "upsideDown": False,
                },
            )
        for name, host, port in [
            ("RomM DB", "romm-db", 3306),
            ("Grimmory DB", "grimmory-db", 3306),
            ("NZBGet", "nzbget", 5001),
            ("Tautulli", "tautulli", 8181),
        ]:
            if f"Ghostship {name}" not in names:
                call(
                    "add",
                    {
                        "name": f"Ghostship {name}",
                        "type": "port",
                        "conditions": [],
                        "hostname": host,
                        "port": port,
                        "interval": 60,
                        "retryInterval": 60,
                        "maxretries": 2,
                        "accepted_statuscodes": ["200-299"],
                        "notificationIDList": {str(notification_id): True},
                    },
                )
        pushes = {"containers": {}}
        for name in ["backup", "updates"]:
            monitor_name = f"Ghostship {name} heartbeat"
            existing = next(
                (m for m in monitors.values() if m["name"] == monitor_name),
                None,
            )
            if existing:
                monitor = call("getMonitor", existing["id"])["monitor"]
                pushes[name] = monitor["pushToken"]
            else:
                token = secrets.token_hex(10)
                call(
                    "add",
                    {
                        "name": monitor_name,
                        "type": "push",
                        "conditions": [],
                        "pushToken": token,
                        "interval": 600,
                        "retryInterval": 60,
                        "maxretries": 1,
                        "accepted_statuscodes": ["200-299"],
                        "notificationIDList": {str(notification_id): True},
                    },
                )
                pushes[name] = token
        container_names = sorted(
            {app["container"] for app in registry.values()}
        )
        path = Path("/var/lib/ghostship-monitoring/push.json")
        previous_pushes = json.loads(path.read_text()) if path.exists() else {}
        previous_container_tokens = previous_pushes.get("containers", {})
        previous_tokens = set(previous_container_tokens.values())
        container_monitor_names = {
            f"Ghostship container {name}" for name in container_names
        }
        for listed_monitor in monitors.values():
            if not (
                listed_monitor["name"].startswith("Ghostship container ")
                and listed_monitor["name"] not in container_monitor_names
                and listed_monitor["type"] == "push"
            ):
                continue
            existing = call("getMonitor", listed_monitor["id"])["monitor"]
            if is_owned_stale_container_monitor(
                existing, container_names, previous_tokens
            ):
                call("deleteMonitor", (existing["id"], False))
        for container in container_names:
            monitor_name = f"Ghostship container {container}"
            existing = next(
                (m for m in monitors.values() if m["name"] == monitor_name),
                None,
            )
            if existing:
                if existing["type"] != "push":
                    raise RuntimeError(
                        f"Managed container monitor {container} changed type"
                    )
                monitor = call("getMonitor", existing["id"])["monitor"]
                if (
                    monitor["pushToken"]
                    != previous_container_tokens.get(container)
                ):
                    raise RuntimeError(
                        f"Container monitor {container} conflicts with an unmanaged entry"
                    )
                pushes["containers"][container] = monitor["pushToken"]
            else:
                token = secrets.token_hex(10)
                call(
                    "add",
                    {
                        "name": monitor_name,
                        "type": "push",
                        "conditions": [],
                        "pushToken": token,
                        "interval": 600,
                        "retryInterval": 60,
                        "maxretries": 1,
                        "accepted_statuscodes": ["200-299"],
                        "notificationIDList": {str(notification_id): True},
                    },
                )
                pushes["containers"][container] = token
            # Persist each token as soon as its monitor exists so a later API
            # failure can retry without orphaning an unrecognized monitor.
            write_push_tokens(path, pushes)
        print("Ghostship monitors provisioned; existing entries preserved")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
