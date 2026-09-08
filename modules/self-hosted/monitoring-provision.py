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
# Its populated fleet exceeds Engine.IO's default 16-packet polling limit.
Payload.max_decode_packets = 256


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
        call(
            "login",
            {"username": "the owner", "password": os.environ["KUMA_PASSWORD"]},
        )
        call("getMonitorList")
        if not monitor_event.wait(15) or not notification_event.wait(15):
            raise RuntimeError("Kuma did not provide its configuration lists")
        notification = next(
            (n for n in notifications if n["name"] == "Ghostship ntfy"), None
        )
        if notification is None:
            result = call(
                "addNotification",
                (
                    {
                        "name": "Ghostship ntfy",
                        "type": "ntfy",
                        "isDefault": False,
                        "ntfyserverurl": "http://ntfy:8080",
                        "ntfytopic": "operations",
                        "ntfyAuthenticationMethod": "usernamePassword",
                        "ntfyusername": "publisher",
                        "ntfypassword": os.environ["NTFY_PUBLISH_PASSWORD"],
                        "ntfyPriority": 3,
                    },
                    None,
                ),
            )
            notification_id = result["id"]
        else:
            notification_id = notification["id"]
        registry = json.loads(Path(sys.argv[1]).read_text())
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
        pushes = {}
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
        path = Path("/var/lib/ghostship-monitoring/push.json")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_suffix(".new")
        temporary.write_text(json.dumps(pushes))
        temporary.chmod(0o600)
        temporary.replace(path)
        print("Ghostship monitors provisioned; existing entries preserved")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
