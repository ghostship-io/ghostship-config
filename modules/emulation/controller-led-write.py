"""Write only Switch Pro player LED brightness; never write kiosk state as root."""

import json
import re
import subprocess
import sys
import time
from pathlib import Path


MAC = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")


def player_rows(raw):
    rows = json.loads(raw).get("players", [])
    result = {}
    for row in rows:
        mac = str(row.get("mac", "")).upper()
        slot = row.get("player")
        if row.get("connected") is True and type(slot) is int and 1 <= slot <= 4 and MAC.fullmatch(mac):
            result[mac] = slot
        if len(result) == 4:
            break
    return result


def apply(rows, sys_root=Path("/sys"), delay=time.sleep):
    # All destinations come from the kernel's input tree, never from JSON paths.
    devices_root = (sys_root / "devices").resolve()
    found = set()
    for event in (sys_root / "class/input").glob("event*"):
        try:
            mac = (event / "device/uniq").read_text().strip().upper()
            if mac not in rows:
                continue
            device = (event / "device").resolve().parent.parent
            if not device.is_relative_to(devices_root):
                continue
            for led in (device / "leds").glob("*:green:player-[1-4]"):
                brightness = (led / "brightness").resolve(strict=True)
                if not brightness.is_relative_to(devices_root):
                    continue
                found.add(mac)
                value = "1" if int(led.name[-1]) <= rows[mac] else "0"
                if brightness.read_text().strip() != value:
                    brightness.write_text(value + "\n")
                    delay(0.5)
        except OSError as exc:
            print(f"controller LED unavailable: {exc}", file=sys.stderr)
    return found


def main():
    setpriv, head, user, group, order_file = sys.argv[1:]
    # Even reads of a kiosk-supplied symlink use the kiosk identity.
    result = subprocess.run(
        [setpriv, "--reuid", user, "--regid", group, "--clear-groups",
         "--no-new-privs", head, "-c", "65537", "--", order_file],
        capture_output=True, check=True, timeout=3,
    )
    if len(result.stdout) > 65536:
        raise ValueError("controller order exceeds 64 KiB")
    rows = player_rows(result.stdout)
    for _ in range(20):
        if apply(rows) == set(rows):
            break
        # Connected input devices may appear shortly before their LED sysfs nodes.
        time.sleep(0.1)


if __name__ == "__main__":
    main()
