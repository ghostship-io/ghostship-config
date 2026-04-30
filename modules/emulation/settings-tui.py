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
        match = re.match(r"^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line.strip())
        if match:
            devices.append({"mac": mac_key(match.group(1)), "name": match.group(2).strip()})
    return devices


def parse_nmcli_rows(output):
    rows = []
    for line in output.splitlines():
        if line.strip():
            rows.append(line.rstrip("\n").split(":"))
    return rows


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


class ControllerReader(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True)
        self.events = events
        self.stop_event = threading.Event()
        self.fds = {}
        self.last_abs = {}

    def refresh_devices(self):
        wanted = set(glob.glob("/dev/input/event*"))
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
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_GREEN, -1)
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

    def draw_frame(self, title, subtitle=""):
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        self.add(0, 0, " " * (width - 1), curses.color_pair(1))
        self.add(0, 2, title.upper(), curses.color_pair(1) | curses.A_BOLD)
        if subtitle:
            self.add(1, 2, subtitle, curses.color_pair(3))
        footer = "Controller: D-pad move  A select  B back  X refresh  Y action | Keyboard: arrows/WASD enter esc r"
        self.add(height - 2, 0, " " * (width - 1), curses.color_pair(1))
        self.add(height - 2, 2, footer, curses.color_pair(1))
        self.add(height - 1, 2, self.message, curses.color_pair(5) if "OK" in self.message else curses.color_pair(3))

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
        details = details or []
        while self.running:
            self.draw_frame(title)
            y = 3
            for line in details[:8]:
                self.add(y, 2, line)
                y += 1
            y += 1
            if not items:
                self.add(y, 4, "No items available.", curses.color_pair(4))
            for index, item in enumerate(items):
                attr = curses.color_pair(2) | curses.A_BOLD if index == selected else curses.A_NORMAL
                marker = ">" if index == selected else " "
                self.add(y + index * 2, 2, f"{marker} {item['label']}", attr)
                if item.get("desc"):
                    self.add(y + index * 2 + 1, 6, item["desc"], curses.color_pair(3))
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
            height, _ = self.stdscr.getmaxyx()
            for row, line in enumerate(lines[top : top + height - 6], start=3):
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
                top = min(max(0, len(lines) - 1), top + 1)

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
        for index, line in enumerate(lines, start=4):
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
        lines = []
        for wanted in ("Powered:", "Discoverable:", "Pairable:", "Discovering:"):
            for line in out.splitlines():
                if line.strip().startswith(wanted):
                    lines.append(line.strip())
        if err:
            lines.append(err)
        return lines or ["Bluetooth adapter not found."]

    def paired_rows(self):
        connected = {d["mac"] for d in self.devices("Connected")}
        rows = []
        for device in self.devices("Paired"):
            state = "connected" if device["mac"] in connected else "paired"
            rows.append({"label": device["name"], "desc": f"{device['mac']} - {state}", **device})
        return rows

    def scan(self, seconds=8):
        run_cmd(["bluetoothctl", "power", "on"], timeout=8)
        run_cmd(["bluetoothctl", "agent", "KeyboardDisplay"], timeout=8)
        run_cmd(["bluetoothctl", "default-agent"], timeout=8)
        run_cmd(["bluetoothctl", "pairable", "on"], timeout=8)
        run_cmd(["bluetoothctl", "scan", "on"], timeout=8)
        time.sleep(seconds)
        run_cmd(["bluetoothctl", "scan", "off"], timeout=8)
        seen = {d["mac"]: d for d in self.devices()}
        return sorted(seen.values(), key=lambda row: row["name"].lower())

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
        _, devices, _ = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], timeout=8)
        _, active, _ = run_cmd(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], timeout=8)
        policy = self.policy()
        lines.append("2.4 GHz: " + ("allowed" if policy.get("allow_24ghz") else "disabled for Bluetooth performance"))
        lines.extend(radio.splitlines()[:3])
        lines.extend(devices.splitlines()[:4])
        if active:
            lines.append("Active:")
            lines.extend(active.splitlines()[:3])
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
            pref = self.audio.preference()
            details = self.bt.adapter_summary()
            details.append("Audio output: " + (pref.get("description") or pref.get("mode", "hdmi")))
            items = [
                {"label": "Status", "desc": "Bluetooth, paired devices, connected devices, player order", "action": self.bluetooth_status},
                {"label": "Bluetooth On", "desc": "Power on the adapter", "action": lambda: self.run_and_show("Bluetooth On", lambda: self.bt.action("power", "on"))},
                {"label": "Bluetooth Off", "desc": "Power off the adapter", "action": lambda: self.run_and_show("Bluetooth Off", lambda: self.bt.action("power", "off"))},
                {"label": "Restart Bluetooth", "desc": "Restart bluetooth.service", "action": lambda: self.run_and_show("Restart Bluetooth", self.bt.restart_service)},
                {"label": "Scan And Pair Device", "desc": "Pair controllers, headphones, Wiimotes, keyboards, or accessories", "action": self.bluetooth_scan_pair},
                {"label": "Connect Paired Device", "desc": "Connect one saved device", "action": self.bluetooth_connect_paired},
                {"label": "Disconnect Device", "desc": "Disconnect one connected device", "action": self.bluetooth_disconnect},
                {"label": "Reconnect All", "desc": "Trust and connect all paired devices", "action": self.bluetooth_reconnect_all},
                {"label": "Unpair Device", "desc": "Remove a saved Bluetooth device", "action": self.bluetooth_unpair},
                {"label": "Player Assignment", "desc": "Press a controller button, view slot, move or swap player slots", "action": self.player_assignment},
                {"label": "Audio Output", "desc": "Choose HDMI or connected Bluetooth headphones", "action": self.audio_output},
            ]
            choice = self.tui.menu("Bluetooth Settings", items, details)
            if not choice:
                return
            if choice == "refresh":
                continue
            choice["action"]()

    def bluetooth_status(self):
        order = read_json(PLAYER_ORDER, {"players": []})
        paired = self.bt.devices("Paired")
        connected = self.bt.devices("Connected")
        lines = ["Adapter:", *self.bt.adapter_summary(), "", "Connected:"]
        lines.extend([f"{d['name']}  {d['mac']}" for d in connected] or ["None"])
        lines.extend(["", "Paired:"])
        lines.extend([f"{d['name']}  {d['mac']}" for d in paired] or ["None"])
        lines.extend(["", "Player order:"])
        for player in order.get("players", []):
            lines.append(f"P{player.get('player')}: {player.get('name')} {player.get('mac')} connected={player.get('connected')}")
        if not order.get("players"):
            lines.append("No assigned controllers.")
        self.tui.show_output("Bluetooth Status", lines)

    def bluetooth_scan_pair(self):
        self.tui.progress("Bluetooth Scan", ["Scanning for 8 seconds...", "Put the device in pairing mode now."])
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
        self.tui.progress("Player Assignment", ["Press any button on the controller you want to identify."])
        detected = None
        end = time.time() + 30
        while time.time() < end and not detected:
            event = self.tui.get_input(0.2)
            if event and event.device and (is_mac(event.device.get("mac")) or event.device.get("name")):
                detected = event.device
        if not detected:
            self.tui.show_output("Player Assignment", ["No controller input detected."])
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
            items = [
                {"label": "Status", "desc": "Radio, device, active SSID, and IP details", "action": self.wifi_status},
                {"label": "Wi-Fi On", "desc": "Enable Wi-Fi radio", "action": lambda: self.run_and_show("Wi-Fi On", lambda: run_cmd(["nmcli", "radio", "wifi", "on"], timeout=12))},
                {"label": "Wi-Fi Off", "desc": "Disable Wi-Fi radio", "action": self.wifi_off},
                {"label": "Restart Wi-Fi", "desc": "Cycle Wi-Fi radio and reapply policy", "action": self.wifi_restart},
                {"label": "Connect Saved Network", "desc": "Connect an existing NetworkManager profile", "action": self.wifi_connect_saved},
                {"label": "Connect New Network", "desc": "Scan and enter password with keyboard or controller", "action": self.wifi_connect_new},
                {"label": "Disconnect Network", "desc": "Disconnect the active Wi-Fi device", "action": self.wifi_disconnect},
                {"label": "Forget Network", "desc": "Delete a saved Wi-Fi profile", "action": self.wifi_forget},
                {"label": "2.4 GHz Toggle", "desc": "Allow or disable 2.4 GHz Wi-Fi", "action": self.wifi_toggle_24},
            ]
            choice = self.tui.menu("Wi-Fi Settings", items, self.wifi.status_lines())
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
        print(json.dumps({"devices": parse_bt_devices(sample)}, indent=2))
    else:
        sample = "SKYNET:WPA2:88:149:*\nGuest::52:6:"
        rows = parse_nmcli_rows(sample)
        print(json.dumps({"rows": rows}, indent=2))


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
