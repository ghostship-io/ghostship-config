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
AUDIO_PREF = CONFIG_ROOT / "audio" / "output.json"
PLAYER_ORDER = CONFIG_ROOT / "controllers" / "player-order.json"
WIFI_POLICY = CONFIG_ROOT / "network" / "wifi-policy.json"

EV_KEY = 0x01
EV_ABS = 0x03
BTN_MISC = 0x100
EVENT_STRUCT = struct.Struct("@llHHi")

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


def mac_key(value):
    return value.upper() if value else ""


def is_mac(value):
    return bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", value or ""))


def parse_bt_devices(output):
    devices = []
    for line in output.splitlines():
        stripped = ANSI_RE.sub("", line.strip())
        match = re.match(r"^(?:\[NEW\]\s+)?Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", stripped)
        if match:
            devices.append({"mac": mac_key(match.group(1)), "name": match.group(2).strip()})
    return devices


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
    labels = ["Status", "Bluetooth Toggle"]
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
    try:
        name = (base / "name").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    try:
        uniq = (base / "uniq").read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    return {"event": event_path, "name": name or Path(event_path).name, "mac": mac_key(uniq)}


def is_controller_event_device(event_path):
    return is_controller_name(controller_device_info(event_path).get("name", ""))


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

    def emit(self, action, path):
        self.events.put(InputEvent(action=action, device=controller_device_info(path)))

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
                304: ACTION_SELECT,
                305: ACTION_BACK,
                307: ACTION_ALT,
                308: ACTION_REFRESH,
                314: ACTION_BACK,
                315: ACTION_SELECT,
            }
            action = key_map.get(code)
            if action:
                self.emit(action, path)
            elif code >= BTN_MISC:
                self.emit(ACTION_SELECT, path)
        elif ev_type == EV_ABS and code in (0, 1, 16, 17):
            if code in (0, 16):
                action = ACTION_LEFT if value < 0 else ACTION_RIGHT if value > 0 else None
            else:
                action = ACTION_UP if value < 0 else ACTION_DOWN if value > 0 else None
            key = (path, code)
            if action and self.last_abs.get(key) != value:
                self.emit(action, path)
            self.last_abs[key] = value

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
        footer = "Move: D-pad/Arrows/WASD  Select: A/Enter  Back: B/Esc  Refresh: X/R"
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

    def draw_two_pane(self, title, items, selected, detail_lines):
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
        for row, line in enumerate(right_lines[: metrics["content_height"]], start=top):
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
                return InputEvent(ACTION_UP)
            if ch in (curses.KEY_DOWN, ord("s"), ord("S")):
                return InputEvent(ACTION_DOWN)
            if ch in (curses.KEY_LEFT, ord("a"), ord("A")):
                return InputEvent(ACTION_LEFT)
            if ch in (curses.KEY_RIGHT, ord("d"), ord("D")):
                return InputEvent(ACTION_RIGHT)
            if ch in (10, 13, curses.KEY_ENTER):
                return InputEvent(ACTION_SELECT)
            if ch in (27,):
                return InputEvent(ACTION_BACK)
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                return InputEvent("\b")
            if ch in (ord("r"), ord("R")):
                return InputEvent(ACTION_REFRESH)
            if ch in (ord("y"), ord("Y"), ord("x"), ord("X")):
                return InputEvent(ACTION_ALT if ch in (ord("y"), ord("Y")) else ACTION_REFRESH)
            if ch in (ord("q"), ord("Q")):
                return InputEvent(ACTION_QUIT)
            if 32 <= ch <= 126:
                return InputEvent(chr(ch))
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
                return InputEvent(ACTION_UP)
            if ch == curses.KEY_DOWN:
                return InputEvent(ACTION_DOWN)
            if ch == curses.KEY_LEFT:
                return InputEvent(ACTION_LEFT)
            if ch == curses.KEY_RIGHT:
                return InputEvent(ACTION_RIGHT)
            if ch in (10, 13, curses.KEY_ENTER):
                return InputEvent(ACTION_SELECT)
            if ch == 27:
                return InputEvent(ACTION_BACK)
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                return InputEvent("\b")
            if 32 <= ch <= 126:
                return InputEvent(chr(ch))
        return None

    def menu(self, title, items, details=None, selected=0):
        selected = max(0, min(selected, len(items) - 1)) if items else 0
        while self.running:
            item = items[selected] if items else None
            self.draw_two_pane(title, items, selected, self.item_detail_lines(item, details))
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
            elif event.action == ACTION_DOWN and items:
                selected = (selected + 1) % len(items)
            elif event.action == ACTION_SELECT and items:
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
            else:
                self.wifi_menu()
        finally:
            self.tui.stop()

    def run_and_show(self, title, func):
        self.tui.progress(title, ["Working..."])
        code, out, err = func()
        self.tui.message = "OK" if code == 0 else f"Failed with exit {code}"
        self.tui.show_output(title, [out, err])

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

    def bluetooth_scan_pair(self):
        self.tui.progress("Bluetooth Scan", ["Scanning for 10 seconds...", "Put the device in pairing mode now."])
        devices = self.bt.scan()
        row = self.tui.choose(
            "Pair Device",
            [{"label": d["name"], "desc": d["mac"], **d} for d in devices],
            "No Bluetooth devices found.",
        )
        if not row:
            return
        def action():
            output = []
            for args in (("pair", row["mac"]), ("trust", row["mac"]), ("connect", row["mac"])):
                if args[0] == "pair":
                    code, out, err = self.bt.pair(row["mac"])
                else:
                    code, out, err = self.bt.action(*args, timeout=35)
                output.append(f"$ bluetoothctl {' '.join(args)}")
                output.extend([out, err])
                if code != 0 and args[0] == "pair":
                    break
            return 0, "\n".join([line for line in output if line]), ""
        self.run_and_show("Pair Device", action)

    def bluetooth_connect_paired(self):
        row = self.tui.choose("Connect Device", self.bt.paired_rows(), "No paired devices.")
        if row:
            self.run_and_show("Connect Device", lambda: self.bt.action("connect", row["mac"], timeout=25))

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
        detected = None
        end = time.time() + 30
        while time.time() < end and not detected:
            event = self.tui.get_input(0.2)
            if not event:
                continue
            if event.action in (ACTION_BACK, ACTION_QUIT):
                return
            if event.device and (is_mac(event.device.get("mac")) or event.device.get("name")):
                detected = event.device
            elif event.action != ACTION_REFRESH:
                detected = {"event": "keyboard", "name": "Keyboard", "mac": "KEYBOARD"}
        if not detected:
            self.tui.show_output("Player Assignment", ["No input detected."])
            return
        order = read_json(PLAYER_ORDER, {"players": []})
        mac = mac_key(detected.get("mac"))
        name = detected.get("name") or "Unknown controller"
        players = order.get("players", [])
        current = next((p for p in players if mac and mac_key(p.get("mac")) == mac), None)
        lines = [f"Detected: {name}", f"MAC: {mac or 'unknown'}", f"Current slot: P{current.get('player')}" if current else "Current slot: unassigned"]
        items = [
            {"label": f"Assign to Player {slot}", "desc": "Swap if occupied", "row": {"slot": slot}}
            for slot in range(1, 5)
        ]
        choice = self.tui.menu("Choose Player Slot", items, lines)
        if not choice or choice == "refresh":
            return
        self.assign_player(mac, name, choice["row"]["slot"])

    def assign_player(self, mac, name, slot):
        order = read_json(PLAYER_ORDER, {"players": []})
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
        write_json(PLAYER_ORDER, {"players": players})
        run_cmd(["systemctl", "restart", "controller-leds.service"], timeout=15)
        self.tui.show_output("Player Assignment", [f"{name} assigned to Player {slot}.", "Controller LED service restarted."])

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
        assert "Restart Bluetooth" in labels_on
        assert "Restart Bluetooth" not in labels_off
        assert "Scanning: No" in adapter_lines
        assert not any("Discoverable" in line or "Pairable" in line for line in adapter_lines)
        assert is_controller_name("Nintendo Switch Pro Controller")
        assert is_controller_name("8BitDo Ultimate Wireless Controller")
        assert not is_controller_name("AMIRA-KEYBOAR USB KEYBOARD")
        assert not is_controller_name("AMIRA-KEYBOAR USB KEYBOARD Mouse")
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
    else:
        sample = "SKYNET:WPA2:88:149:*\nGuest::52:6:"
        rows = parse_nmcli_rows(sample)
        metrics = pane_metrics(26, 92)
        start, end = menu_window(9, 8, metrics["content_height"])
        assert 0 <= start < end <= 9
        assert metrics["content_bottom"] < 26
        assert metrics["right_x"] + metrics["right_width"] < 92
        print(json.dumps({"rows": rows, "layout": metrics}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["bluetooth", "wifi"])
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
