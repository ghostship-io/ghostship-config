#!/usr/bin/env python3
import argparse
import curses
import glob
import json
import os
import queue
import re
import select
import signal
import struct
import subprocess
import sys
import threading
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path


CONFIG_ROOT = Path(os.environ.get("EMULATION_CONFIG_ROOT", "/srv/emulation/config"))
DATA_ROOT = Path(os.environ.get("EMULATION_DATA_ROOT", "/srv/emulation"))
AUDIO_PREF = CONFIG_ROOT / "audio" / "output.json"
PLAYER_ORDER = CONFIG_ROOT / "controllers" / "player-order.json"
WIFI_POLICY = CONFIG_ROOT / "network" / "wifi-policy.json"
PAIRING_LOG = DATA_ROOT / "logs" / "tools" / "bluetooth-pairing.log"

EV_KEY = 0x01
EV_ABS = 0x03
BTN_MISC = 0x100
EVENT_STRUCT = struct.Struct("@llHHi")
JOY_DEADZONE = 12000
JOY_RELEASE = 7000
JOY_REPEAT_SECONDS = 0.25

ACTION_UP = "up"
ACTION_DOWN = "down"
ACTION_LEFT = "left"
ACTION_RIGHT = "right"
ACTION_SELECT = "select"
ACTION_BACK = "back"
ACTION_REFRESH = "refresh"
ACTION_ALT = "alt"
ACTION_QUIT = "quit"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class InputEvent:
    action: str
    device: dict | None = None
    source: str = "unknown"


def run_cmd(args, timeout=20):
    try:
        proc = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        return 124, out.strip(), (err.strip() or "Command timed out")
    except FileNotFoundError:
        return 127, "", f"Missing command: {args[0]}"


def read_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def append_log(path, lines):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
            for line in lines:
                if line:
                    handle.write(str(line) + "\n")
            handle.write("\n")
    except Exception:
        pass


def mac_key(value):
    return value.upper() if value else ""


def is_mac(value):
    return bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", value or ""))


def controller_identity(uniq, modalias):
    if is_mac(uniq):
        return mac_key(uniq)
    match = re.search(r"v([0-9A-Fa-f]{4})p([0-9A-Fa-f]{4})", modalias or "")
    if not match:
        return mac_key(uniq)
    stable = re.sub(r"[^0-9A-Za-z_.:-]+", "_", uniq or "unknown")
    return f"USB:{match.group(1).upper()}:{match.group(2).upper()}:{stable}"


def parse_bt_devices(output):
    devices = []
    for line in output.splitlines():
        stripped = ANSI_RE.sub("", line.strip())
        match = re.match(r"^(?:\[NEW\]\s+)?Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", stripped)
        if match:
            devices.append({"mac": mac_key(match.group(1)), "name": match.group(2).strip()})
    return devices


def bluetooth_info_value(output, key):
    prefix = f"{key}:"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return ""


def bluetooth_info_flag(output, key):
    return bluetooth_info_value(output, key).lower() == "yes"


def bluetooth_paired_or_bonded(output):
    return any(bluetooth_info_flag(output, key) for key in ("Paired", "Bonded", "BREDR.Paired", "BREDR.Bonded"))


def bluetooth_connected(output):
    return any(bluetooth_info_flag(output, key) for key in ("Connected", "BREDR.Connected", "LE.Connected"))


def looks_pairable_for_boomer(device, info):
    text = f"{device.get('name', '')}\n{info}".lower()
    allow_hints = (
        "8bitdo",
        "audio sink",
        "gamepad",
        "headphone",
        "headset",
        "hidp",
        "human interface device",
        "input-gaming",
        "input-keyboard",
        "input-mouse",
        "keyboard",
        "modalias: usb:v057ep2009",
        "mouse",
        "nintendo",
        "pro controller",
        "speaker",
        "switch",
        "wiimote",
    )
    deny_patterns = (
        r"\bandroid\b",
        r"\bbedroom tv\b",
        r"\bhome_",
        r"\biphone\b",
        r"\bliving room tv\b",
        r"\bphone\b",
        r"\bshield\b",
        r"\btelevision\b",
    )
    return any(hint in text for hint in allow_hints) and not any(re.search(pattern, text) for pattern in deny_patterns)


def parse_nmcli_rows(output):
    rows = []
    for line in output.splitlines():
        if line.strip():
            rows.append(line.rstrip("\n").split(":"))
    return rows


def ellipsize(value, limit):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def wrap_lines(lines, width):
    wrapped = []
    for line in lines:
        text = str(line)
        if not text:
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                text,
                width=max(1, width),
                break_long_words=True,
                replace_whitespace=False,
            )
            or [""]
        )
    return wrapped


def parse_bluetooth_power(output):
    for line in output.splitlines():
        if line.strip().startswith("Powered:"):
            return line.split(":", 1)[1].strip().lower() == "yes"
    return False


def parse_bluetooth_adapter_lines(output):
    name = ""
    powered = "unknown"
    discovering = "unknown"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Powered:"):
            powered = stripped.split(":", 1)[1].strip().lower()
        elif stripped.startswith("Discovering:"):
            discovering = stripped.split(":", 1)[1].strip().lower()
    lines = [f"Power: {'On' if powered == 'yes' else 'Off' if powered == 'no' else 'Unknown'}"]
    if discovering in ("yes", "no"):
        lines.append(f"Scanning: {'Yes' if discovering == 'yes' else 'No'}")
    if name:
        lines.append(f"Host: {name}")
    return lines


def menu_window(item_count, selected, visible_rows):
    if item_count <= 0 or visible_rows <= 0:
        return 0, 0
    selected = max(0, min(selected, item_count - 1))
    visible_rows = min(visible_rows, item_count)
    start = selected - visible_rows // 2
    start = max(0, min(start, item_count - visible_rows))
    return start, start + visible_rows


def pane_metrics(height, width):
    content_top = 3
    content_bottom = max(content_top, height - 4)
    content_height = max(1, content_bottom - content_top + 1)
    if width < 78:
        left_width = max(22, min(width // 2 - 2, 32))
    else:
        left_width = min(36, max(28, width // 3))
    separator_x = min(width - 2, left_width + 1)
    right_x = min(width - 1, separator_x + 2)
    right_width = max(1, width - right_x - 1)
    return {
        "content_top": content_top,
        "content_bottom": content_bottom,
        "content_height": content_height,
        "left_width": left_width,
        "separator_x": separator_x,
        "right_x": right_x,
        "right_width": right_width,
    }


def bluetooth_visible_labels(powered):
    labels = ["Status", "Show Paired", "Bluetooth Toggle"]
    if powered:
        labels.append("Restart Bluetooth")
    labels.extend(
        [
            "Scan And Pair Device",
            "Connect Paired Device",
            "Disconnect Device",
            "Reconnect All",
            "Unpair Device",
            "Player Assignment",
            "Audio Output",
        ]
    )
    return labels


BUTTON_MAP_COLUMN_WIDTH = 27


COMMON_HOTKEYS = [
    "Quick Menu: Select + X",
    "Turbo: Star + <Button>",
    "Exit: Select + Start twice",
    "Save: Select + R",
    "Load: Select + L",
    "Reset: Select + B",
    "FPS: Select + Y",
    "Screenshot: Select + A",
    "Fast: Select + ZR",
]


def two_column_button_lines(entries):
    lines = []
    for index in range(0, len(entries), 2):
        left = ellipsize(entries[index], BUTTON_MAP_COLUMN_WIDTH)
        right = ellipsize(entries[index + 1], BUTTON_MAP_COLUMN_WIDTH) if index + 1 < len(entries) else ""
        lines.append(f"{left:<{BUTTON_MAP_COLUMN_WIDTH}} {right}".rstrip())
    return lines


def controller_map(title, mappings, notes=(), hotkeys=(), square="None"):
    mappings = [*mappings, f"Square -> {square}", "Star -> Turbo"]
    lines = [title, "Button Map"]
    lines.extend(f"  {line}" for line in two_column_button_lines(mappings))
    lines.append("Hotkeys")
    lines.extend(f"  {line}" for line in (hotkeys or COMMON_HOTKEYS))
    lines.extend(f"  Note: {line}" for line in notes)
    return lines


CONTROLLER_MAPS = [
    {
        "label": "Switch Pro Reference",
        "detail": controller_map(
            "Switch Pro Reference",
            [
                "A -> A / confirm",
                "B -> B / back",
                "X -> X / refresh",
                "Y -> Y / action",
                "Plus -> Start",
                "Minus -> Select",
                "D-pad -> D-pad",
                "Left Stick -> Move",
            ],
            ["Rocknix hotkeys use Select; Square is Home only where listed."],
            square="Console Home*",
        ),
    },
    {
        "label": "NES / Famicom",
        "detail": controller_map(
            "NES / Famicom",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "B -> B",
                "A -> A",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "SNES / Super Famicom",
        "detail": controller_map(
            "SNES / Super Famicom",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "B -> B",
                "A -> A",
                "Y -> Y",
                "X -> X",
                "L -> L/ZL",
                "R -> R/ZR",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Game Boy / Color",
        "detail": controller_map(
            "Game Boy / Game Boy Color",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "B -> B",
                "A -> A",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Game Boy Advance",
        "detail": controller_map(
            "Game Boy Advance",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "B -> B",
                "A -> A",
                "L -> L/ZL",
                "R -> R/ZR",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Virtual Boy",
        "detail": controller_map(
            "Virtual Boy",
            [
                "Left D-pad -> D-pad",
                "Left Stick -> D-pad",
                "Right Stick -> Right D-pad",
                "B -> B",
                "A -> A",
                "L -> L/ZL",
                "R -> R/ZR",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Genesis / Saturn",
        "detail": controller_map(
            "Genesis / Saturn",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "A -> A",
                "B -> B",
                "C -> R",
                "X -> X",
                "Y -> Y",
                "Z -> ZR",
                "Mode -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Master System / Game Gear",
        "detail": controller_map(
            "Master System / Game Gear",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "Button 1 -> B",
                "Button 2 -> A",
                "Pause -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Dreamcast",
        "detail": controller_map(
            "Dreamcast",
            [
                "Analog -> Left Stick",
                "D-pad -> D-pad",
                "A -> A",
                "B -> B",
                "X -> X",
                "Y -> Y",
                "L Trigger -> L/ZL",
                "R Trigger -> R/ZR",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "PC Engine / CD",
        "detail": controller_map(
            "PC Engine / PC Engine CD",
            [
                "D-pad -> D-pad",
                "Left Stick -> D-pad",
                "I -> A",
                "II -> B",
                "Select -> Minus",
                "Run -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Neo Geo / Pocket",
        "detail": controller_map(
            "Neo Geo / Neo Geo Pocket",
            [
                "Stick -> D-pad",
                "Left Stick -> D-pad",
                "A -> A",
                "B -> B",
                "C -> X",
                "D -> Y",
                "Coin/Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "PlayStation",
        "detail": controller_map(
            "PlayStation",
            [
                "D-pad -> D-pad",
                "Left Stick -> Left Stick",
                "Right Stick -> Right Stick",
                "PS Cross -> A",
                "PS Circle -> B",
                "PS Square -> Y",
                "PS Triangle -> X",
                "L1 -> L",
                "R1 -> R",
                "L2 -> ZL",
                "R2 -> ZR",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Nintendo 64",
        "detail": controller_map(
            "Nintendo 64",
            [
                "Analog -> Left Stick",
                "D-pad -> D-pad",
                "A -> A",
                "B -> B",
                "C-buttons -> Right Stick",
                "C-Up -> X",
                "C-Left -> Y",
                "Z -> ZL",
                "L -> L",
                "R -> R/ZR",
                "Start -> Plus",
            ],
            ["N64 A/B stay direct."],
        ),
    },
    {
        "label": "GameCube",
        "detail": controller_map(
            "GameCube",
            [
                "Main Stick -> Left Stick",
                "C-Stick -> Right Stick",
                "D-pad -> D-pad",
                "A -> A",
                "B -> B",
                "X -> X",
                "Y -> Y",
                "L -> L/ZL",
                "R -> R/ZR",
                "Z -> R",
                "Start -> Plus",
            ],
            ["Dolphin GameCube has no Home button."],
        ),
    },
    {
        "label": "Wii Remote + Nunchuk",
        "detail": controller_map(
            "Wii Remote + Nunchuk",
            [
                "Remote D-pad -> D-pad",
                "Pointer -> Right Stick",
                "A -> A",
                "B Trigger -> ZR",
                "1 -> B",
                "2 -> Y",
                "Minus -> Minus",
                "Plus -> Plus",
                "Shake -> L3",
                "Nunchuk Stick -> Left Stick",
                "C -> L",
                "Z -> R",
            ],
            [],
            square="Console Home",
        ),
    },
    {
        "label": "Wii Classic",
        "detail": controller_map(
            "Wii Classic",
            [
                "D-pad -> D-pad",
                "Left Stick -> Left Stick",
                "Right Stick -> Right Stick",
                "a -> A",
                "b -> B",
                "x -> X",
                "y -> Y",
                "L -> L",
                "R -> R",
                "ZL -> ZL",
                "ZR -> ZR",
                "Minus -> Minus",
                "Plus -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Wii U",
        "detail": controller_map(
            "Wii U GamePad / Pro Controller",
            [
                "D-pad -> D-pad",
                "Left Stick -> Left Stick",
                "Right Stick -> Right Stick",
                "A -> A",
                "B -> B",
                "X -> X",
                "Y -> Y",
                "L -> L",
                "R -> R",
                "ZL -> ZL",
                "ZR -> ZR",
                "Minus -> Minus",
                "Plus -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Xbox",
        "detail": controller_map(
            "Xbox",
            [
                "D-pad -> D-pad",
                "Left Stick -> Left Stick",
                "Right Stick -> Right Stick",
                "A -> A",
                "B -> B",
                "X -> X",
                "Y -> Y",
                "Left Trigger -> ZL",
                "Right Trigger -> ZR",
                "White -> L",
                "Black -> R",
                "Back -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "PSP",
        "detail": controller_map(
            "PSP",
            [
                "D-pad -> D-pad",
                "Analog -> Left Stick",
                "PSP Cross -> A",
                "PSP Circle -> B",
                "PSP Square -> Y",
                "PSP Triangle -> X",
                "L -> L/ZL",
                "R -> R/ZR",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "DS / 3DS",
        "detail": controller_map(
            "DS / 3DS",
            [
                "D-pad -> D-pad",
                "Circle Pad -> Left Stick",
                "C-Stick -> Right Stick",
                "A -> A",
                "B -> B",
                "X -> X",
                "Y -> Y",
                "L -> L",
                "R -> R",
                "ZL -> ZL",
                "ZR -> ZR",
                "Select -> Minus",
                "Start -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Switch",
        "detail": controller_map(
            "Switch",
            [
                "D-pad -> D-pad",
                "Left Stick -> Left Stick",
                "Right Stick -> Right Stick",
                "A -> A",
                "B -> B",
                "X -> X",
                "Y -> Y",
                "L -> L",
                "R -> R",
                "ZL -> ZL",
                "ZR -> ZR",
                "Minus -> Minus",
                "Plus -> Plus",
            ],
            [],
        ),
    },
    {
        "label": "Arcade",
        "detail": controller_map(
            "Arcade",
            [
                "Stick -> D-pad",
                "Left Stick -> Stick",
                "Coin -> Minus",
                "Start -> Plus",
                "B1 -> A",
                "B2 -> B",
                "B3 -> X",
                "B4 -> Y",
                "B5 -> L/ZL",
                "B6 -> R/ZR",
                "B7 -> ZL",
                "B8 -> ZR",
            ],
            [],
        ),
    },
    {
        "label": "GZDoom",
        "detail": controller_map(
            "GZDoom",
            [
                "Move -> Left Stick/D-pad",
                "Look -> Right Stick",
                "Fire -> R2",
                "Alt Fire -> L2",
                "Use/Confirm -> A",
                "Jump/Back -> B",
                "Map Toggle -> Minus",
                "Crouch Toggle -> Y",
                "X -> No-op",
                "Prev Weapon -> L1",
                "Next Weapon -> R1",
                "Map Pan -> Left Stick/D-pad",
                "Menu -> Plus",
            ],
            ["Right stick uses native SDL axes for horizontal and vertical look."],
            [
                "Menu: Plus / Start",
                "Map: Minus toggles",
                "Turbo: Star + <Button>",
                "Exit: Select + Start twice",
            ],
        ),
    },
    {
        "label": "PICO-8",
        "detail": controller_map(
            "PICO-8",
            [
                "Move -> D-pad/Left Stick",
                "O / Primary -> B",
                "X / Secondary -> A",
                "Pause/Menu -> Plus",
            ],
            [],
        ),
    },
]


CONTROLLER_NAME_HINTS = (
    "8bit",
    "controller",
    "dualshock",
    "dualsense",
    "gamepad",
    "joy-con",
    "joycon",
    "joystick",
    "nintendo",
    "playstation",
    "steam",
    "switch",
    "wii",
    "wireless controller",
    "xbox",
)

NON_CONTROLLER_NAME_HINTS = (
    "audio",
    "consumer control",
    "hd-audio",
    "hdmi",
    "imu",
    "keyboard",
    "mouse",
    "power button",
    "touchpad",
    "video bus",
)


def is_controller_name(name):
    lowered = (name or "").lower()
    if not lowered or any(hint in lowered for hint in NON_CONTROLLER_NAME_HINTS):
        return False
    return any(hint in lowered for hint in CONTROLLER_NAME_HINTS)


def controller_device_info(event_path):
    base = Path("/sys/class/input") / Path(event_path).name / "device"
    name = ""
    uniq = ""
    modalias = ""
    try:
        name = (base / "name").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    try:
        uniq = (base / "uniq").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    try:
        modalias = (base / "modalias").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    return {"event": event_path, "name": name or Path(event_path).name, "mac": controller_identity(uniq, modalias)}


def capability_has_bit(value, bit):
    try:
        words = [int(word, 16) for word in (value or "").split()]
    except ValueError:
        return False
    word_index = bit // 64
    bit_index = bit % 64
    if word_index >= len(words):
        return False
    return bool(words[-1 - word_index] & (1 << bit_index))


def capability_has_any_bit(value):
    try:
        return any(int(word, 16) for word in (value or "").split())
    except ValueError:
        return False


def event_has_controller_navigation(event_path):
    base = Path("/sys/class/input") / Path(event_path).name / "device" / "capabilities"
    try:
        key_caps = (base / "key").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        key_caps = ""
    try:
        abs_caps = (base / "abs").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        abs_caps = ""
    return capability_has_any_bit(key_caps) or capability_has_bit(abs_caps, 16) or capability_has_bit(abs_caps, 17)


def is_controller_event_device(event_path):
    return is_controller_name(controller_device_info(event_path).get("name", "")) and event_has_controller_navigation(event_path)


def format_bluetooth_status(adapter_lines, connected, paired, players, audio_output):
    player_by_mac = {mac_key(player.get("mac")): player for player in players if player.get("mac")}
    lines = []
    power = next((line for line in adapter_lines if line.startswith("Power:")), "Power: Unknown")
    scanning = next((line for line in adapter_lines if line.startswith("Scanning:")), "Scanning: Unknown")
    lines.append(f"{power} | {scanning}")
    lines.append(f"Audio: {ellipsize(audio_output, 48)}")
    lines.append("")
    lines.append(f"Connected ({len(connected)}):")
    if connected:
        for device in connected[:6]:
            player = player_by_mac.get(mac_key(device.get("mac")))
            prefix = f"P{player.get('player')}" if player else "Other"
            lines.append(f"{prefix} {ellipsize(device.get('name'), 44)}")
    else:
        lines.append("None")
    lines.append("")
    lines.append("Player slots:")
    for slot in range(1, 5):
        player = next((row for row in players if int(row.get("player", 0) or 0) == slot), None)
        lines.append(f"P{slot}: {ellipsize(player.get('name'), 42) if player else 'Unassigned'}")
    lines.append(f"Paired: {len(paired)}")
    return lines


class ControllerReader(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True)
        self.events = events
        self.stop_event = threading.Event()
        self.fds = {}
        self.last_abs = {}
        self.last_abs_emit = {}

    def refresh_devices(self):
        wanted = {path for path in glob.glob("/dev/input/event*") if is_controller_event_device(path)}
        for path in list(self.fds):
            if path not in wanted:
                os.close(self.fds.pop(path))
        for path in sorted(wanted):
            if path in self.fds:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self.fds[path] = fd

    def emit(self, action, path, source):
        self.events.put(InputEvent(action=action, device=controller_device_info(path), source=source))

    def handle_event(self, path, ev_type, code, value):
        if ev_type == EV_KEY and value == 1:
            key_map = {
                103: ACTION_UP,
                108: ACTION_DOWN,
                105: ACTION_LEFT,
                106: ACTION_RIGHT,
                28: ACTION_SELECT,
                1: ACTION_BACK,
                19: ACTION_REFRESH,
                21: ACTION_ALT,
                544: ACTION_UP,
                545: ACTION_DOWN,
                546: ACTION_LEFT,
                547: ACTION_RIGHT,
                304: ACTION_BACK,
                305: ACTION_SELECT,
                307: ACTION_REFRESH,
                308: ACTION_ALT,
                315: ACTION_SELECT,
            }
            action = key_map.get(code)
            if action:
                self.emit(action, path, "key")
        elif ev_type == EV_ABS and code in (0, 1, 16, 17):
            threshold = 1 if code in (16, 17) else JOY_DEADZONE
            release = 0 if code in (16, 17) else JOY_RELEASE
            if abs(value) <= release:
                self.last_abs[(path, code)] = None
                return
            if abs(value) < threshold:
                return
            if code in (0, 16):
                action = ACTION_LEFT if value < 0 else ACTION_RIGHT if value > 0 else None
            else:
                action = ACTION_UP if value < 0 else ACTION_DOWN if value > 0 else None
            key = (path, code)
            now = time.monotonic()
            last_action = self.last_abs.get(key)
            last_emit = self.last_abs_emit.get(key, 0)
            if action and (last_action != action or now - last_emit >= JOY_REPEAT_SECONDS):
                self.emit(action, path, "axis")
                self.last_abs_emit[key] = now
            self.last_abs[key] = action

    def run(self):
        while not self.stop_event.is_set():
            self.refresh_devices()
            if not self.fds:
                time.sleep(1)
                continue
            try:
                readable, _, _ = select.select(list(self.fds.values()), [], [], 0.1)
            except OSError:
                time.sleep(0.2)
                continue
            reverse = {fd: path for path, fd in self.fds.items()}
            for fd in readable:
                path = reverse.get(fd)
                if not path:
                    continue
                try:
                    data = os.read(fd, EVENT_STRUCT.size * 16)
                except BlockingIOError:
                    continue
                except OSError:
                    continue
                for offset in range(0, len(data) - EVENT_STRUCT.size + 1, EVENT_STRUCT.size):
                    _, _, ev_type, code, value = EVENT_STRUCT.unpack(data[offset : offset + EVENT_STRUCT.size])
                    self.handle_event(path, ev_type, code, value)

    def stop(self):
        self.stop_event.set()
        for fd in list(self.fds.values()):
            try:
                os.close(fd)
            except OSError:
                pass


class Tui:
    def __init__(self, stdscr, mode):
        self.stdscr = stdscr
        self.mode = mode
        self.queue = queue.Queue()
        self.controller = ControllerReader(self.queue)
        self.message = "Ready"
        self.running = True
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLACK)
        self.stdscr.bkgd(" ", curses.color_pair(1))
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        self.controller.start()

    def stop(self):
        self.controller.stop()

    def clear_pending_input(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        while self.stdscr.getch() != -1:
            pass
        self.controller.last_abs.clear()
        self.controller.last_abs_emit.clear()

    def add(self, y, x, text, attr=0):
        height, width = self.stdscr.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        text = str(text)
        if len(text) > width - x - 1:
            text = text[: max(0, width - x - 2)] + "..."
        try:
            self.stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def wrapped(self, lines, width):
        return wrap_lines(lines, width)

    def draw_frame(self, title, subtitle=""):
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        self.add(0, 0, " " * (width - 1), curses.color_pair(1))
        self.add(0, 2, title.upper(), curses.color_pair(1) | curses.A_BOLD)
        if subtitle:
            self.add(1, 2, subtitle, curses.color_pair(3) | curses.A_DIM)
        if self.mode == "maps":
            footer = "Move: D-pad/Left Stick/Arrows/WASD  Details: Left/Right  Back: B/Esc"
        else:
            footer = "Move: D-pad/Left Stick/Arrows/WASD  Select: A/Enter  Back: B/Esc  Refresh: X/R"
        self.add(height - 2, 0, " " * (width - 1), curses.color_pair(1))
        self.add(height - 2, 2, footer, curses.color_pair(1) | curses.A_DIM)
        self.add(height - 1, 2, self.message, curses.color_pair(1) | curses.A_DIM)

    def item_detail_lines(self, item, details):
        lines = []
        if item:
            if not item.get("detail_only"):
                lines.append(item.get("label", ""))
            if item.get("desc") and not item.get("detail_only"):
                lines.extend(["", item["desc"]])
            detail = item.get("detail")
            if callable(detail):
                detail = detail()
            if detail:
                if lines:
                    lines.append("")
                lines.extend(detail)
        if details:
            if callable(details):
                details = details(item)
            if details:
                if lines:
                    lines.append("")
                lines.extend(details)
        return lines

    def draw_two_pane(self, title, items, selected, detail_lines, detail_top=0):
        self.draw_frame(title)
        height, width = self.stdscr.getmaxyx()
        metrics = pane_metrics(height, width)
        top = metrics["content_top"]
        bottom = metrics["content_bottom"]
        left_width = metrics["left_width"]
        separator_x = metrics["separator_x"]
        right_x = metrics["right_x"]
        right_width = metrics["right_width"]
        self.add(1, 2, "OPTIONS", curses.color_pair(1) | curses.A_BOLD)
        self.add(1, right_x, "DETAILS", curses.color_pair(1) | curses.A_BOLD)
        for y in range(top - 1, bottom + 1):
            self.add(y, separator_x, "|", curses.color_pair(1) | curses.A_DIM)
        menu_rows = metrics["content_height"]
        if len(items) > menu_rows:
            menu_rows = max(1, menu_rows - 1)
        start, end = menu_window(len(items), selected, menu_rows)
        visible = items[start:end]
        if start > 0:
            self.add(top - 1, 2, "more above", curses.color_pair(1) | curses.A_DIM)
        if not visible:
            self.add(top, 2, "No items available.", curses.color_pair(1) | curses.A_DIM)
        for offset, item in enumerate(visible):
            index = start + offset
            attr = curses.color_pair(2) | curses.A_BOLD if index == selected else curses.color_pair(1)
            marker = ">" if index == selected else " "
            label = f"{marker} {item['label']}"
            self.add(top + offset, 2, label.ljust(max(1, left_width - 2)), attr)
        if end < len(items):
            self.add(bottom, 2, "more below", curses.color_pair(1) | curses.A_DIM)
        right_lines = self.wrapped(detail_lines, right_width)
        detail_top = max(0, min(detail_top, max(0, len(right_lines) - metrics["content_height"])))
        if detail_top > 0:
            self.add(top - 1, right_x, "more above", curses.color_pair(1) | curses.A_DIM)
        if detail_top + metrics["content_height"] < len(right_lines):
            self.add(bottom, right_x, "more below", curses.color_pair(1) | curses.A_DIM)
        for row, line in enumerate(right_lines[detail_top : detail_top + metrics["content_height"]], start=top):
            attr = curses.color_pair(1) | (curses.A_BOLD if row == top else curses.A_NORMAL)
            self.add(row, right_x, line, attr)

    def get_input(self, timeout=0.1):
        try:
            event = self.queue.get_nowait()
            return event
        except queue.Empty:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            ch = self.stdscr.getch()
            if ch == -1:
                time.sleep(0.02)
                continue
            if ch in (curses.KEY_UP, ord("w"), ord("W")):
                return InputEvent(ACTION_UP, source="keyboard")
            if ch in (curses.KEY_DOWN, ord("s"), ord("S")):
                return InputEvent(ACTION_DOWN, source="keyboard")
            if ch in (curses.KEY_LEFT, ord("a"), ord("A")):
                return InputEvent(ACTION_LEFT, source="keyboard")
            if ch in (curses.KEY_RIGHT, ord("d"), ord("D")):
                return InputEvent(ACTION_RIGHT, source="keyboard")
            if ch in (10, 13, curses.KEY_ENTER):
                return InputEvent(ACTION_SELECT, source="keyboard")
            if ch in (27,):
                return InputEvent(ACTION_BACK, source="keyboard")
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                return InputEvent("\b", source="keyboard")
            if ch in (ord("r"), ord("R")):
                return InputEvent(ACTION_REFRESH, source="keyboard")
            if ch in (ord("y"), ord("Y"), ord("x"), ord("X")):
                return InputEvent(ACTION_ALT if ch in (ord("y"), ord("Y")) else ACTION_REFRESH, source="keyboard")
            if ch in (ord("q"), ord("Q")):
                return InputEvent(ACTION_QUIT, source="keyboard")
            if 32 <= ch <= 126:
                return InputEvent(chr(ch), source="keyboard")
        return None

    def get_text_input(self, timeout=0.1):
        try:
            event = self.queue.get_nowait()
            return event
        except queue.Empty:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            ch = self.stdscr.getch()
            if ch == -1:
                time.sleep(0.02)
                continue
            if ch == curses.KEY_UP:
                return InputEvent(ACTION_UP, source="keyboard")
            if ch == curses.KEY_DOWN:
                return InputEvent(ACTION_DOWN, source="keyboard")
            if ch == curses.KEY_LEFT:
                return InputEvent(ACTION_LEFT, source="keyboard")
            if ch == curses.KEY_RIGHT:
                return InputEvent(ACTION_RIGHT, source="keyboard")
            if ch in (10, 13, curses.KEY_ENTER):
                return InputEvent(ACTION_SELECT, source="keyboard")
            if ch == 27:
                return InputEvent(ACTION_BACK, source="keyboard")
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                return InputEvent("\b", source="keyboard")
            if 32 <= ch <= 126:
                return InputEvent(chr(ch), source="keyboard")
        return None

    def menu(self, title, items, details=None, selected=0, scroll_detail=False, select_returns=True):
        selected = max(0, min(selected, len(items) - 1)) if items else 0
        detail_top = 0
        while self.running:
            item = items[selected] if items else None
            detail_lines = self.item_detail_lines(item, details)
            self.draw_two_pane(title, items, selected, detail_lines, detail_top)
            self.stdscr.refresh()
            event = self.get_input()
            if not event:
                continue
            if event.action in (ACTION_QUIT, ACTION_BACK):
                return None
            if event.action == ACTION_REFRESH:
                return "refresh"
            if event.action == ACTION_UP and items:
                selected = (selected - 1) % len(items)
                detail_top = 0
            elif event.action == ACTION_DOWN and items:
                selected = (selected + 1) % len(items)
                detail_top = 0
            elif scroll_detail and event.action == ACTION_LEFT:
                detail_top = max(0, detail_top - 1)
            elif scroll_detail and event.action == ACTION_RIGHT:
                metrics = pane_metrics(*self.stdscr.getmaxyx())
                max_top = max(0, len(self.wrapped(detail_lines, metrics["right_width"])) - metrics["content_height"])
                detail_top = min(max_top, detail_top + 1)
            elif event.action == ACTION_SELECT and items and select_returns:
                return items[selected]

    def confirm(self, title, lines):
        items = [{"label": "Yes", "desc": "Run this action"}, {"label": "No", "desc": "Go back"}]
        choice = self.menu(title, items, lines)
        return bool(choice and choice.get("label") == "Yes")

    def show_output(self, title, output):
        lines = []
        for block in output:
            if not block:
                continue
            lines.extend(str(block).splitlines())
        if not lines:
            lines = ["Done."]
        top = 0
        while self.running:
            self.draw_frame(title, "Press B/Esc to go back. Use up/down to scroll.")
            height, width = self.stdscr.getmaxyx()
            wrapped = self.wrapped(lines, max(1, width - 4))
            visible_rows = max(1, height - 6)
            for row, line in enumerate(wrapped[top : top + visible_rows], start=3):
                self.add(row, 2, line)
            self.stdscr.refresh()
            event = self.get_text_input()
            if not event:
                continue
            if event.action in (ACTION_BACK, ACTION_SELECT, ACTION_QUIT):
                return
            if event.action == ACTION_UP:
                top = max(0, top - 1)
            elif event.action == ACTION_DOWN:
                top = min(max(0, len(wrapped) - visible_rows), top + 1)

    def choose(self, title, rows, empty="No entries available"):
        items = []
        for row in rows:
            items.append({"label": row.get("label", row.get("name", "")), "desc": row.get("desc", ""), "row": row})
        if not items:
            self.show_output(title, [empty])
            return None
        choice = self.menu(title, items)
        return choice.get("row") if isinstance(choice, dict) else None

    def prompt_text(self, title, prompt, hidden=False):
        value = ""
        grid = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + ["-", "_", ".", " ", "BACK", "DONE", "CANCEL"]
        selected = 0
        while self.running:
            self.draw_frame(title, prompt)
            shown = "*" * len(value) if hidden else value
            self.add(4, 2, f"> {shown}", curses.A_BOLD)
            cols = 8
            for index, char in enumerate(grid):
                y = 7 + index // cols * 2
                x = 4 + (index % cols) * 10
                attr = curses.color_pair(2) | curses.A_BOLD if index == selected else curses.A_NORMAL
                self.add(y, x, char, attr)
            self.stdscr.refresh()
            event = self.get_input()
            if not event:
                continue
            if event.action == ACTION_BACK:
                return None
            if event.action == ACTION_LEFT:
                selected = (selected - 1) % len(grid)
            elif event.action == ACTION_RIGHT:
                selected = (selected + 1) % len(grid)
            elif event.action == ACTION_UP:
                selected = (selected - cols) % len(grid)
            elif event.action == ACTION_DOWN:
                selected = (selected + cols) % len(grid)
            elif event.action == ACTION_SELECT:
                char = grid[selected]
                if char == "DONE":
                    return value
                if char == "CANCEL":
                    return None
                if char == "BACK":
                    value = value[:-1]
                else:
                    value += char
            elif event.action == "\b":
                value = value[:-1]
            elif isinstance(event.action, str) and len(event.action) == 1:
                value += event.action

    def progress(self, title, lines):
        self.draw_frame(title)
        height, width = self.stdscr.getmaxyx()
        wrapped = self.wrapped(lines, max(1, width - 4))
        for index, line in enumerate(wrapped[: max(1, height - 6)], start=4):
            self.add(index, 2, line)
        self.stdscr.refresh()


class BluetoothBackend:
    def devices(self, kind=None):
        args = ["bluetoothctl", "devices"]
        if kind:
            args.append(kind)
        _, out, _ = run_cmd(args, timeout=8)
        return parse_bt_devices(out)

    def info(self, mac):
        _, out, _ = run_cmd(["bluetoothctl", "info", mac], timeout=8)
        return out

    def adapter_summary(self):
        _, out, err = run_cmd(["bluetoothctl", "show"], timeout=8)
        lines = parse_bluetooth_adapter_lines(out)
        if err:
            lines.append(err)
        return lines or ["Bluetooth adapter not found."]

    def powered(self):
        _, out, _ = run_cmd(["bluetoothctl", "show"], timeout=8)
        return parse_bluetooth_power(out)

    def paired_rows(self):
        connected = {d["mac"] for d in self.devices("Connected")}
        rows = []
        for device in self.devices("Paired"):
            state = "connected" if device["mac"] in connected else "paired"
            rows.append({"label": device["name"], "desc": f"{device['mac']} - {state}", **device})
        return rows

    def pairing_rows(self):
        paired = {d["mac"] for d in self.devices("Paired")}
        connected = {d["mac"] for d in self.devices("Connected")}
        rows = []
        for device in self.scan():
            if device["mac"] in connected:
                continue
            info = self.info(device["mac"])
            if not looks_pairable_for_boomer(device, info):
                continue
            paired_state = device["mac"] in paired or bluetooth_paired_or_bonded(info)
            state = "paired" if paired_state else "not paired"
            rows.append({"label": device["name"], "desc": f"{device['mac']} - {state}", "paired": paired_state, **device})
        return rows

    def paired_or_bonded(self, mac):
        return bluetooth_paired_or_bonded(self.info(mac))

    def connected_mac(self, mac):
        return bluetooth_connected(self.info(mac))

    def scan(self, seconds=10):
        run_cmd(["bluetoothctl", "power", "on"], timeout=8)
        run_cmd(["bluetoothctl", "agent", "KeyboardDisplay"], timeout=8)
        run_cmd(["bluetoothctl", "default-agent"], timeout=8)
        run_cmd(["bluetoothctl", "pairable", "on"], timeout=8)
        _, out, _ = run_cmd(["bluetoothctl", "--timeout", str(seconds), "scan", "on"], timeout=seconds + 5)
        run_cmd(["bluetoothctl", "scan", "off"], timeout=8)
        seen = {d["mac"]: d for d in parse_bt_devices(out)}
        for device in self.devices():
            seen.setdefault(device["mac"], device)
        return sorted(seen.values(), key=lambda row: row["name"].lower())

    def pair(self, mac):
        return run_cmd(["bluetoothctl", "--agent", "KeyboardDisplay", "pair", mac], timeout=35)

    def action(self, *args, timeout=20):
        return run_cmd(["bluetoothctl", *args], timeout=timeout)

    def restart_service(self):
        return run_cmd(["systemctl", "restart", "bluetooth.service"], timeout=20)

    def reconnect_all(self):
        output = []
        for device in self.devices("Paired"):
            self.action("trust", device["mac"])
            self.action("wake", device["mac"], "on")
            code, out, err = self.action("connect", device["mac"], timeout=20)
            output.append(f"{device['name']} ({device['mac']}): {'OK' if code == 0 else 'failed'}")
            if out:
                output.append(out)
            if err:
                output.append(err)
        return output


class AudioBackend:
    def sinks(self):
        code, out, err = run_cmd(["pactl", "--format=json", "list", "sinks"], timeout=8)
        if code != 0:
            return [], err
        try:
            raw = json.loads(out or "[]")
        except json.JSONDecodeError as exc:
            return [], str(exc)
        sinks = []
        for sink in raw:
            props = sink.get("properties", {})
            name = sink.get("name", "")
            desc = sink.get("description", name)
            bus = props.get("device.bus", "")
            is_bt = bus == "bluetooth" or "bluez" in name.lower() or "bluetooth" in desc.lower()
            is_hdmi = "hdmi" in desc.lower() or "displayport" in desc.lower() or "navi" in desc.lower()
            if is_bt or is_hdmi:
                sinks.append({"name": name, "desc": desc, "bluetooth": is_bt, "hdmi": is_hdmi})
        return sinks, ""

    def preference(self):
        return read_json(AUDIO_PREF, {"mode": "hdmi"})

    def set_hdmi(self):
        write_json(AUDIO_PREF, {"mode": "hdmi", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return run_cmd(["audio-route"], timeout=15)

    def set_bluetooth(self, sink):
        write_json(
            AUDIO_PREF,
            {
                "mode": "bluetooth",
                "sink": sink["name"],
                "description": sink["desc"],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        return run_cmd(["audio-route"], timeout=15)


class WifiBackend:
    def policy(self):
        return read_json(WIFI_POLICY, {"allow_24ghz": False})

    def write_policy(self, allow_24ghz):
        write_json(
            WIFI_POLICY,
            {"allow_24ghz": bool(allow_24ghz), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        return self.apply_policy()

    def apply_policy(self):
        allow = self.policy().get("allow_24ghz", False)
        output = []
        for profile in self.saved_profiles():
            band = "" if allow else "a"
            code, out, err = run_cmd(
                ["nmcli", "connection", "modify", "uuid", profile["uuid"], "802-11-wireless.band", band],
                timeout=12,
            )
            output.append(f"{profile['name']}: {'2.4/5 GHz allowed' if allow else '5 GHz only'}")
            if code != 0:
                output.append(err or out)
        return 0, "\n".join(output), ""

    def status_lines(self):
        lines = []
        _, radio, _ = run_cmd(["nmcli", "radio"], timeout=8)
        _, devices, _ = run_cmd(
            ["nmcli", "-t", "--escape", "no", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
            timeout=8,
        )
        policy = self.policy()
        lines.append("2.4 GHz: " + ("Allowed" if policy.get("allow_24ghz") else "Disabled for Bluetooth performance"))
        wifi_line = next((line for line in radio.splitlines() if "WIFI" not in line and line.strip()), "")
        if wifi_line:
            parts = wifi_line.split()
            if len(parts) >= 2:
                lines.append(f"Wi-Fi radio: {parts[1].capitalize()}")
        wifi_devices = [parts for parts in parse_nmcli_rows(devices) if len(parts) >= 3 and parts[1] == "wifi"]
        active_device = next((parts for parts in wifi_devices if len(parts) >= 4 and parts[2].startswith("connected")), None)
        if active_device:
            lines.append(f"Active SSID: {active_device[3] or 'unknown'}")
            lines.append(f"Device: {active_device[0]}")
            _, ip, _ = run_cmd(["nmcli", "-t", "--escape", "no", "-f", "IP4.ADDRESS,IP4.GATEWAY", "device", "show", active_device[0]], timeout=8)
            ip_lines = [line for line in ip.splitlines() if line]
            if ip_lines:
                lines.extend(ip_lines[:3])
        elif wifi_devices:
            lines.append("Active SSID: none")
            lines.append(f"Device: {wifi_devices[0][0]} ({wifi_devices[0][2]})")
        else:
            lines.append("Wi-Fi device: not found")
        saved = self.saved_profiles()
        lines.append(f"Saved profiles: {len(saved)}")
        _, nearby, _ = run_cmd(
            ["nmcli", "-t", "--escape", "no", "-f", "SSID,SIGNAL,CHAN,IN-USE", "device", "wifi", "list", "--rescan", "no"],
            timeout=8,
        )
        networks = [parts for parts in parse_nmcli_rows(nearby) if len(parts) >= 3 and parts[0]]
        if networks:
            lines.append("Nearby:")
            for parts in networks[:3]:
                current = " current" if len(parts) > 3 and parts[3] == "*" else ""
                lines.append(f"{parts[0]}  {parts[1]}%  ch {parts[2]}{current}")
        else:
            lines.append("Nearby: not scanned yet")
        return lines

    def saved_profiles(self):
        _, out, _ = run_cmd(["nmcli", "-t", "--escape", "no", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"], timeout=8)
        rows = []
        for parts in parse_nmcli_rows(out):
            if len(parts) >= 3 and parts[2] == "802-11-wireless":
                rows.append({"name": parts[0], "uuid": parts[1], "device": parts[3] if len(parts) > 3 else ""})
        return rows

    def active_profiles(self):
        _, out, _ = run_cmd(["nmcli", "-t", "--escape", "no", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"], timeout=8)
        rows = []
        for parts in parse_nmcli_rows(out):
            if len(parts) >= 3 and parts[2] == "802-11-wireless":
                rows.append({"name": parts[0], "uuid": parts[1], "device": parts[3] if len(parts) > 3 else ""})
        return rows

    def networks(self):
        run_cmd(["nmcli", "radio", "wifi", "on"], timeout=8)
        _, out, _ = run_cmd(
            ["nmcli", "-t", "--escape", "no", "-f", "SSID,SECURITY,SIGNAL,CHAN,IN-USE", "device", "wifi", "list", "--rescan", "yes"],
            timeout=20,
        )
        by_ssid = {}
        for parts in parse_nmcli_rows(out):
            if len(parts) < 4 or not parts[0]:
                continue
            ssid = parts[0]
            try:
                signal = int(parts[2] or "0")
            except ValueError:
                signal = 0
            chan = parts[3]
            current = parts[4] if len(parts) > 4 else ""
            row = {"ssid": ssid, "security": parts[1], "signal": signal, "channel": chan, "current": current}
            if ssid not in by_ssid or signal > by_ssid[ssid]["signal"]:
                by_ssid[ssid] = row
        return sorted(by_ssid.values(), key=lambda row: row["signal"], reverse=True)

    def connect_saved(self, uuid):
        code, out, err = run_cmd(["nmcli", "--wait", "30", "connection", "up", "uuid", uuid], timeout=40)
        self.apply_policy()
        return code, out, err

    def connect_network(self, ssid, password=None):
        args = ["nmcli", "--wait", "45", "device", "wifi", "connect", ssid]
        if password:
            args.extend(["password", password])
        code, out, err = run_cmd(args, timeout=55)
        self.apply_policy()
        return code, out, err

    def disconnect(self, device):
        return run_cmd(["nmcli", "device", "disconnect", device], timeout=20)

    def forget(self, uuid):
        return run_cmd(["nmcli", "connection", "delete", "uuid", uuid], timeout=20)


def assign_player_order(order, mac, name, slot):
    players = order.get("players", [])
    for player in players:
        player["player"] = int(player.get("player", 0) or 0)
    existing = next((p for p in players if mac and mac_key(p.get("mac")) == mac), None)
    target = next((p for p in players if p.get("player") == slot), None)
    if existing and target and existing is not target:
        existing["player"], target["player"] = target["player"], existing["player"]
    elif existing:
        existing["player"] = slot
        existing["name"] = name
    elif target:
        target["player"] = len(players) + 1
        players.append({"player": slot, "mac": mac, "name": name, "connected": True})
    else:
        players.append({"player": slot, "mac": mac, "name": name, "connected": True})
    players.sort(key=lambda row: row.get("player", 99))
    return {"players": players}


class SettingsApp:
    def __init__(self, tui):
        self.tui = tui
        self.bt = BluetoothBackend()
        self.audio = AudioBackend()
        self.wifi = WifiBackend()

    def run(self):
        try:
            if self.tui.mode == "bluetooth":
                self.bluetooth_menu()
            elif self.tui.mode == "wifi":
                self.wifi_menu()
            else:
                self.controller_maps_menu()
        finally:
            self.tui.stop()

    def run_and_show(self, title, func):
        self.tui.progress(title, ["Working..."])
        code, out, err = func()
        self.tui.message = "OK" if code == 0 else f"Failed with exit {code}"
        self.tui.show_output(title, [out, err])

    def controller_maps_menu(self):
        items = [
            {"label": row["label"], "detail_only": True, "detail": row["detail"]}
            for row in CONTROLLER_MAPS
        ]
        while self.tui.running:
            choice = self.tui.menu("Controller Maps", items, scroll_detail=True, select_returns=False)
            if not choice:
                return
            if choice == "refresh":
                continue

    def bluetooth_menu(self):
        while self.tui.running:
            powered = self.bt.powered()
            status = self.bluetooth_status_lines()
            toggle_target = "off" if powered else "on"
            items = [
                {
                    "label": "Status",
                    "detail_only": True,
                    "detail": status,
                    "action": self.bluetooth_status,
                },
                {
                    "label": "Show Paired",
                    "detail_only": True,
                    "detail": self.bluetooth_paired_lines,
                    "action": self.bluetooth_paired,
                },
                {
                    "label": "Bluetooth Toggle",
                    "desc": f"Turn Bluetooth {toggle_target}.",
                    "detail": [f"Current state: {'On' if powered else 'Off'}", f"Select to turn Bluetooth {toggle_target}."],
                    "action": lambda: self.run_and_show("Bluetooth Toggle", lambda: self.bt.action("power", toggle_target)),
                },
            ]
            if powered:
                items.append(
                    {
                        "label": "Restart Bluetooth",
                        "desc": "Restart bluetooth.service without rebooting Boomer.",
                        "detail": ["Available because Bluetooth is on.", "Use this if paired devices stop responding."],
                        "action": lambda: self.run_and_show("Restart Bluetooth", self.bt.restart_service),
                    }
                )
            items.extend(
                [
                    {
                        "label": "Scan And Pair Device",
                        "desc": "Find and pair controllers, headphones, Wiimotes, keyboards, or accessories.",
                        "detail": ["Starts a short scan for nearby devices.", "Put the device in pairing mode first."],
                        "action": self.bluetooth_scan_pair,
                    },
                    {
                        "label": "Connect Paired Device",
                        "desc": "Connect one saved Bluetooth device.",
                        "detail": ["Use this for a controller or headset that is already paired."],
                        "action": self.bluetooth_connect_paired,
                    },
                    {
                        "label": "Disconnect Device",
                        "desc": "Disconnect one currently connected Bluetooth device.",
                        "detail": ["Leaves the pairing saved for later reconnect."],
                        "action": self.bluetooth_disconnect,
                    },
                    {
                        "label": "Reconnect All",
                        "desc": "Trust and reconnect every paired Bluetooth device.",
                        "detail": ["Useful after waking controllers or headphones."],
                        "action": self.bluetooth_reconnect_all,
                    },
                    {
                        "label": "Unpair Device",
                        "desc": "Remove a saved Bluetooth pairing.",
                        "detail": ["Use this before pairing a device from scratch again."],
                        "action": self.bluetooth_unpair,
                    },
                    {
                        "label": "Player Assignment",
                        "desc": "Press a controller button, then move or swap its player slot.",
                        "detail": ["Press any controller button or keyboard key.", "B/Esc backs out without changing assignments."],
                        "action": self.player_assignment,
                    },
                    {
                        "label": "Audio Output",
                        "desc": "Choose HDMI or connected Bluetooth headphones.",
                        "detail": ["Bluetooth audio is used only when explicitly selected and available."],
                        "action": self.audio_output,
                    },
                ]
            )
            choice = self.tui.menu("Bluetooth Settings", items)
            if not choice:
                return
            if choice == "refresh":
                continue
            choice["action"]()

    def bluetooth_status_lines(self):
        pref = self.audio.preference()
        order = read_json(PLAYER_ORDER, {"players": []})
        paired = self.bt.devices("Paired")
        connected = self.bt.devices("Connected")
        return format_bluetooth_status(
            self.bt.adapter_summary(),
            connected,
            paired,
            order.get("players", []),
            pref.get("description") or pref.get("mode", "hdmi"),
        )

    def bluetooth_status(self):
        self.tui.show_output("Bluetooth Status", self.bluetooth_status_lines())

    def bluetooth_paired_lines(self):
        connected = {device["mac"] for device in self.bt.devices("Connected")}
        paired = self.bt.devices("Paired")
        if not paired:
            return ["No paired Bluetooth devices."]
        lines = [f"Paired devices ({len(paired)}):"]
        for device in paired:
            state = "connected" if device["mac"] in connected else "not connected"
            lines.append(f"{ellipsize(device['name'], 36)}")
            lines.append(f"  {device['mac']} - {state}")
        return lines

    def bluetooth_paired(self):
        self.tui.show_output("Show Paired", self.bluetooth_paired_lines())

    def bluetooth_scan_pair(self):
        self.tui.progress("Bluetooth Scan", ["Scanning for 10 seconds...", "Put the device in pairing mode now."])
        row = self.tui.choose(
            "Pair Device",
            self.bt.pairing_rows(),
            "No unconnected controllers, audio devices, or Bluetooth peripherals found.",
        )
        if not row:
            return
        def action():
            output = []
            def finish(code):
                append_log(PAIRING_LOG, [f"pair target: {row.get('name')} ({row.get('mac')})", *output])
                return code, "\n".join([line for line in output if line]), ""
            if not row.get("paired"):
                code, out, err = self.bt.pair(row["mac"])
                output.append(f"$ bluetoothctl pair {row['mac']}")
                output.extend([out, err])
                if code != 0:
                    if self.bt.paired_or_bonded(row["mac"]):
                        output.append("Pairing reported an error, but BlueZ now reports the device is paired. Continuing.")
                    else:
                        return finish(code)
            for args in (("trust", row["mac"]), ("wake", row["mac"], "on")):
                code, out, err = self.bt.action(*args, timeout=20)
                output.append(f"$ bluetoothctl {' '.join(args)}")
                output.extend([out, err])
                if code != 0 and args[0] != "wake":
                    return finish(code)
            code, out, err = self.bt.action("connect", row["mac"], timeout=35)
            output.append(f"$ bluetoothctl connect {row['mac']}")
            output.extend([out, err])
            if code != 0:
                if self.bt.connected_mac(row["mac"]):
                    output.append("Connect reported an error, but BlueZ now reports the device is connected.")
                else:
                    return finish(code)
            run_cmd(["systemctl", "start", "--no-block", "controller-leds-apply.service"], timeout=8)
            return finish(0)
        self.run_and_show("Pair Device", action)

    def bluetooth_connect_paired(self):
        row = self.tui.choose("Connect Device", self.bt.paired_rows(), "No paired devices.")
        if row:
            def action():
                output = []
                def finish(code):
                    append_log(PAIRING_LOG, [f"connect target: {row.get('name')} ({row.get('mac')})", *output])
                    return code, "\n".join([line for line in output if line]), ""
                for args in (("trust", row["mac"]), ("wake", row["mac"], "on"), ("connect", row["mac"])):
                    code, out, err = self.bt.action(*args, timeout=25)
                    output.append(f"$ bluetoothctl {' '.join(args)}")
                    output.extend([out, err])
                    if code != 0 and args[0] == "connect":
                        if self.bt.connected_mac(row["mac"]):
                            output.append("Connect reported an error, but BlueZ now reports the device is connected.")
                            break
                        return finish(code)
                    if code != 0 and args[0] != "wake":
                        return finish(code)
                run_cmd(["systemctl", "start", "--no-block", "controller-leds-apply.service"], timeout=8)
                return finish(0)
            self.run_and_show("Connect Device", action)

    def bluetooth_disconnect(self):
        devices = self.bt.devices("Connected")
        row = self.tui.choose("Disconnect Device", [{"label": d["name"], "desc": d["mac"], **d} for d in devices], "No connected devices.")
        if row:
            self.run_and_show("Disconnect Device", lambda: self.bt.action("disconnect", row["mac"], timeout=20))

    def bluetooth_unpair(self):
        row = self.tui.choose("Unpair Device", self.bt.paired_rows(), "No paired devices.")
        if row and self.tui.confirm("Unpair Device", [row["name"], row["mac"], "This removes the saved pairing."]):
            self.run_and_show("Unpair Device", lambda: self.bt.action("remove", row["mac"], timeout=20))

    def bluetooth_reconnect_all(self):
        self.tui.progress("Reconnect All", ["Connecting all paired devices..."])
        output = self.bt.reconnect_all()
        self.tui.show_output("Reconnect All", output)

    def audio_output(self):
        sinks, err = self.audio.sinks()
        rows = [{"label": "HDMI / Display Audio", "desc": "Default Boomer output", "mode": "hdmi"}]
        for sink in sinks:
            if sink.get("bluetooth"):
                rows.append({"label": sink["desc"], "desc": sink["name"], "mode": "bluetooth", "sink": sink})
        if err:
            self.tui.message = err
        row = self.tui.choose("Audio Output", rows)
        if not row:
            return
        if row["mode"] == "hdmi":
            self.run_and_show("Audio Output", self.audio.set_hdmi)
        else:
            self.run_and_show("Audio Output", lambda: self.audio.set_bluetooth(row["sink"]))

    def player_assignment(self):
        self.tui.progress("Player Assignment", ["Press any controller button or keyboard key.", "Press B/Esc to go back."])
        self.tui.clear_pending_input()
        time.sleep(0.25)
        self.tui.clear_pending_input()
        detected = None
        end = time.time() + 30
        while time.time() < end and not detected:
            event = self.tui.get_input(0.2)
            if not event:
                continue
            if event.source == "axis":
                continue
            if event.action in (ACTION_BACK, ACTION_QUIT):
                return
            if event.source == "key" and event.device and (is_mac(event.device.get("mac")) or event.device.get("name")):
                detected = event.device
            elif event.source == "keyboard" and event.action not in (
                ACTION_UP,
                ACTION_DOWN,
                ACTION_LEFT,
                ACTION_RIGHT,
                ACTION_REFRESH,
                ACTION_ALT,
            ):
                detected = {"event": "keyboard", "name": "Keyboard", "mac": "KEYBOARD"}
        if not detected:
            self.tui.show_output("Player Assignment", ["No input detected."])
            return
        order = read_json(PLAYER_ORDER, {"players": []})
        mac = mac_key(detected.get("mac"))
        name = detected.get("name") or "Unknown controller"
        players = order.get("players", [])
        current = next((p for p in players if mac and mac_key(p.get("mac")) == mac), None)
        current_slot = f"P{current.get('player')}" if current else "unassigned"
        slot_lines = []
        for slot in range(1, 5):
            occupant = next((row for row in players if int(row.get("player", 0) or 0) == slot), None)
            slot_lines.append(f"P{slot}: {occupant.get('name') if occupant else 'empty'}")
        base_lines = [
            f"Detected: {name}",
            f"ID: {mac or 'unknown'}",
            f"Current slot: {current_slot}",
            "",
            "Slots:",
            *slot_lines,
        ]
        items = []
        for slot in range(1, 5):
            occupant = next((row for row in players if int(row.get("player", 0) or 0) == slot), None)
            target_lines = [
                *base_lines,
                "",
                f"Target: Player {slot}",
                f"Current occupant: {occupant.get('name') if occupant else 'empty'}",
                "Selecting this slot swaps controllers if occupied.",
            ]
            items.append({"label": f"Assign to Player {slot}", "detail_only": True, "detail": target_lines, "row": {"slot": slot}})
        self.tui.message = f"{name}: current slot {current_slot}"
        choice = self.tui.menu("Player Assignment", items)
        if not choice or choice == "refresh":
            return
        self.assign_player(mac, name, choice["row"]["slot"])

    def assign_player(self, mac, name, slot):
        order = read_json(PLAYER_ORDER, {"players": []})
        write_json(PLAYER_ORDER, assign_player_order(order, mac, name, slot))
        run_cmd(["systemctl", "start", "--no-block", "controller-leds-apply.service"], timeout=8)
        self.tui.show_output("Player Assignment", [f"{name} assigned to Player {slot}.", "Controller LEDs updated."])

    def wifi_menu(self):
        while self.tui.running:
            status = self.wifi.status_lines()
            allow_24 = self.wifi.policy().get("allow_24ghz", False)
            items = [
                {
                    "label": "Status",
                    "detail_only": True,
                    "detail": status,
                    "action": self.wifi_status,
                },
                {
                    "label": "Wi-Fi On",
                    "desc": "Enable the Wi-Fi radio.",
                    "detail": ["Turns the Wi-Fi radio on."],
                    "action": lambda: self.run_and_show("Wi-Fi On", lambda: run_cmd(["nmcli", "radio", "wifi", "on"], timeout=12)),
                },
                {
                    "label": "Wi-Fi Off",
                    "desc": "Disable the Wi-Fi radio.",
                    "detail": ["This can disconnect SSH if Wi-Fi is the active network."],
                    "action": self.wifi_off,
                },
                {
                    "label": "Restart Wi-Fi",
                    "desc": "Cycle Wi-Fi radio and reapply the 2.4/5 GHz policy.",
                    "detail": ["Use this after changing networks or radio policy."],
                    "action": self.wifi_restart,
                },
                {
                    "label": "Connect Saved Network",
                    "desc": "Connect an existing NetworkManager Wi-Fi profile.",
                    "detail": ["Uses a saved profile, then reapplies the band policy."],
                    "action": self.wifi_connect_saved,
                },
                {
                    "label": "Connect New Network",
                    "desc": "Scan nearby networks and enter a password with keyboard or controller.",
                    "detail": ["Starts a fresh scan, then saves the selected network."],
                    "action": self.wifi_connect_new,
                },
                {
                    "label": "Disconnect Network",
                    "desc": "Disconnect the active Wi-Fi device.",
                    "detail": ["Leaves saved profiles intact."],
                    "action": self.wifi_disconnect,
                },
                {
                    "label": "Forget Network",
                    "desc": "Delete a saved Wi-Fi profile.",
                    "detail": ["Use this to remove stale or unwanted saved networks."],
                    "action": self.wifi_forget,
                },
                {
                    "label": "2.4 GHz Toggle",
                    "desc": "Allow or disable 2.4 GHz Wi-Fi.",
                    "detail": [
                        f"Current policy: {'2.4/5 GHz allowed' if allow_24 else '5 GHz only'}",
                        "2.4 GHz can reduce Bluetooth controller and headphone performance.",
                    ],
                    "action": self.wifi_toggle_24,
                },
            ]
            choice = self.tui.menu("Wi-Fi Settings", items)
            if not choice:
                return
            if choice == "refresh":
                continue
            choice["action"]()

    def wifi_status(self):
        _, ip, _ = run_cmd(["nmcli", "-f", "IP4", "device", "show"], timeout=8)
        self.tui.show_output("Wi-Fi Status", [*self.wifi.status_lines(), "", ip])

    def wifi_off(self):
        if self.tui.confirm("Wi-Fi Off", ["This can disconnect SSH if Wi-Fi is the active network.", "Turn Wi-Fi off?"]):
            self.run_and_show("Wi-Fi Off", lambda: run_cmd(["nmcli", "radio", "wifi", "off"], timeout=12))

    def wifi_restart(self):
        def action():
            out = []
            for args in (["nmcli", "radio", "wifi", "off"], ["nmcli", "radio", "wifi", "on"]):
                code, stdout, stderr = run_cmd(args, timeout=12)
                out.extend([stdout, stderr])
                if code != 0:
                    return code, "\n".join([line for line in out if line]), ""
                time.sleep(2)
            code, stdout, stderr = self.wifi.apply_policy()
            out.extend([stdout, stderr])
            return code, "\n".join([line for line in out if line]), ""
        self.run_and_show("Restart Wi-Fi", action)

    def wifi_connect_saved(self):
        rows = [
            {"label": p["name"], "desc": f"{p['uuid']} {p.get('device', '')}", **p}
            for p in self.wifi.saved_profiles()
        ]
        row = self.tui.choose("Connect Saved Network", rows, "No saved Wi-Fi profiles.")
        if row:
            self.run_and_show("Connect Saved Network", lambda: self.wifi.connect_saved(row["uuid"]))

    def wifi_connect_new(self):
        self.tui.progress("Wi-Fi Scan", ["Scanning nearby networks..."])
        networks = self.wifi.networks()
        rows = []
        for net in networks:
            rows.append({
                "label": net["ssid"],
                "desc": f"{net['signal']}%  ch {net['channel']}  {net['security'] or 'open'}",
                **net,
            })
        row = self.tui.choose("Connect New Network", rows, "No Wi-Fi networks found.")
        if not row:
            return
        password = None
        if row.get("security") and row.get("security") not in ("--", ""):
            password = self.tui.prompt_text("Wi-Fi Password", f"Password for {row['ssid']}", hidden=True)
            if password is None:
                return
        self.run_and_show("Connect New Network", lambda: self.wifi.connect_network(row["ssid"], password))

    def wifi_disconnect(self):
        rows = [
            {"label": p["name"], "desc": p.get("device", ""), **p}
            for p in self.wifi.active_profiles()
            if p.get("device")
        ]
        row = self.tui.choose("Disconnect Network", rows, "No active Wi-Fi network.")
        if row:
            self.run_and_show("Disconnect Network", lambda: self.wifi.disconnect(row["device"]))

    def wifi_forget(self):
        rows = [{"label": p["name"], "desc": p["uuid"], **p} for p in self.wifi.saved_profiles()]
        row = self.tui.choose("Forget Network", rows, "No saved Wi-Fi profiles.")
        if row and self.tui.confirm("Forget Network", [row["name"], "This deletes the saved Wi-Fi profile."]):
            self.run_and_show("Forget Network", lambda: self.wifi.forget(row["uuid"]))

    def wifi_toggle_24(self):
        allow = self.wifi.policy().get("allow_24ghz", False)
        if not allow:
            ok = self.tui.confirm(
                "Enable 2.4 GHz",
                [
                    "Warning: 2.4 GHz Wi-Fi can reduce Bluetooth controller",
                    "and headphone performance on shared radios.",
                    "Enable 2.4 GHz anyway?",
                ],
            )
            if not ok:
                return
        self.run_and_show("2.4 GHz Toggle", lambda: self.wifi.write_policy(not allow))


def smoke_test(mode):
    if mode == "bluetooth":
        sample = "Device AA:BB:CC:DD:EE:FF Switch Pro Controller\nDevice 11:22:33:44:55:66 Headphones"
        scan_sample = "\x1b[0;92m[NEW]\x1b[0m Device 22:33:44:55:66:77 8BitDo Ultimate Controller\n[CHG] Device 22:33:44:55:66:77 RSSI: -62"
        show = """Controller 4C:24:CE:FA:E3:2A
    Name: boomer-kuwanger
    Powered: yes
    Discoverable: no
    Pairable: no
    Discovering: no
"""
        labels_on = bluetooth_visible_labels(True)
        labels_off = bluetooth_visible_labels(False)
        adapter_lines = parse_bluetooth_adapter_lines(show)
        assert "Bluetooth Toggle" in labels_on
        assert labels_on[:2] == ["Status", "Show Paired"]
        assert "Restart Bluetooth" in labels_on
        assert "Restart Bluetooth" not in labels_off
        assert "Scanning: No" in adapter_lines
        assert not any("Discoverable" in line or "Pairable" in line for line in adapter_lines)
        assert is_controller_name("Nintendo Switch Pro Controller")
        assert is_controller_name("Nintendo.Co.Ltd. Pro Controller")
        assert is_controller_name("8BitDo Ultimate Wireless Controller")
        assert not is_controller_name("Pro Controller (IMU)")
        assert not is_controller_name("AMIRA-KEYBOAR USB KEYBOARD")
        assert not is_controller_name("AMIRA-KEYBOAR USB KEYBOARD Mouse")
        assert capability_has_bit("3001b", 16)
        assert capability_has_bit("3001b", 17)
        assert not capability_has_bit("3f", 16)
        assert not capability_has_any_bit("0 0 0")
        assert looks_pairable_for_boomer(
            {"name": "Pro Controller"},
            "Icon: input-gaming\nModalias: usb:v057Ep2009d0001\nPaired: no",
        )
        assert looks_pairable_for_boomer({"name": "Headphones"}, "UUID: Audio Sink\nPaired: yes")
        assert not looks_pairable_for_boomer({"name": "Living Room TV"}, "Icon: video-display\nPaired: no")
        reader = ControllerReader(queue.Queue())
        emitted = []
        reader.emit = lambda action, path, source: emitted.append((action, source))
        reader.handle_event("/dev/input/event0", EV_KEY, 304, 1)
        reader.handle_event("/dev/input/event0", EV_KEY, 305, 1)
        reader.handle_event("/dev/input/event0", EV_KEY, 307, 1)
        reader.handle_event("/dev/input/event0", EV_KEY, 308, 1)
        assert emitted == [(ACTION_BACK, "key"), (ACTION_SELECT, "key"), (ACTION_REFRESH, "key"), (ACTION_ALT, "key")]
        emitted.clear()
        reader.handle_event("/dev/input/event0", EV_KEY, 314, 1)
        assert emitted == []
        reader.handle_event("/dev/input/event0", EV_ABS, 1, 16000)
        assert emitted == [(ACTION_DOWN, "axis")]
        order = {
            "players": [
                {"player": 1, "mac": "AA:AA:AA:AA:AA:01", "name": "P1"},
                {"player": 2, "mac": "AA:AA:AA:AA:AA:02", "name": "P2"},
                {"player": 3, "mac": "AA:AA:AA:AA:AA:03", "name": "P3"},
            ]
        }
        swapped = assign_player_order(order, "AA:AA:AA:AA:AA:02", "P2", 3)
        by_mac = {row["mac"]: row["player"] for row in swapped["players"]}
        assert by_mac["AA:AA:AA:AA:AA:02"] == 3
        assert by_mac["AA:AA:AA:AA:AA:03"] == 2
        assert parse_bt_devices(scan_sample) == [
            {"mac": "22:33:44:55:66:77", "name": "8BitDo Ultimate Controller"}
        ]
        metrics = pane_metrics(26, 92)
        worst_connected = [
            {"mac": f"AA:BB:CC:DD:EE:0{slot}", "name": f"Controller With A Long Friendly Name {slot}"}
            for slot in range(1, 5)
        ]
        worst_connected.append({"mac": "11:22:33:44:55:66", "name": "Bluetooth Headphones With A Long Friendly Name"})
        worst_players = [
            {"player": slot, "mac": f"AA:BB:CC:DD:EE:0{slot}", "name": f"Controller With A Long Friendly Name {slot}"}
            for slot in range(1, 5)
        ]
        worst_status = format_bluetooth_status(
            adapter_lines,
            worst_connected,
            worst_connected,
            worst_players,
            "Bluetooth Headphones With A Long Friendly Name",
        )
        assert len(wrap_lines(worst_status, metrics["right_width"])) <= metrics["content_height"]
        start, end = menu_window(len(labels_on), len(labels_on) - 1, metrics["content_height"])
        assert 0 <= start < end <= len(labels_on)
        assert metrics["content_bottom"] < 26
        assert metrics["right_x"] + metrics["right_width"] < 92
        print(json.dumps({"devices": parse_bt_devices(sample), "labels_on": labels_on, "adapter": adapter_lines}, indent=2))
    elif mode == "wifi":
        sample = "SKYNET:WPA2:88:149:*\nGuest::52:6:"
        rows = parse_nmcli_rows(sample)
        metrics = pane_metrics(26, 92)
        start, end = menu_window(9, 8, metrics["content_height"])
        assert 0 <= start < end <= 9
        assert metrics["content_bottom"] < 26
        assert metrics["right_x"] + metrics["right_width"] < 92
        print(json.dumps({"rows": rows, "layout": metrics}, indent=2))
    else:
        metrics = pane_metrics(26, 92)
        expected = {
            "Switch Pro Reference",
            "NES / Famicom",
            "SNES / Super Famicom",
            "Game Boy / Color",
            "Game Boy Advance",
            "Virtual Boy",
            "Genesis / Saturn",
            "Master System / Game Gear",
            "Dreamcast",
            "PC Engine / CD",
            "Neo Geo / Pocket",
            "PlayStation",
            "Nintendo 64",
            "GameCube",
            "Wii Remote + Nunchuk",
            "Wii Classic",
            "Wii U",
            "Xbox",
            "PSP",
            "DS / 3DS",
            "Switch",
            "Arcade",
            "GZDoom",
            "PICO-8",
        }
        labels = {row["label"] for row in CONTROLLER_MAPS}
        assert expected <= labels
        assert CONTROLLER_MAPS[0]["label"] == "Switch Pro Reference"
        for row in CONTROLLER_MAPS:
            wrapped = wrap_lines(row["detail"], metrics["right_width"])
            assert wrapped
            assert len(wrapped) <= metrics["content_height"]
            assert all(len(line) <= metrics["right_width"] for line in wrapped)
            assert "Button Map" in row["detail"]
            assert "Hotkeys" in row["detail"]
            assert any("Star" in line for line in row["detail"])
            assert any("Select + Start twice" in line for line in row["detail"])
            assert any("Square" in line for line in row["detail"])
            assert not any("opens RetroArch quick menu" in line for line in row["detail"])
            if row["label"] != "GZDoom":
                assert any("Quick Menu: Select + X" in line for line in row["detail"])
            assert not any("Original Controller" in line or "+---" in line for line in row["detail"])
        n64 = next(row for row in CONTROLLER_MAPS if row["label"] == "Nintendo 64")
        assert any("A -> A" in line for line in n64["detail"])
        assert any("B -> B" in line for line in n64["detail"])
        wii = next(row for row in CONTROLLER_MAPS if row["label"] == "Wii Remote + Nunchuk")
        assert any("Square -> Console Home" in line for line in wii["detail"])
        for row in CONTROLLER_MAPS:
            if row["label"] in {"Switch Pro Reference", "Wii Remote + Nunchuk", "GZDoom"}:
                continue
            assert any("Square -> None" in line for line in row["detail"])
        gzdoom = next(row for row in CONTROLLER_MAPS if row["label"] == "GZDoom")
        assert any("Use/Confirm -> A" in line for line in gzdoom["detail"])
        assert any("Move -> Left Stick/D-pad" in line for line in gzdoom["detail"])
        assert any("Look -> Right Stick" in line for line in gzdoom["detail"])
        assert any("Map Toggle -> Minus" in line for line in gzdoom["detail"])
        assert any("Crouch Toggle -> Y" in line for line in gzdoom["detail"])
        assert any("X -> No-op" in line for line in gzdoom["detail"])
        assert any("Map Pan -> Left Stick/D-pad" in line for line in gzdoom["detail"])
        assert any("Prev Weapon -> L1" in line for line in gzdoom["detail"])
        assert any("Next Weapon -> R1" in line for line in gzdoom["detail"])
        assert any("Menu -> Plus" in line for line in gzdoom["detail"])
        assert any("Square -> None" in line for line in gzdoom["detail"])
        assert metrics["right_x"] + metrics["right_width"] < 92
        print(json.dumps({"maps": [row["label"] for row in CONTROLLER_MAPS], "layout": metrics}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["bluetooth", "wifi", "maps"])
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test(args.mode)
        return 0
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    def runner(stdscr):
        app = SettingsApp(Tui(stdscr, args.mode))
        app.run()
    curses.wrapper(runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
