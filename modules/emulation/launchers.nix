{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  packages = config.ghostship.emulation.internal.packages;

  launcherPath = lib.makeBinPath (
    [
      packages.retroarchPackage
      pkgs.gamescope
      pkgs.gamemode
      pkgs.jq
      pkgs.mangohud
      pkgs.util-linux
      pkgs.xdg-utils
      packages.pico8Package
      packages.ryubingCanaryPackage
      packages.winePackage
      config.ghostship.emulation.internal.scripts.audioRoute
      config.ghostship.emulation.internal.scripts.controllerLeds
      displayProfile
    ]
    ++ emu.optionalPackages [
      "azahar"
      "dolphin-emu"
      "cemu"
      "xemu"
      "lime3ds"
      "pcsx2"
      "ppsspp-sdl"
    ]
    ++ lib.optional (packages.gzdoomPackage != null) packages.gzdoomPackage
    ++ lib.optional (packages.supermodelPackage != null) packages.supermodelPackage
  );

  controllerResolve = pkgs.writeShellScriptBin "controller-resolve" ''
    set -euo pipefail
    order_file="${cfg.configRoot}/controllers/player-order.json"
    runtime_dir="/run/ghostship-emulation/controllers"
    output_file="$runtime_dir/resolved-order.json"
    log_file="${cfg.dataRoot}/logs/controller-resolve.log"
    mkdir -p "$runtime_dir" "$(dirname "$log_file")"
    chown ${cfg.user}:${cfg.group} "$runtime_dir" "$(dirname "$log_file")" 2>/dev/null || true

    ${pkgs.python3}/bin/python3 - "$order_file" "$output_file" "$log_file" "${packages.ryubingCanaryPackage}/opt/ryubing-canary/libSDL3.so" <<'PY'
import ctypes
import json
import os
import re
import sys
import time
from ctypes import POINTER, Structure, c_bool, c_char_p, c_int, c_uint8, c_uint32, c_void_p
from pathlib import Path

order_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
log_path = Path(sys.argv[3])
sdl3_path = Path(sys.argv[4])

PLAYER_ID_RE = re.compile(r"^(([0-9A-F]{2}:){5}[0-9A-F]{2}|USB:[0-9A-F]{4}:[0-9A-F]{4}:.+)$")
SUPPORTED_RE = re.compile(r"(pro controller|nintendo switch pro|joy-?con|8bitdo|ultimate 2c|v057ep2009|v2dc8p(310b|301a))", re.I)
MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")

def read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""

def log(message):
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n")
    except OSError:
        pass

def usb_id_from_modalias(modalias, uniq):
    match = re.search(r"v([0-9a-fA-F]{4})p([0-9a-fA-F]{4})", modalias or "")
    if not match:
        return ""
    stable = re.sub(r"[^A-Za-z0-9_.:-]", "_", uniq or "unknown")
    return f"USB:{match.group(1).upper()}:{match.group(2).upper()}:{stable}"

def identity(uniq, modalias):
    uniq = (uniq or "").upper()
    if MAC_RE.match(uniq):
        return uniq
    return usb_id_from_modalias(modalias, uniq)

def modalias_bus(modalias):
    match = re.search(r"input:b([0-9a-fA-F]{4})", modalias or "")
    return match.group(1).lower() if match else ""

def modalias_vid_pid(modalias):
    match = re.search(r"v([0-9a-fA-F]{4})p([0-9a-fA-F]{4})", modalias or "")
    if not match:
        return "", ""
    return match.group(1).upper(), match.group(2).upper()

def ryubing_guid_from_sdl(raw_guid):
    raw = "".join(ch for ch in (raw_guid or "").lower() if ch in "0123456789abcdef")
    if len(raw) != 32:
        return ""
    guid = f"{raw[4:6]}{raw[6:8]}{raw[2:4]}{raw[0:2]}-{raw[10:12]}{raw[8:10]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return "0000" + guid[4:]

def stable_ryubing_guid(raw_guid, modalias):
    return ryubing_guid_from_sdl(raw_guid)

def transport_from_bus(bus):
    if bus == "0005":
        return "bluetooth"
    if bus == "0003":
        return "usb"
    return "unknown"

def bluez_devices():
    try:
        import subprocess

        proc = subprocess.run(
            [
                "${pkgs.systemd}/bin/busctl",
                "--system",
                "--json=short",
                "call",
                "org.bluez",
                "/",
                "org.freedesktop.DBus.ObjectManager",
                "GetManagedObjects",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception as exc:
        log(f"could not query BlueZ devices: {exc}")
        return {}
    if proc.returncode != 0:
        log("could not query BlueZ devices")
        return {}
    try:
        root = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        log(f"could not parse BlueZ devices: {exc}")
        return {}
    devices = {}
    for entry in root.get("data", [{}])[0].values():
        device = entry.get("org.bluez.Device1")
        if not device:
            continue
        address = str(device.get("Address", {}).get("data") or "").upper()
        if not MAC_RE.match(address):
            continue
        devices[address] = {
            "bluez_connected": bool(device.get("Connected", {}).get("data", False)),
            "bluez_paired": bool(device.get("Paired", {}).get("data", device.get("Bonded", {}).get("data", False))),
            "bluez_name": str(device.get("Alias", {}).get("data") or device.get("Name", {}).get("data") or ""),
            "bluez_modalias": str(device.get("Modalias", {}).get("data") or "").lower(),
        }
    return devices

def sysfs_devices():
    bluez = bluez_devices()
    devices = {}
    events = sorted(Path("/sys/class/input").glob("event*"), key=lambda p: p.name)
    sdl_index = 0
    for event in events:
        name = read(event / "device/name")
        if not name or "imu" in name.lower():
            continue
        modalias = read(event / "device/modalias").lower()
        bus = modalias_bus(modalias)
        if bus not in {"0003", "0005"}:
            continue
        if not SUPPORTED_RE.search(f"{name} {modalias}"):
            continue
        uniq = read(event / "device/uniq")
        ident = identity(uniq, modalias)
        if not ident or not PLAYER_ID_RE.match(ident):
            continue
        bluez_state = bluez.get(ident, {})
        transport = transport_from_bus(bus)
        if transport == "bluetooth" and not bluez_state.get("bluez_connected", False):
            continue
        vid, pid = modalias_vid_pid(modalias)
        devices.setdefault(ident, {
            "identity": ident,
            "name": name,
            "transport": transport,
            "bus": bus,
            "vid": vid,
            "pid": pid,
            "bluez_connected": bool(bluez_state.get("bluez_connected", False)),
            "bluez_paired": bool(bluez_state.get("bluez_paired", False)),
            "event_path": f"/dev/input/{event.name}",
            "sysfs_event": str(event),
            "modalias": modalias,
            "sdl2_index": sdl_index,
            "sdl3_index": sdl_index,
            "sdl_guid": "",
            "xemu_guid": ident,
        })
        sdl_index += 1
    return devices

class SdlGuid(Structure):
    _fields_ = [("data", c_uint8 * 16)]

def decode(value):
    return (value or b"").decode("utf-8", errors="replace")

def input_metadata_for_device_path(device_path):
    if not device_path:
        return {}
    name = Path(device_path).name
    roots = []
    if name.startswith("event"):
        roots.append(Path("/sys/class/input") / name / "device")
    elif name.startswith("hidraw"):
        hid_root = Path("/sys/class/hidraw") / name / "device"
        try:
            roots.extend(sorted(hid_root.glob("input/input*/")))
        except OSError:
            pass
    for root in roots:
        input_name = read(root / "name")
        if "imu" in input_name.lower():
            continue
        modalias = read(root / "modalias").lower()
        if input_name and SUPPORTED_RE.search(f"{input_name} {modalias}"):
            return {
                "uniq": read(root / "uniq").upper(),
                "modalias": modalias,
                "name": input_name,
            }
    return {}

def sdl3_gamepads():
    if not sdl3_path.exists():
        return []
    try:
        sdl = ctypes.CDLL(str(sdl3_path))
    except OSError as exc:
        log(f"could not load SDL3 for controller resolve: {exc}")
        return []

    sdl.SDL_Init.argtypes = [c_uint32]
    sdl.SDL_Init.restype = c_bool
    sdl.SDL_GetError.restype = c_char_p
    sdl.SDL_GetGamepads.argtypes = [POINTER(c_int)]
    sdl.SDL_GetGamepads.restype = POINTER(c_uint32)
    sdl.SDL_GetGamepadNameForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadNameForID.restype = c_char_p
    sdl.SDL_GetGamepadPathForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadPathForID.restype = c_char_p
    sdl.SDL_GetGamepadGUIDForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadGUIDForID.restype = SdlGuid
    sdl.SDL_GUIDToString.argtypes = [SdlGuid, ctypes.c_char_p, c_int]
    sdl.SDL_OpenGamepad.argtypes = [c_uint32]
    sdl.SDL_OpenGamepad.restype = c_void_p
    sdl.SDL_CloseGamepad.argtypes = [c_void_p]
    sdl.SDL_free.argtypes = [c_void_p]
    sdl.SDL_Quit.argtypes = []

    if not sdl.SDL_Init(0x00000200 | 0x00002000 | 0x00004000):
        log(f"SDL3 gamepad initialization failed: {decode(sdl.SDL_GetError())}")
        return []
    try:
        count = c_int()
        ids = sdl.SDL_GetGamepads(ctypes.byref(count))
        result = []
        try:
            for index in range(count.value):
                instance_id = ids[index]
                handle = sdl.SDL_OpenGamepad(instance_id)
                if not handle:
                    continue
                try:
                    guid = sdl.SDL_GetGamepadGUIDForID(instance_id)
                    guid_buffer = ctypes.create_string_buffer(64)
                    sdl.SDL_GUIDToString(guid, guid_buffer, len(guid_buffer))
                    path = decode(sdl.SDL_GetGamepadPathForID(instance_id))
                    result.append({
                        "sdl3_index": index,
                        "sdl3_instance_id": int(instance_id),
                        "name": decode(sdl.SDL_GetGamepadNameForID(instance_id)),
                        "path": path,
                        "input": input_metadata_for_device_path(path),
                        "guid": guid_buffer.value.decode("ascii", errors="replace"),
                    })
                finally:
                    sdl.SDL_CloseGamepad(handle)
        finally:
            if ids:
                sdl.SDL_free(ids)
        return result
    finally:
        sdl.SDL_Quit()

def saved_players():
    try:
        raw = json.loads(order_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for row in raw.get("players", []):
        ident = str(row.get("mac") or "").upper()
        if not PLAYER_ID_RE.match(ident):
            continue
        try:
            player = int(row.get("player"))
        except (TypeError, ValueError):
            continue
        if 1 <= player <= 4 and row.get("connected") is True:
            rows.append({"player": player, "identity": ident, "name": str(row.get("name") or "")})
    return sorted(rows, key=lambda row: row["player"])

connected = sysfs_devices()
ryubing_duplicate_counts = {}
for gamepad in sdl3_gamepads():
    input_meta = gamepad.get("input", {})
    ident = identity(input_meta.get("uniq", ""), input_meta.get("modalias", ""))
    if ident in connected:
        ryubing_guid = stable_ryubing_guid(gamepad["guid"], input_meta.get("modalias", ""))
        ryubing_id = ""
        if ryubing_guid:
            prefix = ryubing_duplicate_counts.get(ryubing_guid, 0)
            ryubing_id = f"{prefix}-{ryubing_guid}"
            ryubing_duplicate_counts[ryubing_guid] = prefix + 1
        connected[ident].update({
            "sdl_name": gamepad.get("name") or "",
            "sdl3_index": gamepad["sdl3_index"],
            "sdl3_instance_id": gamepad["sdl3_instance_id"],
            "sdl_guid": gamepad["guid"],
            "ryubing_guid": ryubing_guid,
            "ryubing_id": ryubing_id,
            "xemu_guid": gamepad["guid"],
        })
resolved = []
used = set()
for row in saved_players():
    device = connected.get(row["identity"])
    if not device or row["identity"] in used:
        continue
    used.add(row["identity"])
    resolved.append(device)

for ident, device in sorted(connected.items(), key=lambda item: item[1].get("sdl2_index", 99)):
    if ident not in used and len(resolved) < 4:
        used.add(ident)
        resolved.append(device)

players = []
for slot, device in enumerate(resolved[:4], start=1):
    players.append({
        **device,
        "player": slot,
        "sdl2_index": len(players),
        "sdl3_index": len(players),
    })

payload = {
    "version": 1,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "source_order": str(order_path),
    "players": players,
}
tmp = output_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp, output_path)
log(f"resolved {len(players)} connected controller(s)")
PY
  '';

  displayPolicy = pkgs.writeText "emulation-display-policy.json" (
    builtins.toJSON {
      upscaler = "none";
      ultrawide = "center-fixed-aspect";
      gamescope = {
        fsr = false;
        scaleMode = "fit";
        stretchFixedAspect = false;
      };
      nativeScaling = {
        xemu = "internal-resolution-scale";
        xemu-hotkeys = "internal-resolution-scale";
        ryubing = "resolution-scale-and-native-filter";
        dolphin = "internal-resolution";
        pcsx2 = "hardware-renderer-internal-resolution";
        ppsspp = "rendering-resolution";
        cemu = "graphics-packs";
        azahar = "internal-resolution";
        supermodel = "-res output_width,output_height";
      };
    }
  );

  standaloneHotkeyBrokerPy = pkgs.writeText "standalone-hotkey-broker.py" ''
    #!/usr/bin/env python3
    import argparse
    import glob
    import json
    import os
    import select
    import signal
    import socket
    import struct
    import subprocess
    import sys
    import time
    from pathlib import Path

    EVENT = struct.Struct("@llHHi")
    EV_KEY = 0x01
    BTN_B = 304
    BTN_A = 305
    BTN_CAPTURE = 309
    BTN_L1 = 310
    BTN_R1 = 311
    BTN_R2 = 313
    BTN_X = 307
    BTN_Y = 308
    BTN_SELECT = 314
    BTN_START = 315
    DOUBLE_PRESS_SECONDS = 0.9
    FORCE_KILL_SECONDS = 5.0
    KEY_HOLD_MS = "120"
    XDOTOOL = "${lib.getExe pkgs.xdotool}"
    YDOTOOL = "${lib.getExe pkgs.ydotool}"

    KEY_COMMANDS = {
        "escape": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "1:1", "1:0"],
        "tab": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "15:1", "15:0"],
        "f1": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "59:1", "59:0"],
        "f2": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "60:1", "60:0"],
        "f4": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "62:1", "62:0"],
        "f5": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "63:1", "63:0"],
        "f8": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "66:1", "66:0"],
        "f9": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "67:1", "67:0"],
        "f10": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "68:1", "68:0"],
        "f12": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "88:1", "88:0"],
        "grave": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "41:1", "41:0"],
        "ctrl-p": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "29:1", "25:1", "25:0", "29:0"],
        "enter": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "28:1", "28:0"],
        "shift-f1": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "42:1", "59:1", "59:0", "42:0"],
        "ctrl-6": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "29:1", "7:1", "7:0", "29:0"],
        "ctrl-9": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "29:1", "10:1", "10:0", "29:0"],
        "ctrl-r": [YDOTOOL, "key", "-d", KEY_HOLD_MS, "29:1", "19:1", "19:0", "29:0"],
    }
    X_KEY_NAMES = {
        "ctrl-r": "ctrl+r",
        "f1": "F1",
        "f4": "F4",
        "f5": "F5",
        "f8": "F8",
        "f9": "F9",
        "shift-f1": "shift+F1",
        "tab": "Tab",
    }

    PROFILES = {
        "global": {
            "bindings": {},
        },
        "dolphin": {
            "bindings": {
                (BTN_SELECT, BTN_B): ("send-key", "ctrl-r", "Minus + B reset Dolphin"),
                (BTN_SELECT, BTN_L1): ("send-key", "f1", "Minus + L1 loaded Dolphin state slot 1"),
                (BTN_SELECT, BTN_R1): ("send-key", "shift-f1", "Minus + R1 saved Dolphin state slot 1"),
                (BTN_SELECT, BTN_A): ("send-key", "f9", "Minus + A triggered Dolphin screenshot"),
                (BTN_SELECT, BTN_R2): ("send-key", "tab", "Minus + R2 toggled Dolphin fast mode"),
            },
        },
        "xemu": {
            "snapshot_tag": "esde-slot1",
            "bindings": {
                (BTN_SELECT, BTN_X): ("send-key", "f2", "Minus + X opened Xemu quick actions"),
                (BTN_SELECT, BTN_B): ("hmp-command", "system_reset", "Minus + B reset Xemu"),
                (BTN_SELECT, BTN_L1): ("hmp-command", "loadvm {snapshot_tag}", "Minus + L1 loaded Xemu save state"),
                (BTN_SELECT, BTN_R1): ("hmp-command", "savevm {snapshot_tag}", "Minus + R1 saved Xemu state"),
                (BTN_SELECT, BTN_A): ("send-key", "f12", "Minus + A triggered Xemu screenshot"),
                (BTN_SELECT, BTN_Y): ("send-key", "grave", "Minus + Y toggled Xemu debug monitor"),
                (BTN_SELECT, BTN_R2): ("notify-none", "xemu fast-forward is not available", "Minus + R2 has no Xemu action"),
            },
        },
        "pico8": {
            "bindings": {
                (BTN_SELECT, BTN_X): ("send-key", "enter", "Minus + X opened PICO-8 pause menu"),
                (BTN_SELECT, BTN_B): ("send-key", "ctrl-r", "Minus + B reset PICO-8 cart"),
                (BTN_SELECT, BTN_A): ("send-key", "ctrl-6", "Minus + A saved PICO-8 screenshot"),
                (BTN_SELECT, BTN_Y): ("send-key", "ctrl-9", "Minus + Y saved PICO-8 GIF"),
                (BTN_SELECT, BTN_R2): ("notify-none", "pico8 fast-forward is not available", "Minus + R2 has no PICO-8 action"),
            },
        },
        "ryubing": {
            "bindings": {
                (BTN_SELECT, BTN_X): ("send-x-key", "f4", "Minus + X toggled Ryubing UI"),
                (BTN_SELECT, BTN_A): ("send-x-key", "f8", "Minus + A triggered Ryubing screenshot"),
                (BTN_CAPTURE,): ("send-x-key", "f5", "Square toggled Ryubing pause"),
            },
        },
    }

    def log(path, message, event="standalone-hotkey-broker", system="", emulator=""):
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": event,
                            "system": system,
                            "emulator": emulator,
                            "rom": "",
                            "message": message,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        except OSError:
            pass

    def input_name(event_path):
        try:
            return (Path("/sys/class/input") / Path(event_path).name / "device/name").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            return ""

    def supported_event(event_path):
        name = input_name(event_path).lower()
        if "imu" in name:
            return False
        return "pro controller" in name or "8bitdo" in name or "ultimate 2c" in name

    def open_events():
        fds = {}
        for event_path in sorted(glob.glob("/dev/input/event*")):
            if not supported_event(event_path):
                continue
            try:
                fds[event_path] = os.open(event_path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
        return fds

    def process_alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def group_alive(pgid):
        try:
            os.killpg(pgid, 0)
            return True
        except OSError:
            return False

    def process_group(pid):
        try:
            return os.getpgid(pid)
        except OSError:
            return None

    def signal_group(pid, sig, pgid=None):
        try:
            if pgid is None:
                pgid = os.getpgid(pid)
            os.killpg(pgid, sig)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def terminate_process_group(pid, log_path, reason, timeout=FORCE_KILL_SECONDS, system="", emulator=""):
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            log(log_path, f"{reason} skipped; emulator process is already gone", "exit-request", system, emulator)
            return ["gone"]
        except PermissionError:
            log(log_path, f"{reason} failed; could not inspect emulator process group", "exit-request", system, emulator)
            return ["permission-denied"]

        actions = []
        if signal_group(pid, signal.SIGTERM, pgid=pgid):
            actions.append("sigterm")
            log(log_path, f"{reason} sent SIGTERM to emulator process group", "exit-request", system, emulator)
        else:
            actions.append("sigterm-failed")
            log(log_path, f"{reason} SIGTERM failed; emulator process group is already gone or inaccessible", "exit-request", system, emulator)
            return actions

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not group_alive(pgid):
                log(log_path, "emulator process group exited after SIGTERM", "exit-request", system, emulator)
                return actions
            time.sleep(0.1)

        if signal_group(pid, signal.SIGKILL, pgid=pgid):
            actions.append("sigkill")
            log(log_path, f"{reason} still alive after 5 seconds; sent SIGKILL to emulator process group", "force-kill", system, emulator)
        else:
            actions.append("sigkill-skipped")
            log(log_path, "emulator exited before SIGKILL escalation", "exit-request", system, emulator)
        return actions

    def hmp_command(socket_path, command):
        if not socket_path:
            raise RuntimeError("HMP socket is required for this action")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(socket_path)
            try:
                client.recv(4096)
            except socket.timeout:
                pass
            client.sendall((command + "\n").encode("utf-8"))
            time.sleep(0.15)

    def key_command(name):
        try:
            return KEY_COMMANDS[name]
        except KeyError as exc:
            raise RuntimeError(f"unknown key action: {name}") from exc

    def send_key(name, dry_run=False):
        command = key_command(name)
        if dry_run:
            return command
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{' '.join(command)} failed with exit {result.returncode}: {detail}")
        return command

    def x_key_name(name):
        try:
            return X_KEY_NAMES[name]
        except KeyError as exc:
            raise RuntimeError(f"unknown X key action: {name}") from exc

    def x_window_name(window):
        result = subprocess.run(
            [XDOTOOL, "getwindowname", window],
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def find_x_window(pid, profile):
        if not os.environ.get("DISPLAY"):
            return None, "DISPLAY is not set"
        searches = [("pid", [XDOTOOL, "search", "--pid", str(pid)])]
        if profile == "dolphin":
            searches.extend(
                [
                    ("class dolphin-emu", [XDOTOOL, "search", "--class", "dolphin-emu"]),
                    ("class Dolphin", [XDOTOOL, "search", "--class", "Dolphin"]),
                    ("name Dolphin", [XDOTOOL, "search", "--name", "Dolphin"]),
                ]
            )
        elif profile == "ryubing":
            searches.extend(
                [
                    ("class Ryujinx", [XDOTOOL, "search", "--class", "Ryujinx"]),
                    ("class Ryubing", [XDOTOOL, "search", "--class", "Ryubing"]),
                    ("name Ryujinx", [XDOTOOL, "search", "--name", "Ryujinx"]),
                    ("name Ryubing", [XDOTOOL, "search", "--name", "Ryubing"]),
                ]
            )
        failures = []
        for label, command in searches:
            result = subprocess.run(command, check=False, text=True, capture_output=True)
            windows = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
            if windows:
                return windows[-1], label
            detail = (result.stderr or result.stdout or "").strip()
            if detail:
                failures.append(f"{label}: {detail}")
        return None, "; ".join(failures)

    def send_x_key(name, pid, profile, log_path="", system="", emulator="", dry_run=False):
        x_key = x_key_name(name)
        window, source = find_x_window(pid, profile)
        if not window:
            log(log_path, f"{profile} hotkey {x_key} fell back to ydotool; no X window found ({source or 'no matching windows'})", system=system, emulator=emulator)
            return send_key(name, dry_run=dry_run)
        command = [XDOTOOL, "key", "--window", window, "--clearmodifiers", x_key]
        if dry_run:
            return command
        window_name = x_window_name(window)
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"{' '.join(command)} failed with exit {result.returncode}: {detail}")
        detail = f"{profile} hotkey {x_key} sent to X window {window}"
        if window_name:
            detail += f" ({window_name})"
        detail += f" via {source}"
        log(log_path, detail, system=system, emulator=emulator)
        return command

    def resolve_binding_with_chord(profile, pressed_codes, code):
        bindings = PROFILES[profile]["bindings"]
        for chord, action in bindings.items():
            if chord[-1] != code:
                continue
            if all(button in pressed_codes for button in chord):
                return chord, action
        return None, None

    def resolve_binding(profile, pressed_codes, code):
        _chord, action = resolve_binding_with_chord(profile, pressed_codes, code)
        return action

    def compact_active_chords(active_chords, pressed_codes):
        return {chord for chord in active_chords if all(button in pressed_codes for button in chord)}

    def should_fire_chord(active_chords, chord):
        if chord in active_chords:
            return False
        active_chords.add(chord)
        return True

    def run_action(action, args):
        kind, value, message = action
        if kind == "send-key":
            send_key(value, dry_run=args.dry_run)
        elif kind == "send-x-key":
            send_x_key(value, args.pid, args.profile, args.log, args.system, args.emulator, dry_run=args.dry_run)
        elif kind == "hmp-command":
            command = value.format(snapshot_tag=args.snapshot_tag)
            if args.dry_run:
                return message
            hmp_command(args.hmp_socket, command)
        elif kind == "terminate-process-group":
            if not args.dry_run:
                terminate_process_group(args.pid, args.log, message, system=args.system, emulator=args.emulator)
        elif kind == "notify-none":
            pass
        else:
            raise RuntimeError(f"unknown action kind: {kind}")
        return message

    def self_test():
        action = resolve_binding("xemu", {BTN_SELECT, BTN_X}, BTN_X)
        if action[:2] != ("send-key", "f2"):
            raise AssertionError(f"unexpected Minus + X action: {action}")
        action = resolve_binding("xemu", {BTN_SELECT, BTN_R1}, BTN_R1)
        if action[:2] != ("hmp-command", "savevm {snapshot_tag}"):
            raise AssertionError(f"unexpected Minus + R1 action: {action}")
        if resolve_binding("xemu", {BTN_X}, BTN_X) is not None:
            raise AssertionError("Minus-less X must not resolve to an action")
        if resolve_binding("global", {BTN_SELECT, BTN_X}, BTN_X) is not None:
            raise AssertionError("global profile must not resolve emulator actions")
        if key_command("f2") != [YDOTOOL, "key", "-d", KEY_HOLD_MS, "60:1", "60:0"]:
            raise AssertionError("F2 command changed unexpectedly")
        action = resolve_binding("pico8", {BTN_SELECT, BTN_A}, BTN_A)
        if action[:2] != ("send-key", "ctrl-6"):
            raise AssertionError(f"unexpected PICO-8 screenshot action: {action}")
        action = resolve_binding("pico8", {BTN_SELECT, BTN_B}, BTN_B)
        if action[:2] != ("send-key", "ctrl-r"):
            raise AssertionError(f"unexpected PICO-8 reset action: {action}")
        if resolve_binding("pico8", {BTN_CAPTURE}, BTN_CAPTURE) is not None:
            raise AssertionError("bare Square must not resolve to a PICO-8 hotkey")
        action = resolve_binding("dolphin", {BTN_SELECT, BTN_B}, BTN_B)
        if action[:2] != ("send-key", "ctrl-r"):
            raise AssertionError(f"unexpected Dolphin reset action: {action}")
        action = resolve_binding("dolphin", {BTN_SELECT, BTN_L1}, BTN_L1)
        if action[:2] != ("send-key", "f1"):
            raise AssertionError(f"unexpected Dolphin load action: {action}")
        action = resolve_binding("dolphin", {BTN_SELECT, BTN_R1}, BTN_R1)
        if action[:2] != ("send-key", "shift-f1"):
            raise AssertionError(f"unexpected Dolphin save action: {action}")
        action = resolve_binding("dolphin", {BTN_SELECT, BTN_A}, BTN_A)
        if action[:2] != ("send-key", "f9"):
            raise AssertionError(f"unexpected Dolphin screenshot action: {action}")
        if resolve_binding("dolphin", {BTN_CAPTURE}, BTN_CAPTURE) is not None:
            raise AssertionError("bare Square must not resolve to a Dolphin hotkey")
        action = resolve_binding("dolphin", {BTN_SELECT, BTN_R2}, BTN_R2)
        if action[:2] != ("send-key", "tab"):
            raise AssertionError(f"unexpected Dolphin fast-mode action: {action}")
        if resolve_binding("dolphin", {BTN_SELECT, BTN_X}, BTN_X) is not None:
            raise AssertionError("Dolphin Minus + X must stay unbound")
        if resolve_binding("dolphin", {BTN_SELECT, BTN_Y}, BTN_Y) is not None:
            raise AssertionError("Dolphin Minus + Y must stay unbound")
        action = resolve_binding("ryubing", {BTN_SELECT, BTN_X}, BTN_X)
        if action[:2] != ("send-x-key", "f4"):
            raise AssertionError(f"unexpected Ryubing Minus + X action: {action}")
        action = resolve_binding("ryubing", {BTN_SELECT, BTN_A}, BTN_A)
        if action[:2] != ("send-x-key", "f8"):
            raise AssertionError(f"unexpected Ryubing Minus + A action: {action}")
        action = resolve_binding("ryubing", {BTN_CAPTURE}, BTN_CAPTURE)
        if action[:2] != ("send-x-key", "f5"):
            raise AssertionError(f"unexpected Ryubing Square action: {action}")
        active_chords = set()
        chord = (BTN_SELECT, BTN_X)
        if not should_fire_chord(active_chords, chord):
            raise AssertionError("first chord press must fire")
        if should_fire_chord(active_chords, chord):
            raise AssertionError("held chord must not fire twice")
        active_chords = compact_active_chords(active_chords, {BTN_SELECT})
        if chord in active_chords:
            raise AssertionError("released chord must clear debounce state")
        if not should_fire_chord(active_chords, chord):
            raise AssertionError("chord must fire again after release")

        socket_path = None
        received = []
        import tempfile
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "hmp.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
            server.listen(1)

            def accept_once():
                conn, _ = server.accept()
                with conn:
                    conn.sendall(b"(qemu) ")
                    received.append(conn.recv(4096).decode("utf-8"))

            thread = threading.Thread(target=accept_once)
            thread.start()
            hmp_command(socket_path, "system_reset")
            thread.join(timeout=3)
            server.close()
        if received != ["system_reset\n"]:
            raise AssertionError(f"unexpected HMP payload: {received!r}")

        proc = subprocess.Popen(
            [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            actions = terminate_process_group(proc.pid, "", "self-test", timeout=0.2)
            if actions[:2] != ["sigterm", "sigkill"]:
                raise AssertionError(f"unexpected termination actions: {actions}")
            for _ in range(30):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            if proc.poll() is None:
                raise AssertionError("self-test child survived SIGKILL")
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                proc.wait(timeout=3)
        print("standalone-hotkey-broker self-test passed")

    def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--profile", choices=sorted(PROFILES))
        parser.add_argument("--pid", type=int)
        parser.add_argument("--hmp-socket", default="")
        parser.add_argument("--snapshot-tag", default="")
        parser.add_argument("--log", default="")
        parser.add_argument("--system", default="")
        parser.add_argument("--emulator", default="")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--self-test", action="store_true")
        args = parser.parse_args()
        if args.self_test:
            self_test()
            return 0
        if args.profile is None:
            parser.error("--profile is required unless --self-test is used")
        if args.pid is None:
            parser.error("--pid is required unless --self-test is used")
        if not args.snapshot_tag:
            args.snapshot_tag = PROFILES[args.profile].get("snapshot_tag", "slot1")

        fds = open_events()
        if not fds:
            log(args.log, f"no supported controller input devices found for {args.profile} hotkey broker", system=args.system, emulator=args.emulator)
            return 0
        target_pgid = process_group(args.pid)
        if target_pgid is None:
            log(args.log, f"{args.profile} hotkey broker target process {args.pid} is already gone", system=args.system, emulator=args.emulator)
            for fd in fds.values():
                os.close(fd)
            return 0

        pressed = {path: set() for path in fds}
        active_chords = {path: set() for path in fds}
        last_select_start = {path: 0.0 for path in fds}
        event_detail = ", ".join(f"{path}:{input_name(path)}" for path in sorted(fds))
        log(args.log, f"started {args.profile} hotkey broker on pid {args.pid}, pgid {target_pgid}, events [{event_detail}]", system=args.system, emulator=args.emulator)

        while group_alive(target_pgid):
            try:
                readable, _, _ = select.select(list(fds.values()), [], [], 0.2)
            except OSError:
                break
            reverse = {fd: path for path, fd in fds.items()}
            for fd in readable:
                path = reverse.get(fd)
                if not path:
                    continue
                try:
                    data = os.read(fd, EVENT.size * 16)
                except OSError:
                    continue
                for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _sec, _usec, ev_type, code, value = EVENT.unpack(data[offset : offset + EVENT.size])
                    if ev_type != EV_KEY:
                        continue
                    if value == 2:
                        continue
                    if value:
                        pressed[path].add(code)
                    else:
                        pressed[path].discard(code)
                        active_chords[path] = compact_active_chords(active_chords[path], pressed[path])
                        continue
                    if code == BTN_START and BTN_SELECT in pressed[path]:
                        now = time.monotonic()
                        if now - last_select_start[path] <= DOUBLE_PRESS_SECONDS:
                            terminate_process_group(
                                args.pid,
                                args.log,
                                "Minus + Plus double-press",
                                system=args.system,
                                emulator=args.emulator,
                            )
                            return 0
                        last_select_start[path] = now
                        continue
                    chord, action = resolve_binding_with_chord(args.profile, pressed[path], code)
                    if action is None:
                        continue
                    if not should_fire_chord(active_chords[path], chord):
                        continue
                    try:
                        message = run_action(action, args)
                        log(args.log, message, system=args.system, emulator=args.emulator)
                    except Exception as exc:
                        log(args.log, f"hotkey action failed: {exc}", "error", args.system, args.emulator)
        return 0

    if __name__ == "__main__":
        sys.exit(main())
  '';

  standaloneHotkeyBroker = pkgs.writeShellScriptBin "standalone-hotkey-broker" ''
    set -euo pipefail
    exec ${pkgs.python3}/bin/python3 ${standaloneHotkeyBrokerPy} "$@"
  '';

  standaloneHotkeyBrokerSmokeTest = pkgs.writeShellScriptBin "standalone-hotkey-broker-smoke-test" ''
    set -euo pipefail
    exec ${lib.getExe standaloneHotkeyBroker} --self-test
  '';

  switchProButtonProbePy = pkgs.writeText "switch-pro-button-probe.py" ''
    #!/usr/bin/env python3
    import glob
    import os
    import select
    import struct
    import time
    from pathlib import Path

    EVENT = struct.Struct("@llHHi")
    EV_KEY = 0x01
    EV_ABS = 0x03
    NAMES = {
        304: "B/South",
        305: "A/East",
        307: "X/North",
        308: "Y/West",
        309: "Square/Capture",
        310: "L1",
        311: "R1",
        312: "L2",
        313: "R2",
        314: "Minus",
        315: "Start/+",
        316: "Star/Home",
        317: "Left Stick Press",
        318: "Right Stick Press",
    }
    ABS_NAMES = {
        0: "Left Stick X",
        1: "Left Stick Y",
        3: "Right Stick X",
        4: "Right Stick Y",
        16: "D-pad X",
        17: "D-pad Y",
    }

    def name(path):
        try:
            return (Path("/sys/class/input") / Path(path).name / "device/name").read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except OSError:
            return ""

    fds = {}
    for path in sorted(glob.glob("/dev/input/event*")):
        lowered = name(path).lower()
        if "pro controller" in lowered and "imu" not in lowered:
            try:
                fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                print(f"Watching {path} ({name(path)})")
            except OSError:
                pass
    if not fds:
        print("No Switch Pro controller event devices found.")
        raise SystemExit(1)
    print("Press buttons or move sticks now; exiting after 12 seconds.")
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        readable, _, _ = select.select(list(fds.values()), [], [], 0.25)
        reverse = {fd: path for path, fd in fds.items()}
        for fd in readable:
            path = reverse.get(fd, "?")
            data = os.read(fd, EVENT.size * 16)
            for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _sec, _usec, ev_type, code, value = EVENT.unpack(data[offset : offset + EVENT.size])
                if ev_type == EV_KEY and value == 1:
                    print(f"{Path(path).name}: code {code} {NAMES.get(code, 'unknown')}")
                elif ev_type == EV_ABS and code in ABS_NAMES:
                    print(f"{Path(path).name}: axis {code} {ABS_NAMES[code]} value {value}")
  '';

  switchProButtonProbe = pkgs.writeShellScriptBin "switch-pro-button-probe" ''
    set -euo pipefail
    exec ${pkgs.python3}/bin/python3 ${switchProButtonProbePy} "$@"
  '';

  displayProfile = pkgs.writeShellScriptBin "display-profile" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH

    preferred_vendor="0x1002"
    preferred_device="0x73ef"

    connector_from_output() {
      output="$1"
      card="''${output%%-*}"
      printf '%s\n' "''${output#"$card"-}"
    }

    mode_for_output() {
      output_dir="$1"
      if [ -r "$output_dir/modes" ]; then
        sed -n '1p' "$output_dir/modes"
      fi
    }

    discover_output() {
      forced_connector="''${EMULATION_CONNECTOR:-}"
      forced_drm_card="''${EMULATION_DRM_CARD:-}"
      best_score=-1
      best_output=""
      best_card=""
      best_connector=""
      best_mode=""
      best_dgpu=false

      for status in /sys/class/drm/card*-*/status; do
        [ -e "$status" ] || continue
        grep -qx connected "$status" || continue
        output_dir="''${status%/status}"
        output="''${output_dir##*/}"
        card="''${output%%-*}"
        connector="$(connector_from_output "$output")"
        card_device="/sys/class/drm/$card/device"
        vendor="$(sed -n '1p' "$card_device/vendor" 2>/dev/null || true)"
        device="$(sed -n '1p' "$card_device/device" 2>/dev/null || true)"
        mode="$(mode_for_output "$output_dir")"
        [ -n "$mode" ] || continue

        score=10
        dgpu=false
        if [ "$vendor" = "$preferred_vendor" ] && [ "$device" = "$preferred_device" ]; then
          score=$((score + 100))
          dgpu=true
        elif [ "$vendor" = "$preferred_vendor" ]; then
          score=$((score + 50))
        fi
        if [ -n "$forced_connector" ] && [ "$connector" = "$forced_connector" ]; then
          score=$((score + 1000))
        fi
        if [ -n "$forced_drm_card" ] && [ "$card" = "$forced_drm_card" ]; then
          score=$((score + 500))
        fi
        case "$connector" in
          HDMI-A-*) score=$((score + 20)) ;;
          DP-*|DisplayPort-*) score=$((score + 10)) ;;
        esac

        if [ "$score" -gt "$best_score" ]; then
          best_score="$score"
          best_output="$output"
          best_card="$card"
          best_connector="$connector"
          best_mode="$mode"
          best_dgpu="$dgpu"
        fi
      done

      if [ -n "$best_output" ]; then
        printf '%s\t%s\t%s\t%s\t%s\n' "$best_output" "$best_card" "$best_connector" "$best_mode" "$best_dgpu"
      fi
    }

    if [ "''${1:-}" = "--matrix-test" ]; then
      tmp="$(mktemp)"
      for spec in 1280x720 1920x1080 1920x1200 2560x1080 2560x1440 2560x1600 3440x1440 3840x1600 3840x2160 5120x1440 5120x2160 7680x4320; do
        EMULATION_DISPLAY_WIDTH="''${spec%x*}" EMULATION_DISPLAY_HEIGHT="''${spec#*x}" EMULATION_EMULATOR_HEAVY=0 "$0" >>"$tmp"
        EMULATION_DISPLAY_WIDTH="''${spec%x*}" EMULATION_DISPLAY_HEIGHT="''${spec#*x}" EMULATION_EMULATOR_HEAVY=1 "$0" >>"$tmp"
      done
      jq -s . "$tmp"
      rm -f "$tmp"
      exit 0
    fi

    width="''${EMULATION_DISPLAY_WIDTH:-}"
    height="''${EMULATION_DISPLAY_HEIGHT:-}"
    refresh="''${EMULATION_DISPLAY_REFRESH:-60}"
    system_id="''${EMULATION_SYSTEM_ID:-unknown}"
    emulator_id="''${EMULATION_EMULATOR_ID:-unknown}"
    output="''${EMULATION_OUTPUT:-}"
    drm_card="''${EMULATION_DRM_CARD:-}"
    connector="''${EMULATION_CONNECTOR:-}"
    dgpu=false
    connected=false

    if [ -z "$width" ] || [ -z "$height" ] || [ -z "$connector" ]; then
      discovered="$(discover_output || true)"
      if [ -n "$discovered" ]; then
        connected=true
        IFS=$'\t' read -r output drm_card connector mode dgpu <<<"$discovered"
        if [ -z "$width" ] || [ -z "$height" ]; then
          width="''${mode%x*}"
          mode_rest="''${mode#*x}"
          height="''${mode_rest%%[^0-9]*}"
        fi
      fi
    fi

    if [ -z "$width" ] || [ -z "$height" ]; then
      if command -v wlr-randr >/dev/null 2>&1; then
        mode="$(wlr-randr 2>/dev/null | awk '/^[^ ]/{out=$1} /current/{print $1; exit}' || true)"
        if [ -n "$mode" ]; then
          width="''${mode%x*}"
          rest="''${mode#*x}"
          height="''${rest%@*}"
          if printf '%s' "$rest" | grep -q '@'; then
            refresh="''${rest#*@}"
          fi
        fi
      fi
    fi

    if [ -z "$width" ] || [ -z "$height" ]; then
      if command -v xrandr >/dev/null 2>&1; then
        mode="$(xrandr --current 2>/dev/null | awk '/ connected/{out=$1} /\*/{print $1; exit}' || true)"
        if [ -n "$mode" ]; then
          width="''${mode%x*}"
          height="''${mode#*x}"
        fi
      fi
    fi

    width="''${width:-1920}"
    height="''${height:-1080}"
    drm_device=""
    if [ -n "$drm_card" ] && [ -e "/dev/dri/$drm_card" ]; then
      drm_device="/dev/dri/$drm_card"
    fi
    aspect="$(awk -v w="$width" -v h="$height" 'BEGIN { if (h == 0) h = 1; printf "%.3f", w / h }')"
    class="$(awk -v a="$aspect" 'BEGIN { if (a > 2.9) print "super-ultrawide"; else if (a > 1.9) print "ultrawide"; else if (a > 1.65) print "widescreen"; else print "standard"; }')"
    render_width="$width"
    render_height="$height"
    fsr=false
    scale_mode="fit"
    fixed_aspect="center"
    viewports_json="$(
      jq -n --argjson ow "$width" --argjson oh "$height" '
        def fit($rw; $rh):
          (if (($ow / $oh) >= ($rw / $rh)) then
            { width: (($oh * $rw / $rh) | floor), height: $oh }
          else
            { width: $ow, height: (($ow * $rh / $rw) | floor) }
          end) as $v
          | $v + {
              x: ((($ow - $v.width) / 2) | floor),
              y: ((($oh - $v.height) / 2) | floor)
            };
        {
          "4:3": fit(4; 3),
          "3:2": fit(3; 2),
          "10:9": fit(10; 9),
          "20:19": fit(20; 19),
          "16:9": fit(16; 9),
          native: { x: 0, y: 0, width: $ow, height: $oh }
        }
      '
    )"

    if [ "''${1:-}" = "gamescope-args" ]; then
      args=(-f -e -W "$width" -H "$height" -w "$render_width" -h "$render_height" -S "$scale_mode")
      printf '%q ' "''${args[@]}"
      printf '\n'
      exit 0
    fi

    jq -n \
      --arg system_id "$system_id" \
      --arg emulator_id "$emulator_id" \
      --arg output "$output" \
      --arg drm_card "$drm_card" \
      --arg drm_device "$drm_device" \
      --arg connector "$connector" \
      --argjson connected "$connected" \
      --argjson dgpu "$dgpu" \
      --argjson output_width "$width" \
      --argjson output_height "$height" \
      --arg refresh "$refresh" \
      --arg aspect "$aspect" \
      --arg class "$class" \
      --argjson render_width "$render_width" \
      --argjson render_height "$render_height" \
      --argjson fsr "$fsr" \
      --arg scale_mode "$scale_mode" \
      --arg fixed_aspect "$fixed_aspect" \
      --argjson viewports "$viewports_json" \
      '{
        system_id:$system_id,
        emulator_id:$emulator_id,
        connected:$connected,
        output:$output,
        drm_card:$drm_card,
        drm_device:$drm_device,
        connector:$connector,
        preferred_dgpu:$dgpu,
        preferred_vk_device:(if $dgpu then "1002:73ef" else "" end),
        output_width:$output_width,
        output_height:$output_height,
        refresh:$refresh,
        aspect:($aspect|tonumber),
        class:$class,
        render_width:$render_width,
        render_height:$render_height,
        fsr:$fsr,
        scale_mode:$scale_mode,
        fixed_aspect:$fixed_aspect,
        viewport_recommendations:$viewports,
        gamescope_args:["-f","-e","-W",($output_width|tostring),"-H",($output_height|tostring),"-w",($render_width|tostring),"-h",($render_height|tostring),"-S",$scale_mode],
        frontend_gamescope_args:(["--backend","drm","-f","-W",($output_width|tostring),"-H",($output_height|tostring),"--force-windows-fullscreen"] + (if $connector != "" then ["--prefer-output",$connector] else [] end) + (if $dgpu then ["--prefer-vk-device","1002:73ef"] else [] end))
      }'
  '';

  teknoparrotFree = pkgs.writeShellScriptBin "teknoparrot-free" ''
        set -euo pipefail
        export PATH=${emu.scriptPath}:${
          lib.makeBinPath [
            packages.winePackage
            packages.wineMono
            pkgs.curl
            pkgs.unzip
            pkgs.xmlstarlet
          ]
        }:$PATH
        prefix="${cfg.configRoot}/teknoparrot"
        install_dir="$prefix/TeknoParrot"
        rom="''${1:-}"
        mkdir -p "$prefix" "${cfg.dataRoot}/logs/teknoparrot"
        export WINEPREFIX="$prefix/prefix"
        export WINEARCH=win64
        export WINE_MONO_CACHE_DIR="${packages.wineMono}/share/wine/mono"
        ensure_wine_mono() {
          if [ -e "$WINEPREFIX/drive_c/windows/mono/mono-2.0/lib/mono/4.5/mscorlib.dll" ]; then
            return
          fi
          WINEDLLOVERRIDES=mscoree=d wineboot -u
          wine msiexec /i "${packages.wineMono}/share/wine/mono/wine-mono-10.4.1-x86.msi"
        }
        set_parrot_data_value() {
          local name="$1"
          local value="$2"
          if [ "$(xmlstarlet sel -t -v "count(/ParrotData/$name)" ParrotData.xml 2>/dev/null || echo 0)" != "0" ]; then
            xmlstarlet ed -L -u "/ParrotData/$name" -v "$value" ParrotData.xml
          else
            xmlstarlet ed -L -s /ParrotData -t elem -n "$name" -v "$value" ParrotData.xml
          fi
        }
        ensure_parrot_data() {
          if [ ! -s ParrotData.xml ]; then
            cat >ParrotData.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<ParrotData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <UseSto0ZDrivingHack>false</UseSto0ZDrivingHack>
  <StoozPercent>0</StoozPercent>
  <FullAxisGas>false</FullAxisGas>
  <FullAxisBrake>false</FullAxisBrake>
  <ReverseAxisGas>false</ReverseAxisGas>
  <ReverseAxisBrake>false</ReverseAxisBrake>
  <LastPlayed />
  <ExitGameKey>0x1B</ExitGameKey>
  <PauseGameKey>0x13</PauseGameKey>
  <ScoreSubmissionID />
  <ScoreCollapseGUIKey>0x79</ScoreCollapseGUIKey>
  <SaveLastPlayed>false</SaveLastPlayed>
  <UseDiscordRPC>false</UseDiscordRPC>
  <SilentMode>true</SilentMode>
  <CheckForUpdates>false</CheckForUpdates>
  <ConfirmExit>false</ConfirmExit>
  <DownloadIcons>false</DownloadIcons>
  <UiDisableHardwareAcceleration>true</UiDisableHardwareAcceleration>
  <HideVanguardWarning>false</HideVanguardWarning>
  <UiColour>lightblue</UiColour>
  <UiDarkMode>false</UiDarkMode>
  <UiHolidayThemes>false</UiHolidayThemes>
  <Elfldr2NetworkAdapterName />
  <HasReadPolicies>true</HasReadPolicies>
  <DisableAnalytics>false</DisableAnalytics>
  <Elfldr2LogToFile>false</Elfldr2LogToFile>
  <DatXmlLocation />
  <FirstTimeSetupComplete>true</FirstTimeSetupComplete>
  <IsLoggedIn>false</IsLoggedIn>
  <SegaId />
  <NamcoId />
  <MarioKartId />
  <Language>en</Language>
  <HideDolphinGUI>true</HideDolphinGUI>
  <ConfirmGameDeletion>false</ConfirmGameDeletion>
</ParrotData>
EOF
          fi
          set_parrot_data_value FirstTimeSetupComplete true
          set_parrot_data_value HasReadPolicies true
          set_parrot_data_value CheckForUpdates false
          set_parrot_data_value DownloadIcons false
          set_parrot_data_value SilentMode true
          set_parrot_data_value ConfirmExit false
          set_parrot_data_value UiDisableHardwareAcceleration true
          set_parrot_data_value UiHolidayThemes false
        }
        profile_value() {
          xmlstarlet sel -t -v "/GameProfile/$1" "$2" 2>/dev/null || true
        }
        resolve_profile_arg() {
          local selected="$1"
          local selected_base
          local selected_emulation
          local selected_executable
          local selected_emulator
          local candidate
          selected_base="$(basename "$selected")"
          if [ -f "$install_dir/GameProfiles/$selected_base" ]; then
            printf '%s\n' "$selected_base"
            return
          fi
          selected_emulation="$(profile_value EmulationProfile "$selected")"
          selected_executable="$(profile_value ExecutableName "$selected")"
          selected_emulator="$(profile_value EmulatorType "$selected")"
          while IFS= read -r candidate; do
            if [ "$(profile_value EmulationProfile "$candidate")" = "$selected_emulation" ] \
              && [ "$(profile_value ExecutableName "$candidate")" = "$selected_executable" ] \
              && [ "$(profile_value EmulatorType "$candidate")" = "$selected_emulator" ]; then
              basename "$candidate"
              return
            fi
          done < <(find "$install_dir/GameProfiles" -maxdepth 1 -type f -name "*.xml" | sort)
          echo "No official TeknoParrot GameProfiles entry matches $selected_base ($selected_emulation/$selected_executable/$selected_emulator)" >&2
          exit 66
        }
        if [ ! -e "$install_dir/TeknoParrotUi.exe" ]; then
          cat >&2 <<EOF
    TeknoParrot free is scaffolded but not installed yet.

    Place the official free TeknoParrot files under:
      ${cfg.configRoot}/teknoparrot/TeknoParrot

    No premium unlocks, bypasses, commercial game files, or third-party patch packs
    are managed by this module.
EOF
          exit 69
        fi
        if [ -n "$rom" ]; then
          case "$rom" in
            *.xml|*.XML) ;;
            *)
              echo "TeknoParrot launch targets must be XML profiles: $rom" >&2
              exit 64
              ;;
          esac
          if [ ! -f "$rom" ]; then
            echo "TeknoParrot XML profile not found: $rom" >&2
            exit 66
          fi
          profile="$(resolve_profile_arg "$rom")"
          mkdir -p "$install_dir/UserProfiles"
          cp -f "$rom" "$install_dir/UserProfiles/$profile"
          cd "$install_dir"
          ensure_parrot_data
          ensure_wine_mono
          exec wine TeknoParrotUi.exe --profile="$profile"
        fi
        cd "$install_dir"
        ensure_parrot_data
        ensure_wine_mono
        exec wine "$install_dir/TeknoParrotUi.exe"
  '';

  runEmulator = pkgs.writeShellScriptBin "run-emulator" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${launcherPath}:$PATH
    export ESDE_APPDATA_DIR="${cfg.esde.appDataDir}"
    export XDG_DATA_HOME="${cfg.dataRoot}/xdg/share"
    export XDG_CONFIG_HOME="${cfg.dataRoot}/xdg/config"
    export XDG_CACHE_HOME="${cfg.dataRoot}/xdg/cache"
    export MESA_SHADER_CACHE_DIR="${cfg.dataRoot}/cache/mesa-shaders"
    export SDL_GAMECONTROLLERCONFIG_FILE="${cfg.configRoot}/controllers/gamecontrollerdb.txt"
    export SDL_GAMECONTROLLER_USE_BUTTON_LABELS=1
    export SDL_AUDIO_DRIVER="''${SDL_AUDIO_DRIVER:-pipewire}"
    export SDL_AUDIO_DEVICE_SAMPLE_FRAMES="''${SDL_AUDIO_DEVICE_SAMPLE_FRAMES:-1024}"
    export SDL_AUDIO_FREQUENCY="''${SDL_AUDIO_FREQUENCY:-48000}"
    export SDL_AUDIO_FORMAT="''${SDL_AUDIO_FORMAT:-F32}"
    export SDL_AUDIO_DEVICE_STREAM_ROLE="''${SDL_AUDIO_DEVICE_STREAM_ROLE:-Game}"
    export TMPDIR="${cfg.dataRoot}/tmp"

    if [ "$#" -lt 3 ]; then
      echo "Usage: run-emulator <system-id> <emulator-id> <rom-path>" >&2
      exit 64
    fi

    [ -r "${cfg.configRoot}/display.env" ] && . "${cfg.configRoot}/display.env"

    system_id="$1"
    emulator_id="$2"
    rom_path="$3"
    export EMULATION_SYSTEM_ID="$system_id"
    export EMULATION_EMULATOR_ID="$emulator_id"
    audio-route || true
    log_dir="${cfg.dataRoot}/logs/launches"
    mkdir -p "$log_dir"
    log_file="$log_dir/$(date -u +%Y%m%dT%H%M%SZ)-$system_id.jsonl"

    log_event() {
      jq -nc --arg time "$(date -u +%FT%TZ)" --arg event "$1" --arg system "$system_id" --arg emulator "$emulator_id" --arg rom "$rom_path" --arg message "''${2:-}" \
        '{time:$time,event:$event,system:$system,emulator:$emulator,rom:$rom,message:$message}' >>"$log_file"
    }

    controller-leds apply || true
    ${lib.getExe controllerResolve} || true
    resolved_controllers="/run/ghostship-emulation/controllers/resolved-order.json"
    mkdir -p "$(dirname "$resolved_controllers")"
    resolved_player_count="$(jq -r '.players | length' "$resolved_controllers" 2>/dev/null || echo 0)"
    log_event "controllers" "$(jq -c '.players // []' "$resolved_controllers" 2>/dev/null || echo '[]')"

    first_command() {
      for candidate in "$@"; do
        if command -v "$candidate" >/dev/null 2>&1; then
          printf '%s\n' "$candidate"
          return 0
        fi
      done
      return 1
    }

    core_file_for() {
      case "$1" in
        retroarch-fbneo) echo fbneo_libretro.so ;;
        retroarch-mame) echo mame_libretro.so ;;
        retroarch-fceumm) echo fceumm_libretro.so ;;
        retroarch-mesen) echo mesen_libretro.so ;;
        retroarch-snes9x) echo snes9x_libretro.so ;;
        retroarch-bsnes) echo bsnes_libretro.so ;;
        retroarch-bsnes-hd) echo bsnes_hd_beta_libretro.so ;;
        retroarch-genesis-plus-gx) echo genesis_plus_gx_libretro.so ;;
        retroarch-picodrive) echo picodrive_libretro.so ;;
        retroarch-beetle-supergrafx) echo mednafen_supergrafx_libretro.so ;;
        retroarch-beetle-pce-fast) echo mednafen_pce_fast_libretro.so ;;
        retroarch-gambatte) echo gambatte_libretro.so ;;
        retroarch-sameboy) echo sameboy_libretro.so ;;
        retroarch-mgba) echo mgba_libretro.so ;;
        retroarch-beetle-ngp) echo mednafen_ngp_libretro.so ;;
        retroarch-neocd) echo neocd_libretro.so ;;
        retroarch-beetle-vb) echo mednafen_vb_libretro.so ;;
        retroarch-beetle-psx-hw) echo mednafen_psx_hw_libretro.so ;;
        retroarch-beetle-saturn) echo mednafen_saturn_libretro.so ;;
        retroarch-flycast) echo flycast_libretro.so ;;
        retroarch-mupen64plus) echo mupen64plus_next_libretro.so ;;
        retroarch-parallel-n64) echo parallel_n64_libretro.so ;;
        retroarch-desmume) echo desmume_libretro.so ;;
        retroarch-melonds) echo melonds_libretro.so ;;
        retroarch-ppsspp) echo ppsspp_libretro.so ;;
        retroarch-pcsx2) echo pcsx2_libretro.so ;;
        retroarch-citra) echo citra_libretro.so ;;
        *) return 1 ;;
      esac
    }

    core_pattern_for() {
      case "$1" in
        retroarch-desmume) echo '*desmume*_libretro.so' ;;
        retroarch-melonds) echo '*melon*ds*_libretro.so' ;;
        retroarch-bsnes-hd) echo '*bsnes*hd*_libretro.so' ;;
        retroarch-mupen64plus) echo '*mupen64plus*_libretro.so' ;;
        retroarch-parallel-n64) echo '*parallel*n64*_libretro.so' ;;
        retroarch-beetle-*) echo '*mednafen*_libretro.so' ;;
        *) echo "*''${1#retroarch-}*_libretro.so" ;;
      esac
    }

    retroarch_analog_dpad_mode() {
      case "$system_id" in
        fbneo|gb|gba|gbc|gamegear|genesis|mastersystem|nds|neogeocd|nes|ngpc|pcengine|pcenginecd|saturn|segacd|snes|virtualboy)
          echo 1
          ;;
        *)
          echo 0
          ;;
      esac
    }

    retroarch_face_overrides() {
      player="$1"
      case "$system_id" in
        dreamcast)
          cat <<EOF
input_player''${player}_b_btn = "1"
input_player''${player}_a_btn = "0"
input_player''${player}_y_btn = "3"
input_player''${player}_x_btn = "2"
EOF
          ;;
        *)
          cat <<EOF
input_player''${player}_b_btn = "0"
input_player''${player}_a_btn = "1"
input_player''${player}_y_btn = "2"
input_player''${player}_x_btn = "3"
EOF
          ;;
      esac
    }

    heavy=0
    case "$emulator_id" in
      azahar|dolphin|cemu|xemu|xemu-hotkeys|ryubing|lime3ds|pcsx2|ppsspp|supermodel|teknoparrot|retroarch-beetle-psx-hw|retroarch-beetle-saturn|retroarch-mupen64plus|retroarch-parallel-n64|retroarch-flycast) heavy=1 ;;
    esac
    export EMULATION_EMULATOR_HEAVY="$heavy"
    profile_json="$(display-profile)"
    preferred_vk_device="$(jq -r '.preferred_vk_device // empty' <<<"$profile_json")"
    if [ -n "$preferred_vk_device" ]; then
      export MESA_VK_DEVICE_SELECT="$preferred_vk_device"
      if [ "$emulator_id" = "ryubing" ]; then
        export MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE=1
      fi
    fi
    output_width="$(jq -r '.output_width' <<<"$profile_json")"
    output_height="$(jq -r '.output_height' <<<"$profile_json")"

    bootstrap_emulator_config() {
      emulator="$1"
      case "$emulator" in
        azahar|cemu|dolphin|pcsx2|ppsspp|ryubing|supermodel|xemu|xemu-hotkeys)
          case "$emulator" in
            xemu-hotkeys) dir="${cfg.configRoot}/emulators/xemu" ;;
            *) dir="${cfg.configRoot}/emulators/$emulator" ;;
          esac
          mkdir -p "$dir"
          jq -n \
            --arg emulator "$emulator" \
            --arg scaling_profile "''${EMULATION_PERF_SCALING_PROFILE:-default}" \
            --argjson output_width "$output_width" \
            --argjson output_height "$output_height" \
            '{
              emulator:$emulator,
              output_width:$output_width,
              output_height:$output_height,
              gamescope_fsr:false,
              aspect_policy:"preserve",
              scaling:"emulator-native",
              scaling_profile:$scaling_profile,
              generated_at:now|todate
            }' >"$dir/runtime-scaling-policy.json.tmp"
          mv "$dir/runtime-scaling-policy.json.tmp" "$dir/runtime-scaling-policy.json"
          ;;
      esac
    }
    bootstrap_emulator_config "$emulator_id"

    prepare_ryubing_runtime() {
      ryujinx_config_dir="$XDG_CONFIG_HOME/Ryujinx"
      ryujinx_system_dir="$ryujinx_config_dir/system"
      ryujinx_sdcard_dir="$ryujinx_config_dir/sdcard"
      ryujinx_firmware_dir="$ryujinx_config_dir/bis/system/Contents/registered"
      ryujinx_firmware_marker="$ryujinx_config_dir/bis/system/Contents/firmware-installed.json"
      mkdir -p "$ryujinx_system_dir" "$ryujinx_sdcard_dir" "$ryujinx_firmware_dir" "$(dirname "$ryujinx_firmware_marker")"
      ryujinx_config_file="$ryujinx_config_dir/Config.json"

      ${pkgs.python3}/bin/python3 - \
        "$ryujinx_config_file" \
        "${packages.ryubingCanaryPackage}/opt/ryubing-canary/libSDL3.so" \
        "$resolved_controllers" \
        "$log_file" \
        "$system_id" \
        "$emulator_id" \
        "$rom_path" <<'PY'
import ctypes
import json
import re
import sys
import time
from ctypes import POINTER, Structure, c_bool, c_char_p, c_int, c_uint8, c_uint32, c_void_p
from pathlib import Path

path = Path(sys.argv[1])
sdl_lib_path = Path(sys.argv[2])
resolved_order_path = Path(sys.argv[3])
log_path = Path(sys.argv[4])
system_id = sys.argv[5]
emulator_id = sys.argv[6]
rom_path = sys.argv[7]

def log_event(event, message):
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": event,
                        "system": system_id,
                        "emulator": emulator_id,
                        "rom": rom_path,
                        "message": message,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
    except OSError:
        pass

def log_warning(message):
    log_event("warning", message)

if path.exists():
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise SystemExit(f"Refusing to rewrite invalid Ryubing config: {path}")
else:
    config = {
        "version": 71,
        "enable_file_log": True,
        "backend_threading": "Auto",
        "res_scale": 1,
        "res_scale_custom": 1,
        "max_anisotropy": -1,
        "aspect_ratio": "Fixed16x9",
        "anti_aliasing": "None",
        "scaling_filter": "Bilinear",
        "scaling_filter_level": 80,
        "graphics_shaders_dump_path": "",
        "logging_enable_debug": False,
        "logging_enable_stub": True,
        "logging_enable_info": True,
        "logging_enable_warn": True,
        "logging_enable_error": True,
        "logging_enable_trace": False,
        "logging_enable_guest": True,
        "logging_enable_fs_access_log": False,
        "logging_enable_avalonia": False,
        "logging_filtered_classes": [],
        "logging_graphics_debug_level": "None",
        "system_language": "AmericanEnglish",
        "system_region": "USA",
        "system_time_zone": "UTC",
        "system_time_offset": 0,
        "match_system_time": False,
        "use_input_global_config": True,
        "docked_mode": True,
        "enable_discord_integration": False,
        "check_updates_on_start": False,
        "update_checker_type": "PromptAtStartup",
        "focus_lost_action_type": "DoNothing",
        "show_confirm_exit": False,
        "ignore_applet": False,
        "skip_user_profiles": False,
        "remember_window_state": True,
        "show_title_bar": True,
        "enable_hardware_acceleration": True,
        "hide_cursor": 1,
        "enable_vsync": True,
        "vsync_mode": 0,
        "enable_custom_vsync_interval": False,
        "custom_vsync_interval": 120,
        "enable_shader_cache": True,
        "enable_texture_recompression": False,
        "enable_macro_hle": True,
        "enable_color_space_passthrough": False,
        "enable_ptc": True,
        "enable_low_power_ptc": False,
        "tick_scalar": 50,
        "enable_internet_access": False,
        "enable_fs_integrity_checks": True,
        "fs_global_access_log_mode": 0,
        "audio_backend": "SDL3",
        "audio_volume": 1,
        "memory_manager_mode": "HostMappedUnsafe",
        "dram_size": 0,
        "ignore_missing_services": False,
        "gui_columns": {
            "fav_column": True,
            "icon_column": True,
            "app_column": True,
            "dev_column": True,
            "version_column": True,
            "ldn_info_column": False,
            "time_played_column": True,
            "last_played_column": True,
            "file_ext_column": True,
            "file_size_column": True,
            "path_column": True,
        },
        "column_sort": {"sort_column_id": 0, "sort_ascending": False},
        "game_dirs": [],
        "autoload_dirs": [],
        "shown_file_types": {"nsp": True, "pfs0": True, "xci": True, "nca": True, "nro": True, "nso": True},
        "window_startup": {
            "window_size_width": 1280,
            "window_size_height": 760,
            "window_position_x": 0,
            "window_position_y": 0,
            "window_maximized": False,
        },
        "language_code": "en_US",
        "base_style": "Dark",
        "game_list_view_mode": 0,
        "show_names": True,
        "grid_size": 2,
        "application_sort": 0,
        "is_ascending_order": True,
        "start_fullscreen": True,
        "start_no_ui": False,
        "show_console": False,
        "enable_keyboard": True,
        "enable_mouse": False,
        "disable_input_when_out_of_focus": False,
        "hotkeys": {
            "toggle_vsync_mode": "F1",
            "screenshot": "F8",
            "show_ui": "F4",
            "pause": "F5",
            "toggle_mute": "F2",
            "res_scale_up": "Unbound",
            "res_scale_down": "Unbound",
            "volume_up": "Unbound",
            "volume_down": "Unbound",
            "custom_vsync_interval_increment": "Unbound",
            "custom_vsync_interval_decrement": "Unbound",
            "turbo_mode": "Unbound",
            "turbo_mode_while_held": False,
        },
        "input_config": [],
        "rainbow_speed": 1,
        "graphics_backend": "Vulkan",
        "preferred_gpu": "",
        "multiplayer_mode": 0,
        "multiplayer_lan_interface_id": "0",
        "multiplayer_disable_p2p": False,
        "multiplayer_ldn_passphrase": "",
        "ldn_server": "",
        "use_hypervisor": True,
        "enable_gdb_stub": False,
        "gdb_stub_port": 55555,
        "debugger_suspend_on_start": False,
        "show_dirty_hacks": False,
        "dirty_hacks": [],
    }

for key in (
    "Version",
    "BackendThreading",
    "ResScale",
    "ResScaleCustom",
    "MaxAnisotropy",
    "DockedMode",
    "AudioBackend",
    "GraphicsBackend",
    "StartFullscreen",
    "ShowConsole",
    "EnableKeyboard",
    "EnableMouse",
    "Hotkeys",
):
    config.pop(key, None)

class SdlGuid(Structure):
    _fields_ = [("data", c_uint8 * 16)]

def decode(value):
    return (value or b"").decode("utf-8", errors="replace")

def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""

def input_metadata_for_device_path(device_path):
    if not device_path:
        return {}
    name = Path(device_path).name
    roots = []
    if name.startswith("event"):
        roots.append(Path("/sys/class/input") / name / "device")
    elif name.startswith("hidraw"):
        hid_root = Path("/sys/class/hidraw") / name / "device"
        try:
            roots.extend(sorted(hid_root.glob("input/input*/")))
        except OSError:
            pass
    for root in roots:
        input_name = read_text(root / "name")
        if "imu" in input_name.lower():
            continue
        modalias = read_text(root / "modalias").lower()
        if input_name and re.search(r"(pro controller|nintendo switch pro|joy-?con|8bitdo|ultimate 2c|v057ep2009|v2dc8p(310b|301a))", f"{input_name} {modalias}", re.I):
            return {
                "uniq": read_text(root / "uniq").upper(),
                "modalias": modalias,
                "name": input_name,
            }
    return {}

def ryubing_guid(raw_guid):
    raw = "".join(ch for ch in raw_guid.lower() if ch in "0123456789abcdef")
    if len(raw) != 32:
        return ""
    return f"{raw[4:6]}{raw[6:8]}{raw[2:4]}{raw[0:2]}-{raw[10:12]}{raw[8:10]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"

def vid_pid_from_modalias(modalias):
    match = re.search(r"v([0-9a-fA-F]{4})p([0-9a-fA-F]{4})", modalias or "")
    if not match:
        return "", ""
    return match.group(1).lower(), match.group(2).lower()

def stable_ryubing_guid(raw_guid, input_meta=None):
    guid = ryubing_guid(raw_guid)
    if not guid:
        return ""
    return "0000" + guid[4:]

assert stable_ryubing_guid("0500d71f7e0500000920000001800000") == "00000005-057e-0000-0920-000001800000"
assert stable_ryubing_guid("030077557e0500000920000000026803", {"modalias": "input:b0003v057ep2009"}) == "00000003-057e-0000-0920-000000026803"

def player_order():
    try:
        raw = json.loads(resolved_order_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    result = {}
    for row in raw.get("players", []):
        try:
            player = int(row.get("player"))
        except (TypeError, ValueError):
            continue
        identities = [
            str(row.get("identity") or "").upper(),
            str(row.get("xemu_guid") or "").upper(),
        ]
        for ident in identities:
            if 1 <= player <= 4 and ident:
                result[ident] = player
    return result

def enumerate_sdl_gamepads():
    if not sdl_lib_path.exists():
        log_warning(f"Ryubing SDL3 library is missing: {sdl_lib_path}")
        return []
    try:
        sdl = ctypes.CDLL(str(sdl_lib_path))
    except OSError as exc:
        log_warning(f"could not load Ryubing SDL3 library {sdl_lib_path}: {exc}")
        return []

    sdl.SDL_Init.argtypes = [c_uint32]
    sdl.SDL_Init.restype = c_bool
    sdl.SDL_GetError.restype = c_char_p
    sdl.SDL_GetGamepads.argtypes = [POINTER(c_int)]
    sdl.SDL_GetGamepads.restype = POINTER(c_uint32)
    sdl.SDL_GetGamepadNameForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadNameForID.restype = c_char_p
    sdl.SDL_GetGamepadPathForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadPathForID.restype = c_char_p
    sdl.SDL_GetGamepadGUIDForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadGUIDForID.restype = SdlGuid
    sdl.SDL_GUIDToString.argtypes = [SdlGuid, ctypes.c_char_p, c_int]
    sdl.SDL_GetGamepadTypeForID.argtypes = [c_uint32]
    sdl.SDL_GetGamepadTypeForID.restype = c_int
    sdl.SDL_OpenGamepad.argtypes = [c_uint32]
    sdl.SDL_OpenGamepad.restype = c_void_p
    sdl.SDL_CloseGamepad.argtypes = [c_void_p]
    sdl.SDL_free.argtypes = [c_void_p]
    sdl.SDL_Quit.argtypes = []

    SDL_INIT_JOYSTICK = 0x00000200
    SDL_INIT_GAMEPAD = 0x00002000
    SDL_INIT_EVENTS = 0x00004000
    if not sdl.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMEPAD | SDL_INIT_EVENTS):
        log_warning(f"SDL3 gamepad initialization failed: {decode(sdl.SDL_GetError())}")
        return []
    try:
        count = c_int()
        ids = sdl.SDL_GetGamepads(ctypes.byref(count))
        gamepads = []
        try:
            for index in range(count.value):
                instance_id = ids[index]
                handle = sdl.SDL_OpenGamepad(instance_id)
                if not handle:
                    log_warning(
                        f"SDL3 listed gamepad index {index} but could not open it: {decode(sdl.SDL_GetError())}"
                    )
                    continue
                try:
                    guid = sdl.SDL_GetGamepadGUIDForID(instance_id)
                    guid_buffer = ctypes.create_string_buffer(64)
                    sdl.SDL_GUIDToString(guid, guid_buffer, len(guid_buffer))
                    device_path = decode(sdl.SDL_GetGamepadPathForID(instance_id))
                    raw_guid = guid_buffer.value.decode("ascii", errors="replace")
                    input_meta = input_metadata_for_device_path(device_path)
                    gamepads.append(
                        {
                            "sdl_index": index,
                            "instance_id": int(instance_id),
                            "name": decode(sdl.SDL_GetGamepadNameForID(instance_id)),
                            "path": device_path,
                            "guid": raw_guid,
                            "ryubing_guid": stable_ryubing_guid(raw_guid, input_meta),
                            "uniq": input_meta.get("uniq", ""),
                            "modalias": input_meta.get("modalias", ""),
                            "type": int(sdl.SDL_GetGamepadTypeForID(instance_id)),
                        }
                    )
                finally:
                    sdl.SDL_CloseGamepad(handle)
        finally:
            if ids:
                sdl.SDL_free(ids)
        return gamepads
    finally:
        sdl.SDL_Quit()

def assign_ryubing_ids(gamepads):
    used = set()
    duplicate_counts = {}
    for gamepad in gamepads:
        guid = gamepad.get("ryubing_guid", "")
        if not guid:
            continue
        prefix = duplicate_counts.get(guid, 0)
        candidate = f"{prefix}-{guid}"
        while candidate in used:
            prefix += 1
            candidate = f"{prefix}-{guid}"
        duplicate_counts[guid] = prefix + 1
        used.add(candidate)
        gamepad["ryubing_id"] = candidate

def controller_config(gamepad, player):
    return {
        "left_joycon_stick": {
            "joystick": "Left",
            "invert_stick_x": False,
            "invert_stick_y": False,
            "rotate90_cw": False,
            "stick_button": "LeftStick",
        },
        "right_joycon_stick": {
            "joystick": "Right",
            "invert_stick_x": False,
            "invert_stick_y": False,
            "rotate90_cw": False,
            "stick_button": "RightStick",
        },
        "deadzone_left": 0.05,
        "deadzone_right": 0.05,
        "range_left": 1.0,
        "range_right": 1.0,
        "trigger_threshold": 0.0,
        "motion": {
            "motion_backend": "GamepadDriver",
            "sensitivity": 100,
            "gyro_deadzone": 1,
            "enable_motion": False,
        },
        "rumble": {
            "strong_rumble": 1.0,
            "weak_rumble": 1.0,
            "enable_rumble": True,
        },
        "led": {
            "enable_led": False,
            "turn_off_led": False,
            "use_rainbow": False,
            "led_color": 4278518269,
        },
        "left_joycon": {
            "button_minus": "Back",
            "button_l": "LeftShoulder",
            "button_zl": "LeftTrigger",
            "button_sl": "Unbound",
            "button_sr": "Unbound",
            "dpad_up": "DpadUp",
            "dpad_down": "DpadDown",
            "dpad_left": "DpadLeft",
            "dpad_right": "DpadRight",
        },
        "right_joycon": {
            "button_plus": "Start",
            "button_r": "RightShoulder",
            "button_zr": "RightTrigger",
            "button_sl": "Unbound",
            "button_sr": "Unbound",
            "button_x": "X",
            "button_b": "B",
            "button_y": "Y",
            "button_a": "A",
        },
        "version": 1,
        "backend": "GamepadSDL3",
        "id": gamepad["ryubing_id"],
        "name": gamepad["name"],
        "controller_type": "ProController",
        "player_index": f"Player{player}",
    }

def assign_players(gamepads):
    order = player_order()
    assigned = {}
    used_players = set()
    for gamepad in gamepads:
        preferred = order.get(gamepad["uniq"])
        if preferred and preferred not in used_players:
            assigned[gamepad["instance_id"]] = preferred
            used_players.add(preferred)
    next_player = 1
    for gamepad in gamepads:
        if gamepad["instance_id"] in assigned:
            continue
        while next_player in used_players and next_player <= 4:
            next_player += 1
        if next_player > 4:
            break
        assigned[gamepad["instance_id"]] = next_player
        used_players.add(next_player)
    return assigned

def managed_input_config():
    gamepads = enumerate_sdl_gamepads()
    if not gamepads:
        log_warning("no SDL3 gamepads detected for Ryubing; controller input will be unavailable")
        return []
    assign_ryubing_ids(gamepads)
    if len(gamepads) < 4:
        log_warning(f"Ryubing detected {len(gamepads)} SDL3 gamepad(s); up to 4 are supported when connected before launch")
    assigned = assign_players(gamepads)
    configs = []
    for gamepad in gamepads:
        player = assigned.get(gamepad["instance_id"])
        if player is None or player > 4:
            continue
        if not gamepad.get("ryubing_id"):
            log_warning(f"Ryubing skipped SDL3 gamepad with unparsable GUID: {gamepad}")
            continue
        log_event(
            "ryubing-input",
            "detected SDL3 controller "
            + json.dumps(
                {
                    "name": gamepad["name"],
                    "path": gamepad["path"],
                    "uniq": gamepad["uniq"],
                    "raw_guid": gamepad["guid"],
                    "ryubing_guid": gamepad["ryubing_guid"],
                    "ryubing_id": gamepad["ryubing_id"],
                    "player": player,
                },
                sort_keys=True,
            ),
        )
        configs.append(controller_config(gamepad, player))
    configs.sort(key=lambda row: row["player_index"])
    if not configs:
        log_warning(f"Ryubing detected {len(gamepads)} SDL3 gamepad(s) but generated no input profiles")
    else:
        log_event(
            "ryubing-input",
            "generated input profiles "
            + json.dumps(
                [
                    {
                        "id": row["id"],
                        "player_index": row["player_index"],
                        "controller_type": row["controller_type"],
                    }
                    for row in configs
                ],
                sort_keys=True,
            ),
        )
    return configs

def verify_managed_config(config):
    expected = sorted(assign_players(enumerate_sdl_gamepads()).values())
    expected = [player for player in expected if 1 <= player <= 4]
    actual = sorted(
        int(str(row.get("player_index", "")).removeprefix("Player"))
        for row in config.get("input_config", [])
        if row.get("backend") == "GamepadSDL3"
        and row.get("controller_type") == "ProController"
        and str(row.get("player_index", "")).removeprefix("Player").isdigit()
    )
    if expected and actual != expected:
        raise SystemExit(f"Ryubing input config verification failed: expected players {expected}, generated {actual}")
    for row in config.get("input_config", []):
        if row.get("backend") == "WindowKeyboard":
            raise SystemExit("Ryubing input config verification failed: stale WindowKeyboard profile remains")
        if row.get("backend") == "GamepadSDL3" and not re.match(r"^[0-9]+-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", str(row.get("id", ""))):
            raise SystemExit(f"Ryubing input config verification failed: invalid SDL3 id {row.get('id')!r}")

config.update(
    {
        "backend_threading": "Auto",
        "res_scale": 2,
        "res_scale_custom": 1,
        "max_anisotropy": 16,
        "aspect_ratio": "Fixed16x9",
        "anti_aliasing": "None",
        "scaling_filter": "Bilinear",
        "scaling_filter_level": 80,
        "docked_mode": True,
        "check_updates_on_start": False,
        "show_confirm_exit": False,
        "hide_cursor": 1,
        "enable_vsync": False,
        "enable_shader_cache": True,
        "enable_texture_recompression": False,
        "enable_macro_hle": True,
        "enable_ptc": True,
        "audio_backend": "SDL3",
        "audio_volume": 1,
        "start_fullscreen": True,
        "show_console": False,
        "use_input_global_config": True,
        "enable_keyboard": True,
        "enable_mouse": False,
        "graphics_backend": "Vulkan",
        "preferred_gpu": "0x1002_0x73EF",
    }
)
config["input_config"] = managed_input_config()
verify_managed_config(config)
hotkeys = config.setdefault("hotkeys", {})
hotkeys.update({"show_ui": "F4", "screenshot": "F8", "pause": "F5"})

tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(config, indent=2, sort_keys=False) + "\n", encoding="utf-8")
tmp.replace(path)
PY

      ${pkgs.python3}/bin/python3 - "${cfg.biosRoot}/switch" "$ryujinx_firmware_dir" "$ryujinx_firmware_marker" <<'PY'
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

bios_dir = Path(sys.argv[1])
registered_dir = Path(sys.argv[2])
marker_path = Path(sys.argv[3])

def version_key(path):
    return [int(part) for part in re.findall(r"\d+", path.name)]

archives = sorted(
    [path for path in bios_dir.glob("Firmware*.zip") if path.is_file()],
    key=version_key,
)
if not archives:
    print(f"WARNING: no Ryubing firmware archive found under {bios_dir}", file=sys.stderr)
    raise SystemExit(0)

source = archives[-1]
resolved = source.resolve()
sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
registered_count = len(
    [
        path
        for path in registered_dir.glob("*.nca")
        if path.is_dir() and (path / "00").is_file()
    ]
)
marker = {}
if marker_path.exists():
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        marker = {}

if marker.get("sha256") == sha256 and registered_count > 0:
    print(f"Ryubing firmware already installed from {source} ({registered_count} NCA entries)")
    raise SystemExit(0)

with zipfile.ZipFile(source) as archive:
    names = [
        name
        for name in archive.namelist()
        if not name.endswith("/") and Path(name).name.lower().endswith(".nca")
    ]
    if not names:
        raise SystemExit(f"Firmware archive contains no NCA files: {source}")

    registered_dir.mkdir(parents=True, exist_ok=True)
    for child in registered_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    for name in names:
        nca_name = Path(name.replace(".cnmt", "")).name
        target = registered_dir / nca_name / "00"
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(name) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)

marker_path.write_text(
    json.dumps(
        {
            "source": str(source),
            "resolved": str(resolved),
            "sha256": sha256,
            "file_count": len(names),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print(f"Installed Ryubing firmware from {source} ({len(names)} NCA files)")
PY

      for key_name in prod.keys title.keys; do
        key_source="${cfg.biosRoot}/switch/$key_name"
        key_target="$ryujinx_system_dir/$key_name"
        if [ -r "$key_source" ] && { [ ! -e "$key_target" ] || [ -L "$key_target" ]; }; then
          ln -sfn "$key_source" "$key_target"
        elif [ ! -r "$key_source" ]; then
          log_event "warning" "missing Ryubing key: $key_source"
        fi
      done

      ${pkgs.python3}/bin/python3 - "$rom_path" "$ryujinx_config_dir" "${cfg.biosRoot}/switch/prod.keys" "${pkgs.nstool}/bin/nstool" <<'PY'
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

rom_path = Path(sys.argv[1])
ryujinx_config_dir = Path(sys.argv[2])
key_path = Path(sys.argv[3])
nstool = sys.argv[4]
cache_path = ryujinx_config_dir / "package-metadata-cache.json"

TITLE_RE = re.compile(r"(?i)(?<![0-9a-f])([0-9a-f]{16})(?![0-9a-f])")
VERSION_RE = re.compile(r"(?i)\[v([0-9]+)\]")

def title_ids_from_name(path):
    return [match.lower() for match in TITLE_RE.findall(path.name)]

def version_from_name(path):
    match = VERSION_RE.search(path.name)
    return int(match.group(1)) if match else 0

def base_id(title_id):
    return f"{(int(title_id, 16) & ~0x1fff):016x}"

base_ids = title_ids_from_name(rom_path)
if not base_ids:
    raise SystemExit(0)

application_id_base = base_id(base_ids[0])
game_dir = ryujinx_config_dir / "games" / application_id_base
game_dir.mkdir(parents=True, exist_ok=True)
global_config_path = ryujinx_config_dir / "Config.json"
title_config_path = game_dir / "Config.json"

def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback

global_config = load_json(global_config_path, {})
if isinstance(global_config, dict):
    title_config = load_json(title_config_path, global_config)
    if not isinstance(title_config, dict):
        title_config = dict(global_config)
    title_config["use_input_global_config"] = False
    for key in ("input_config", "enable_keyboard", "enable_mouse", "disable_input_when_out_of_focus"):
        if key in global_config:
            title_config[key] = global_config[key]
    title_config_path.write_text(json.dumps(title_config, indent=2) + "\n", encoding="utf-8")

cache = load_json(cache_path, {})
if not isinstance(cache, dict):
    cache = {}

def cache_key(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }

def cached_metadata(path):
    key = cache_key(path)
    if key is None:
        return None
    row = cache.get(str(path))
    if not isinstance(row, dict):
        return None
    if row.get("size") == key["size"] and row.get("mtime_ns") == key["mtime_ns"]:
        metadata = row.get("metadata")
        return metadata if isinstance(metadata, dict) else None
    return None

def ryubing_pfs_path(path):
    return path if path.startswith("/") else f"/{path}"

def normalize_dlc_ncas(dlc_ncas):
    if not isinstance(dlc_ncas, list):
        return []
    normalized = []
    for dlc_nca in dlc_ncas:
        if not isinstance(dlc_nca, dict):
            continue
        nca_path = dlc_nca.get("path")
        if not isinstance(nca_path, str) or not nca_path:
            continue
        row = dict(dlc_nca)
        row["path"] = ryubing_pfs_path(nca_path)
        normalized.append(row)
    return normalized

def save_cache(path, metadata):
    key = cache_key(path)
    if key is None:
        return
    cache[str(path)] = {
        "size": key["size"],
        "mtime_ns": key["mtime_ns"],
        "metadata": metadata,
    }

def nstool_output(args, timeout=20):
    command = [nstool]
    if key_path.is_file():
        command += ["-k", str(key_path)]
    command += args
    return subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    ).stdout

def package_tree(path):
    output = nstool_output(["--fstree", str(path)])
    names = []
    for line in output.splitlines():
        stripped = line.strip()
        if re.match(r"^[0-9a-f]{32}\.(?:nca|cnmt\.nca|cnmt\.xml)$", stripped, re.I):
            names.append(stripped)
        elif re.match(r"^[0-9a-f]{16}[0-9a-f]{16}\.(?:tik|cert)$", stripped, re.I):
            names.append(stripped)
    return names

def extract_cnmt_xml(package_path, cnmt_name):
    with tempfile.TemporaryDirectory(prefix="ryubing-cnmt.") as tmpdir:
        target = Path(tmpdir) / "content.cnmt.xml"
        nstool_output(["-x", f"/{cnmt_name}", str(target), str(package_path)])
        if not target.is_file():
            return None
        try:
            return ET.fromstring(target.read_text(encoding="utf-8"))
        except ET.ParseError:
            return None

def inspect_package(path, expected_kind):
    names = package_tree(path)
    filename_ids = title_ids_from_name(path)
    title_id = filename_ids[0] if filename_ids else None
    version = version_from_name(path)
    content_type = "update" if expected_kind == "update" else "dlc"
    original_id = base_id(title_id) if title_id else None
    dlc_ncas = []

    for cnmt_name in [name for name in names if name.lower().endswith(".cnmt.xml")]:
        root = extract_cnmt_xml(path, cnmt_name)
        if root is None:
            continue
        cnmt_type = (root.findtext("Type") or "").strip()
        cnmt_id = (root.findtext("Id") or "").strip().removeprefix("0x").lower()
        cnmt_version = root.findtext("Version")
        if cnmt_id:
            title_id = cnmt_id
        if cnmt_version and cnmt_version.isdigit():
            version = int(cnmt_version)
        if cnmt_type == "Patch":
            content_type = "update"
            original_id = (root.findtext("OriginalId") or "").strip().removeprefix("0x").lower()
        elif cnmt_type == "AddOnContent":
            content_type = "dlc"
            original_id = (root.findtext("ApplicationId") or "").strip().removeprefix("0x").lower()
            for content in root.findall("Content"):
                if (content.findtext("Type") or "").strip() != "Data":
                    continue
                content_id = (content.findtext("Id") or "").strip().lower()
                if content_id:
                    full_path = f"{content_id}.nca"
                    if full_path in names:
                        dlc_ncas.append({"title_id": int(title_id, 16), "path": ryubing_pfs_path(full_path), "is_enabled": True})
        if title_id:
            break

    if not title_id:
        for name in names:
            match = re.match(r"^([0-9a-f]{16})[0-9a-f]{16}\.tik$", name, re.I)
            if match:
                title_id = match.group(1).lower()
                original_id = base_id(title_id)
                break

    if content_type == "dlc" and title_id and not dlc_ncas:
        nca_names = [name for name in names if name.lower().endswith(".nca") and ".cnmt." not in name.lower()]
        if len(nca_names) == 1:
            dlc_ncas.append({"title_id": int(title_id, 16), "path": ryubing_pfs_path(nca_names[0]), "is_enabled": True})

    if title_id and not original_id:
        original_id = base_id(title_id)

    return {
        "path": str(path),
        "title_id": title_id,
        "base_id": original_id,
        "version": version,
        "content_type": content_type,
        "dlc_ncas": dlc_ncas,
    }

def metadata_for(path, expected_kind):
    filename_ids = title_ids_from_name(path)
    cached = cached_metadata(path)
    if cached is not None:
        metadata = dict(cached)
        metadata["dlc_ncas"] = normalize_dlc_ncas(metadata.get("dlc_ncas"))
        if filename_ids:
            metadata["title_id"] = filename_ids[0]
            metadata["base_id"] = base_id(filename_ids[0])
        if version_from_name(path):
            metadata["version"] = version_from_name(path)
        return metadata

    if expected_kind == "update" and filename_ids and version_from_name(path):
        return {
            "path": str(path),
            "title_id": filename_ids[0],
            "base_id": base_id(filename_ids[0]),
            "version": version_from_name(path),
            "content_type": "update",
            "dlc_ncas": [],
        }

    try:
        metadata = inspect_package(path, expected_kind)
    except Exception as exc:
        print(f"WARNING: failed to inspect Switch package {path}: {exc}", file=sys.stderr)
        if not filename_ids:
            return None
        metadata = {
            "path": str(path),
            "title_id": filename_ids[0],
            "base_id": base_id(filename_ids[0]),
            "version": version_from_name(path),
            "content_type": expected_kind,
            "dlc_ncas": [],
        }
    save_cache(path, metadata)
    return metadata

def direct_nsp_files(directory):
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".nsp")

rom_dir = rom_path.parent
updates = []
for path in direct_nsp_files(rom_dir / ".updates"):
    metadata = metadata_for(path, "update")
    if metadata and metadata.get("content_type") == "update" and metadata.get("base_id") == application_id_base:
        updates.append(metadata)
    elif metadata:
        print(f"WARNING: ignoring non-matching Ryubing update package: {path}", file=sys.stderr)

dlcs = []
for path in direct_nsp_files(rom_dir / ".dlc"):
    metadata = metadata_for(path, "dlc")
    if metadata and metadata.get("content_type") == "dlc" and metadata.get("base_id") == application_id_base:
        dlcs.append(metadata)
    elif metadata:
        print(f"WARNING: ignoring non-matching Ryubing DLC package: {path}", file=sys.stderr)

existing_updates_path = game_dir / "updates.json"
existing_updates = load_json(existing_updates_path, {})
existing_update_paths = []
if isinstance(existing_updates, dict):
    existing_update_paths = existing_updates.get("paths") or existing_updates.get("Paths") or []
existing_update_paths = [path for path in existing_update_paths if isinstance(path, str) and Path(path).is_file()]

update_by_path = {path: {"path": path, "version": version_from_name(Path(path))} for path in existing_update_paths}
for update in updates:
    update_by_path[update["path"]] = update

if update_by_path:
    selected = max(update_by_path.values(), key=lambda row: int(row.get("version") or 0))["path"]
    existing_updates_path.write_text(
        json.dumps({"selected": selected, "paths": sorted(update_by_path)}, indent=2) + "\n",
        encoding="utf-8",
    )

existing_dlc_path = game_dir / "dlc.json"
existing_dlc = load_json(existing_dlc_path, [])
dlc_by_path = {}
if isinstance(existing_dlc, list):
    for container in existing_dlc:
        if not isinstance(container, dict):
            continue
        container_path = container.get("path")
        if isinstance(container_path, str) and Path(container_path).is_file():
            container = dict(container)
            container["dlc_nca_list"] = normalize_dlc_ncas(container.get("dlc_nca_list"))
            dlc_by_path[container_path] = container

for dlc in dlcs:
    if not dlc.get("dlc_ncas"):
        print(f"WARNING: no DLC NCA path found for {dlc['path']}", file=sys.stderr)
        continue
    dlc_by_path[dlc["path"]] = {
        "path": dlc["path"],
        "dlc_nca_list": dlc["dlc_ncas"],
    }

if dlc_by_path:
    existing_dlc_path.write_text(
        json.dumps([dlc_by_path[path] for path in sorted(dlc_by_path)], indent=2) + "\n",
        encoding="utf-8",
    )

cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

      case "$system_id:$emulator_id:$rom_path" in
        switch:ryubing:*.nro|switch:ryubing:*.NRO)
          rom_dir="$(dirname "$rom_path")"
          asset_source="$rom_dir/data"
          asset_target="$ryujinx_sdcard_dir/data"
          if [ -d "$asset_source" ]; then
            if [ ! -e "$asset_target" ] || [ -L "$asset_target" ]; then
              ln -sfn "$asset_source" "$asset_target"
              log_event "runtime" "linked Ryubing homebrew data: $asset_target -> $asset_source"
            elif [ -d "$asset_target" ]; then
              log_event "runtime" "kept existing Ryubing sdcard data directory: $asset_target"
            else
              log_event "warning" "Ryubing sdcard data path exists and is not a directory or symlink: $asset_target"
            fi
          fi
          ;;
      esac
    }

    prepare_pico8_runtime() {
      pico8_home="${cfg.configRoot}/emulators/pico8"
      pico8_root="${cfg.romRoot}/Fantasy - PICO-8 (2015)"
      pico8_cdata="${cfg.dataRoot}/saves/pico8"
      pico8_desktop="${cfg.dataRoot}/screenshots/pico8"
      mkdir -p "$pico8_home" "$pico8_root" "$pico8_cdata" "$pico8_desktop"
      ${pkgs.gnused}/bin/sed 's/^    //' >"$pico8_home/config.txt" <<EOF
    // Managed by Nix/run-emulator before each PICO-8 launch.
    root_path $pico8_root
    cdata_path $pico8_cdata
    desktop_path $pico8_desktop
    joystick_index 0
    button_keys 0 0 0 0 0 0 0 0 0 0 0 0
    gif_len 8
    screenshot_scale 3
    gif_scale 3
EOF
      if [ -r "${cfg.configRoot}/controllers/gamecontrollerdb.txt" ]; then
        cp -f "${cfg.configRoot}/controllers/gamecontrollerdb.txt" "$pico8_home/sdl_controllers.txt"
      elif [ ! -e "$pico8_home/sdl_controllers.txt" ]; then
        : >"$pico8_home/sdl_controllers.txt"
      fi
      log_event "runtime" "prepared PICO-8 home config at $pico8_home"
    }

    prepare_dolphin_runtime() {
      dolphin_config_dir="$XDG_CONFIG_HOME/dolphin-emu"
      mkdir -p "$dolphin_config_dir"
      dolphin_p1_device=0
      dolphin_p2_device=0
      dolphin_p3_device=0
      dolphin_p4_device=0
      case "''${resolved_player_count:-0}" in
        1) dolphin_p1_device=6 ;;
        2) dolphin_p1_device=6; dolphin_p2_device=6 ;;
        3) dolphin_p1_device=6; dolphin_p2_device=6; dolphin_p3_device=6 ;;
        4) dolphin_p1_device=6; dolphin_p2_device=6; dolphin_p3_device=6; dolphin_p4_device=6 ;;
      esac
      cat >"$dolphin_config_dir/Dolphin.ini" <<EOF
[Analytics]
PermissionAsked = True
Enabled = False
[Core]
CPUThread = True
SkipIPL = True
GFXBackend = Vulkan
SIDevice0 = $dolphin_p1_device
SIDevice1 = $dolphin_p2_device
SIDevice2 = $dolphin_p3_device
SIDevice3 = $dolphin_p4_device
WiimoteContinuousScanning = True
WiimoteEnableSpeaker = False
[Display]
Fullscreen = True
RenderWindowWidth = 1920
RenderWindowHeight = 1080
RenderWindowAutoSize = False
[Interface]
ConfirmStop = False
UsePanicHandlers = False
OnScreenDisplayMessages = True
[General]
HotkeysRequireFocus = False
[DSP]
DSPThread = True
Backend = Cubeb
Volume = 100
EOF
      : >"$dolphin_config_dir/GCPadNew.ini"
      : >"$dolphin_config_dir/WiimoteNew.ini"
      jq -c '.players[]?' "$resolved_controllers" 2>/dev/null | while read -r controller; do
        slot="$(jq -r '.player' <<<"$controller")"
        index="$(jq -r '.sdl2_index' <<<"$controller")"
        name="$(jq -r '.name // "Nintendo Switch Pro Controller"' <<<"$controller")"
        sdl_name="$(jq -r '.sdl_name // .name // "Nintendo Switch Pro Controller"' <<<"$controller")"
        cat >>"$dolphin_config_dir/GCPadNew.ini" <<EOF
[GCPad$slot]
Device = SDL/$index/$sdl_name
Buttons/A = \`Button B\`
Buttons/B = \`Button Y\`
Buttons/X = \`Button A\`
Buttons/Y = \`Button X\`
Buttons/Z = \`Trigger R\`
Buttons/Start = \`Start\`
Main Stick/Up = \`Axis 1-\`
Main Stick/Down = \`Axis 1+\`
Main Stick/Left = \`Axis 0-\`
Main Stick/Right = \`Axis 0+\`
Main Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
C-Stick/Up = \`Axis 3-\`
C-Stick/Down = \`Axis 3+\`
C-Stick/Left = \`Axis 2-\`
C-Stick/Right = \`Axis 2+\`
C-Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
Triggers/L = \`Shoulder L\`
Triggers/R = \`Shoulder R\`
D-Pad/Up = \`Hat 0 N\`
D-Pad/Down = \`Hat 0 S\`
D-Pad/Left = \`Hat 0 W\`
D-Pad/Right = \`Hat 0 E\`

[GCPad$slot/Options]
Always Connected = True
EOF
        cat >>"$dolphin_config_dir/WiimoteNew.ini" <<EOF
[Wiimote$slot]
Source = 1
Device = SDL/$index/$sdl_name
Buttons/A = \`Button B\`
Buttons/B = \`Trigger L\`
Buttons/1 = \`Button A\`
Buttons/2 = \`Button X\`
Buttons/- = \`Back\`
Buttons/+ = \`Start\`
Buttons/Home = \`Misc 1\`
D-Pad/Up = \`Hat 0 N\`
D-Pad/Down = \`Hat 0 S\`
D-Pad/Left = \`Hat 0 W\`
D-Pad/Right = \`Hat 0 E\`
IR/Up = \`Axis 3-\`
IR/Down = \`Axis 3+\`
IR/Left = \`Axis 2-\`
IR/Right = \`Axis 2+\`
Shake/X = \`Shoulder R\`
Shake/Y = \`Shoulder R\`
Shake/Z = \`Shoulder R\`
Extension = Nunchuk
Nunchuk/Buttons/C = \`Back\`
Nunchuk/Buttons/Z = \`Guide\`
Nunchuk/Stick/Up = \`Axis 1-\`
Nunchuk/Stick/Down = \`Axis 1+\`
Nunchuk/Stick/Left = \`Axis 0-\`
Nunchuk/Stick/Right = \`Axis 0+\`
Nunchuk/Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
EOF
      done
      cat >>"$dolphin_config_dir/WiimoteNew.ini" <<'EOF'
[BalanceBoard]
Source = 0
EOF
      if [ "''${EMULATION_DOLPHIN_HOTKEY_FALLBACK:-0}" = "1" ]; then
        cat >"$dolphin_config_dir/Hotkeys.ini" <<'EOF'
[Hotkeys]
Device = XInput2/0/Virtual core pointer
General/Toggle Pause = F10
General/Reset = @(Ctrl+R)
General/Take Screenshot = F9
Emulation Speed/Disable Emulation Speed Limit = Tab
Load State/Load State Slot 1 = F1
Save State/Save State Slot 1 = @(Shift+F1)
EOF
        log_event "runtime" "prepared Dolphin keyboard fallback hotkeys"
      fi
      log_event "runtime" "prepared Dolphin kiosk config"
    }

    prepare_pcsx2_runtime() {
      pcsx2_data_dir="$XDG_CONFIG_HOME/PCSX2"
      pcsx2_ini_dir="$pcsx2_data_dir/inis"
      pcsx2_memcards_dir="${cfg.dataRoot}/saves/pcsx2/memcards"
      pcsx2_savestates_dir="${cfg.dataRoot}/states/pcsx2"
      pcsx2_snapshots_dir="${cfg.dataRoot}/screenshots/pcsx2"
      pcsx2_logs_dir="${cfg.dataRoot}/logs/pcsx2"
      pcsx2_cache_dir="${cfg.dataRoot}/cache/pcsx2"
      pcsx2_cheats_dir="${cfg.configRoot}/emulators/pcsx2/cheats"
      pcsx2_patches_dir="${cfg.configRoot}/emulators/pcsx2/patches"
      pcsx2_textures_dir="${cfg.configRoot}/emulators/pcsx2/textures"
      pcsx2_gamesettings_dir="${cfg.configRoot}/emulators/pcsx2/gamesettings"
      ps2_rom_dir="${cfg.romRoot}/Sony - PlayStation 2 (2000)"
      retroachievements_env="/run/ghostship-secrets/emulation-retroachievements.env"
      pcsx2_achievements_enabled="false"
      pcsx2_achievements_user=""

      if [ -r "$retroachievements_env" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$retroachievements_env"
        set +a
        pcsx2_achievements_user="''${RETROACHIEVEMENTS_USER:-}"
        if [ -n "''${RETROACHIEVEMENTS_USER:-}" ] && [ -n "''${RETROACHIEVEMENTS_TOKEN:-}" ]; then
          pcsx2_achievements_enabled="true"
        fi
      fi

      mkdir -p \
        "$pcsx2_ini_dir" \
        "$pcsx2_memcards_dir" \
        "$pcsx2_savestates_dir" \
        "$pcsx2_snapshots_dir" \
        "$pcsx2_logs_dir" \
        "$pcsx2_cache_dir" \
        "$pcsx2_cheats_dir" \
        "$pcsx2_patches_dir" \
        "$pcsx2_textures_dir" \
        "$pcsx2_gamesettings_dir"

      bios_name="$(find "${cfg.biosRoot}" -maxdepth 1 -type f \( -iname 'scph*.bin' -o -iname 'ps2*.bin' \) -size +1M -printf '%f\n' 2>/dev/null | sort | head -n 1 || true)"
      pcsx2_ini="$pcsx2_ini_dir/PCSX2.ini"
      cat >"$pcsx2_ini" <<EOF
[UI]
SettingsVersion = 1
SetupWizardIncomplete = false
InhibitScreensaver = true
ConfirmShutdown = false
StartPaused = false
PauseOnFocusLoss = false
StartFullscreen = true
HideMouseCursor = true
HideMainWindowWhenRunning = true
RenderToSeparateWindow = false

[Folders]
Bios = ${cfg.biosRoot}
Snapshots = $pcsx2_snapshots_dir
Savestates = $pcsx2_savestates_dir
SaveStates = $pcsx2_savestates_dir
MemoryCards = $pcsx2_memcards_dir
Logs = $pcsx2_logs_dir
Cheats = $pcsx2_cheats_dir
Patches = $pcsx2_patches_dir
GameSettings = $pcsx2_gamesettings_dir
Cache = $pcsx2_cache_dir
Textures = $pcsx2_textures_dir
InputProfiles = $pcsx2_data_dir/inputprofiles
Videos = ${cfg.dataRoot}/videos/pcsx2

[Filenames]
BIOS = $bios_name

[GameList]
RecursivePaths = $ps2_rom_dir

[EmuCore]
EnablePatches = true
EnableCheats = false
EnableWideScreenPatches = false
EnableNoInterlacingPatches = false
McdFolderAutoManage = true
UseSavestateSelector = true
SaveStateOnShutdown = false

[EmuCore/Speedhacks]
EECycleRate = 0
EECycleSkip = 0
vuThread = true
fastCDVD = false

[EmuCore/GS]
Renderer = 14
UpscaleMultiplier = 3.0
VsyncQueueSize = 2
AspectRatio = 0
FMVAspectRatioSwitch = 0
TextureFiltering = 2
MaxAnisotropy = 0
OsdShowMessages = true
OsdShowSpeed = false
OsdShowFPS = true
OsdShowResolution = false
OsdShowCPU = false
OsdShowGPU = false
OsdShowGSStats = false
OsdShowSettings = false

[MemoryCards]
Slot1_Enable = true
Slot1_Filename = Mcd001.ps2
Slot2_Enable = true
Slot2_Filename = Mcd002.ps2

[InputSources]
SDL = true
SDLControllerEnhancedMode = true

[Pad]
MultitapPort1 = true
MultitapPort2 = false

[Pad1]
Type = DualShock2
Up = SDL-0/DPadUp
Right = SDL-0/DPadRight
Down = SDL-0/DPadDown
Left = SDL-0/DPadLeft
Triangle = SDL-0/FaceNorth
Circle = SDL-0/FaceEast
Cross = SDL-0/FaceSouth
Square = SDL-0/FaceWest
Select = SDL-0/Back
Start = SDL-0/Start
L1 = SDL-0/LeftShoulder
L2 = SDL-0/+LeftTrigger
R1 = SDL-0/RightShoulder
R2 = SDL-0/+RightTrigger
L3 = SDL-0/LeftStick
R3 = SDL-0/RightStick
LUp = SDL-0/-LeftY
LRight = SDL-0/+LeftX
LDown = SDL-0/+LeftY
LLeft = SDL-0/-LeftX
RUp = SDL-0/-RightY
RRight = SDL-0/+RightX
RDown = SDL-0/+RightY
RLeft = SDL-0/-RightX
SmallMotor = SDL-0/SmallMotor
LargeMotor = SDL-0/LargeMotor

[Pad2]
Type = DualShock2
Up = SDL-1/DPadUp
Right = SDL-1/DPadRight
Down = SDL-1/DPadDown
Left = SDL-1/DPadLeft
Triangle = SDL-1/FaceNorth
Circle = SDL-1/FaceEast
Cross = SDL-1/FaceSouth
Square = SDL-1/FaceWest
Select = SDL-1/Back
Start = SDL-1/Start
L1 = SDL-1/LeftShoulder
L2 = SDL-1/+LeftTrigger
R1 = SDL-1/RightShoulder
R2 = SDL-1/+RightTrigger
L3 = SDL-1/LeftStick
R3 = SDL-1/RightStick
LUp = SDL-1/-LeftY
LRight = SDL-1/+LeftX
LDown = SDL-1/+LeftY
LLeft = SDL-1/-LeftX
RUp = SDL-1/-RightY
RRight = SDL-1/+RightX
RDown = SDL-1/+RightY
RLeft = SDL-1/-RightX
SmallMotor = SDL-1/SmallMotor
LargeMotor = SDL-1/LargeMotor

[Pad3]
Type = DualShock2
Up = SDL-2/DPadUp
Right = SDL-2/DPadRight
Down = SDL-2/DPadDown
Left = SDL-2/DPadLeft
Triangle = SDL-2/FaceNorth
Circle = SDL-2/FaceEast
Cross = SDL-2/FaceSouth
Square = SDL-2/FaceWest
Select = SDL-2/Back
Start = SDL-2/Start
L1 = SDL-2/LeftShoulder
L2 = SDL-2/+LeftTrigger
R1 = SDL-2/RightShoulder
R2 = SDL-2/+RightTrigger
L3 = SDL-2/LeftStick
R3 = SDL-2/RightStick
LUp = SDL-2/-LeftY
LRight = SDL-2/+LeftX
LDown = SDL-2/+LeftY
LLeft = SDL-2/-LeftX
RUp = SDL-2/-RightY
RRight = SDL-2/+RightX
RDown = SDL-2/+RightY
RLeft = SDL-2/-RightX
SmallMotor = SDL-2/SmallMotor
LargeMotor = SDL-2/LargeMotor

[Pad4]
Type = DualShock2
Up = SDL-3/DPadUp
Right = SDL-3/DPadRight
Down = SDL-3/DPadDown
Left = SDL-3/DPadLeft
Triangle = SDL-3/FaceNorth
Circle = SDL-3/FaceEast
Cross = SDL-3/FaceSouth
Square = SDL-3/FaceWest
Select = SDL-3/Back
Start = SDL-3/Start
L1 = SDL-3/LeftShoulder
L2 = SDL-3/+LeftTrigger
R1 = SDL-3/RightShoulder
R2 = SDL-3/+RightTrigger
L3 = SDL-3/LeftStick
R3 = SDL-3/RightStick
LUp = SDL-3/-LeftY
LRight = SDL-3/+LeftX
LDown = SDL-3/+LeftY
LLeft = SDL-3/-LeftX
RUp = SDL-3/-RightY
RRight = SDL-3/+RightX
RDown = SDL-3/+RightY
RLeft = SDL-3/-RightX
SmallMotor = SDL-3/SmallMotor
LargeMotor = SDL-3/LargeMotor

[Achievements]
Enabled = $pcsx2_achievements_enabled
ChallengeMode = false
EncoreMode = false
SpectatorMode = false
UnofficialTestMode = false
Notifications = true
LeaderboardNotifications = true
SoundEffects = true
InfoSound = true
UnlockSound = true
LBSubmitSound = true
Overlays = true
LBOverlays = true
OverlayPosition = 8
NotificationPosition = 2
Username = $pcsx2_achievements_user

[Hotkeys]
ToggleFullscreen = Keyboard/Alt & Keyboard/Return
OpenPauseMenu = Keyboard/Escape
OpenPauseMenu = SDL-0/Back & SDL-0/FaceNorth
ResetVM = SDL-0/Back & SDL-0/FaceEast
LoadStateFromSlot1 = SDL-0/Back & SDL-0/LeftShoulder
SaveStateToSlot1 = SDL-0/Back & SDL-0/RightShoulder
Screenshot = Keyboard/F8
Screenshot = SDL-0/Back & SDL-0/FaceSouth
ToggleOSD = SDL-0/Back & SDL-0/FaceWest
HoldTurbo = Keyboard/Period
HoldTurbo = SDL-0/Back & SDL-0/+RightTrigger
ToggleTurbo = Keyboard/Tab
TogglePause = Keyboard/Space
EOF
      ${pkgs.python3}/bin/python3 - "$pcsx2_ini" "$resolved_controllers" <<'PY'
import json
import sys
from pathlib import Path

ini_path = Path(sys.argv[1])
resolved_path = Path(sys.argv[2])
try:
    players = json.loads(resolved_path.read_text(encoding="utf-8")).get("players", [])
except (OSError, json.JSONDecodeError):
    players = []
players = [p for p in players if 1 <= int(p.get("player", 0)) <= 4]
players.sort(key=lambda p: int(p["player"]))

def pad_section(player, sdl_index):
    return f"""[Pad{player}]
Type = DualShock2
Up = SDL-{sdl_index}/DPadUp
Right = SDL-{sdl_index}/DPadRight
Down = SDL-{sdl_index}/DPadDown
Left = SDL-{sdl_index}/DPadLeft
Triangle = SDL-{sdl_index}/FaceNorth
Circle = SDL-{sdl_index}/FaceEast
Cross = SDL-{sdl_index}/FaceSouth
Square = SDL-{sdl_index}/FaceWest
Select = SDL-{sdl_index}/Back
Start = SDL-{sdl_index}/Start
L1 = SDL-{sdl_index}/LeftShoulder
L2 = SDL-{sdl_index}/+LeftTrigger
R1 = SDL-{sdl_index}/RightShoulder
R2 = SDL-{sdl_index}/+RightTrigger
L3 = SDL-{sdl_index}/LeftStick
R3 = SDL-{sdl_index}/RightStick
LUp = SDL-{sdl_index}/-LeftY
LRight = SDL-{sdl_index}/+LeftX
LDown = SDL-{sdl_index}/+LeftY
LLeft = SDL-{sdl_index}/-LeftX
RUp = SDL-{sdl_index}/-RightY
RRight = SDL-{sdl_index}/+RightX
RDown = SDL-{sdl_index}/+RightY
RLeft = SDL-{sdl_index}/-RightX
SmallMotor = SDL-{sdl_index}/SmallMotor
LargeMotor = SDL-{sdl_index}/LargeMotor
"""

text = ini_path.read_text(encoding="utf-8")
prefix, rest = text.split("[Pad]\n", 1)
_, suffix = rest.split("[Achievements]\n", 1)
block = "[Pad]\n"
block += f"MultitapPort1 = {'true' if len(players) > 2 else 'false'}\n"
block += "MultitapPort2 = false\n\n"
for player in players:
    block += pad_section(int(player["player"]), int(player.get("sdl2_index", int(player["player"]) - 1))) + "\n"
ini_path.write_text(prefix + block + "[Achievements]\n" + suffix, encoding="utf-8")
PY
      log_event "runtime" "prepared PCSX2 managed config at $pcsx2_ini"
    }

    prepare_xemu_runtime() {
      xemu_data_dir="${cfg.dataRoot}/xdg/share/xemu/xemu"
      xemu_bios_dir="${cfg.biosRoot}/xbox"
      mkdir -p "$xemu_data_dir"
      if [ ! -f "$xemu_data_dir/eeprom.bin" ]; then
        dd if=/dev/zero of="$xemu_data_dir/eeprom.bin" bs=256 count=1 status=none
      fi
      ${pkgs.python3}/bin/python3 - \
        "$xemu_data_dir/xemu.toml" \
        "$resolved_controllers" \
        "$xemu_bios_dir" \
        "$xemu_data_dir/eeprom.bin" \
        "''${EMULATION_XEMU_PREFERRED_GPU_NAME:-}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
resolved_path = Path(sys.argv[2])
bios_dir = Path(sys.argv[3])
eeprom_path = Path(sys.argv[4])
preferred_gpu = sys.argv[5]
try:
    players = json.loads(resolved_path.read_text(encoding="utf-8")).get("players", [])
except (OSError, json.JSONDecodeError):
    players = []
players = sorted([p for p in players if 1 <= int(p.get("player", 0)) <= 4], key=lambda p: int(p["player"]))

def q(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

lines = [
    "[general]",
    "show_welcome = false",
    "skip_boot_anim = true",
    "",
    "[audio]",
    "use_dsp = false",
    "hrtf = false",
    "",
    "[display]",
    "renderer = 'VULKAN'",
    "",
    "[display.vulkan]",
    f"preferred_physical_device = {q(preferred_gpu)}",
    "",
    "[display.window]",
    "fullscreen_on_startup = true",
    "vsync = false",
    "",
    "[display.quality]",
    "surface_scale = 3",
    "",
    "[display.ui]",
    "show_menubar = false",
    "fit = 'scale'",
    "",
    "[sys.files]",
    f"bootrom_path = {q(bios_dir / 'mcpx_1.0.bin')}",
    f"flashrom_path = {q(bios_dir / 'Complex_4627.bin')}",
    f"eeprom_path = {q(eeprom_path)}",
    f"hdd_path = {q(bios_dir / 'xbox_hdd.qcow2')}",
    "",
    "[input.bindings]",
]
for port in range(1, 5):
    match = next((p for p in players if int(p["player"]) == port), None)
    if match is not None:
        value = match.get("xemu_guid") or match.get("identity") or ""
        lines.append(f"port{port} = {q(value)}")
config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
      log_event "runtime" "prepared Xemu managed config from resolved controller order"
    }

    resolve_first_m3u_entry() {
      playlist="$1"
      playlist_dir="$(dirname "$playlist")"
      entry="$(${pkgs.gawk}/bin/awk '
        /^[[:space:]]*($|#)/ { next }
        {
          sub(/^[[:space:]]+/, "")
          sub(/[[:space:]]+$/, "")
          print
          exit
        }
      ' "$playlist")"
      if [ -z "$entry" ]; then
        log_event "error" "empty m3u playlist: $playlist"
        echo "Empty m3u playlist: $playlist" >&2
        exit 64
      fi
      case "$entry" in
        /*) resolved="$entry" ;;
        *) resolved="$playlist_dir/$entry" ;;
      esac
      if [ ! -f "$resolved" ]; then
        log_event "error" "m3u first disc missing: $playlist -> $resolved"
        echo "M3U first disc does not exist: $resolved" >&2
        exit 66
      fi
      printf '%s\n' "$resolved"
    }

    cmd=()
    run_cwd=""
    hotkey_profile="global"
    hotkey_snapshot_tag=""
    hotkey_hmp_socket=""
    hotkey_runtime_dir=""
    parse_gzdoom_launcher() {
      launcher="$1"
      launcher_line="$(grep -v -E '^[[:space:]]*(#|$)' "$launcher" | head -n 1 || true)"
      if [ -z "$launcher_line" ]; then
        log_event "error" "empty GZDoom launcher"
        echo "Empty GZDoom launcher: $launcher" >&2
        exit 64
      fi
      set +e
      mapfile -d "" -t gzdoom_args < <(
        GZDOOM_LAUNCHER_LINE="$launcher_line" ${pkgs.python3}/bin/python3 - <<'PY'
import os
import shlex
import sys

try:
    args = shlex.split(os.environ["GZDOOM_LAUNCHER_LINE"], comments=False, posix=True)
except ValueError as exc:
    print(f"Invalid .gzdoom launcher syntax: {exc}", file=sys.stderr)
    sys.exit(64)

for arg in args:
    sys.stdout.buffer.write(arg.encode("utf-8") + b"\0")
PY
      )
      parse_rc="$?"
      set -e
      if [ "$parse_rc" -ne 0 ]; then
        exit "$parse_rc"
      fi
      if [ "''${#gzdoom_args[@]}" -eq 0 ]; then
        log_event "error" "GZDoom launcher produced no arguments"
        echo "GZDoom launcher produced no arguments: $launcher" >&2
        exit 64
      fi
    }

    case "$emulator_id" in
      retroarch-*)
        core_file="$(core_file_for "$emulator_id")"
        core_path="${packages.retroarchPackage}/lib/retroarch/cores/$core_file"
        if [ ! -e "$core_path" ]; then
          core_path="$(find "${packages.retroarchPackage}/lib/retroarch/cores" -maxdepth 1 -name "$(core_pattern_for "$emulator_id")" -print -quit || true)"
        fi
        if [ -z "''${core_path:-}" ] || [ ! -e "$core_path" ]; then
          log_event "error" "missing RetroArch core for $emulator_id"
          echo "Missing RetroArch core for $emulator_id" >&2
          exit 66
        fi
        cmd=(retroarch --config "${cfg.configRoot}/retroarch/retroarch.cfg")
        retroachievements_config="${cfg.configRoot}/retroarch/retroachievements.cfg"
        if [ -r "$retroachievements_config" ]; then
          cmd+=(--appendconfig "$retroachievements_config")
        fi
        retroarch_order_config="/run/ghostship-emulation/controllers/retroarch-order.cfg"
        if jq -e '.players | length > 0' "$resolved_controllers" >/dev/null 2>&1; then
          analog_dpad_mode="$(retroarch_analog_dpad_mode)"
          : >"$retroarch_order_config.tmp"
          jq -c '.players[] | select(.player >= 1 and .player <= 4)' "$resolved_controllers" | while read -r controller; do
            player="$(jq -r '.player' <<<"$controller")"
            sdl2_index="$(jq -r '.sdl2_index' <<<"$controller")"
            {
              printf 'input_player%s_joypad_index = "%s"\n' "$player" "$sdl2_index"
              printf 'input_player%s_analog_dpad_mode = "%s"\n' "$player" "$analog_dpad_mode"
              retroarch_face_overrides "$player"
            } >>"$retroarch_order_config.tmp"
          done
          mv "$retroarch_order_config.tmp" "$retroarch_order_config"
          cmd+=(--appendconfig "$retroarch_order_config")
        fi
        cmd+=(-L "$core_path" "$rom_path")
        ;;
      dolphin)
        hotkey_profile="dolphin"
        export EMULATION_DOLPHIN_HOTKEY_FALLBACK=1
        prepare_dolphin_runtime
        cmd=(
          dolphin-emu
          -b
          -e "$rom_path"
          -C Main.Analytics.PermissionAsked=True
          -C Main.Analytics.Enabled=False
          -C Main.Interface.ConfirmStop=False
          -C Main.Interface.UsePanicHandlers=False
          -C Main.Interface.OnScreenDisplayMessages=True
          -C Main.General.HotkeysRequireFocus=False
        )
        ;;
      cemu) cmd=(cemu -f -g "$rom_path") ;;
      xemu)
        prepare_xemu_runtime
        cmd=(
          xemu
          -full-screen
          -config_path "${cfg.dataRoot}/xdg/share/xemu/xemu/xemu.toml"
          -dvd_path "$rom_path"
        )
        ;;
      xemu-hotkeys)
        prepare_xemu_runtime
        runtime_root="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        if [ ! -d "$runtime_root" ]; then
          runtime_root="${cfg.dataRoot}/tmp"
        fi
        hotkey_runtime_dir="$runtime_root/ghostship-emulation/xemu-$$"
        install -d -m 0700 "$hotkey_runtime_dir"
        hotkey_hmp_socket="$hotkey_runtime_dir/hmp.sock"
        hotkey_profile="xemu"
        hotkey_snapshot_tag="esde-slot1"
        rm -f "$hotkey_hmp_socket"
        cmd=(
          xemu
          -full-screen
          -config_path "${cfg.dataRoot}/xdg/share/xemu/xemu/xemu.toml"
          -dvd_path "$rom_path"
          -monitor "unix:$hotkey_hmp_socket,server=on,wait=off"
        )
        ;;
      ryubing)
        prepare_ryubing_runtime
        hotkey_profile="ryubing"
        cmd=(ryujinx "$rom_path")
        ;;
      azahar)
        azahar_bin="$(first_command azahar azahar-qt)"
        cmd=("$azahar_bin" "$rom_path")
        ;;
      lime3ds) cmd=(lime3ds "$rom_path") ;;
      pcsx2)
        prepare_pcsx2_runtime
        if [ "''${PCSX2_CONFIG_ONLY:-0}" = "1" ]; then
          log_event "runtime" "prepared PCSX2 managed config only"
          exit 0
        fi
        pcsx2_bin="$(first_command pcsx2-qt pcsx2)"
        pcsx2_rom_path="$rom_path"
        case "$rom_path" in
          *.m3u|*.M3U)
            pcsx2_rom_path="$(resolve_first_m3u_entry "$rom_path")"
            log_event "runtime" "resolved PCSX2 m3u playlist to first disc: $pcsx2_rom_path"
            ;;
        esac
        cmd=("$pcsx2_bin" -batch -fullscreen -- "$pcsx2_rom_path")
        ;;
      ppsspp)
        ppsspp_bin="$(first_command PPSSPPSDL ppsspp ppsspp-sdl)"
        cmd=("$ppsspp_bin" "$rom_path")
        ;;
      supermodel) cmd=(supermodel "$rom_path" -res="$output_width","$output_height" -fullscreen -force-feedback) ;;
      gzdoom)
        run_cwd="$(dirname "$rom_path")"
        gzdoom_controls="${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg"
        gzdoom_common_args=()
        if [ -r "$gzdoom_controls" ]; then
          gzdoom_common_args=(-exec "$gzdoom_controls")
        fi
        case "$rom_path" in
          *.gzdoom|*.GZDOOM)
            parse_gzdoom_launcher "$rom_path"
            cmd=(gzdoom "''${gzdoom_common_args[@]}" "''${gzdoom_args[@]}")
            ;;
          *) cmd=(gzdoom "''${gzdoom_common_args[@]}" -iwad "$rom_path") ;;
        esac
        ;;
      pico8|pico8-hotkeys)
        prepare_pico8_runtime
        if [ "$emulator_id" = "pico8-hotkeys" ]; then
          hotkey_profile="pico8"
        fi
        cmd=(
          pico8
          -home "${cfg.configRoot}/emulators/pico8"
          -root_path "${cfg.romRoot}/Fantasy - PICO-8 (2015)"
          -desktop "${cfg.dataRoot}/screenshots/pico8"
          -screenshot_scale 3
          -gif_scale 3
          -gif_len 8
          -joystick 0
          -run "$rom_path"
        )
        ;;
      teknoparrot) cmd=(teknoparrot-free "$rom_path") ;;
      *)
        log_event "error" "unknown emulator"
        echo "Unknown emulator: $emulator_id" >&2
        exit 64
        ;;
    esac

    log_event "launch" "$profile_json"
    run_cmd=("''${cmd[@]}")
    if [ "''${EMULATION_MANGOHUD:-0}" = "1" ]; then
      run_cmd=(mangohud "''${run_cmd[@]}")
    fi
    use_gamescope=0
    if [ "''${EMULATION_DISABLE_GAMESCOPE:-0}" != "1" ]; then
      if [ "''${EMULATION_FORCE_GAMESCOPE:-0}" = "1" ] || { [ -z "''${WAYLAND_DISPLAY:-}" ] && [ -z "''${DISPLAY:-}" ]; }; then
        use_gamescope=1
      fi
    fi
    if [ "$use_gamescope" = "1" ]; then
      if [ -z "''${WAYLAND_DISPLAY:-}" ] && [ -z "''${DISPLAY:-}" ]; then
        mapfile -t gamescope_args < <(
          jq -r '
            ["--backend","drm","-f","-W",(.output_width|tostring),"-H",(.output_height|tostring),"-w",(.render_width|tostring),"-h",(.render_height|tostring),"-S",.scale_mode,"--force-windows-fullscreen"]
            + (if .connector != "" then ["--prefer-output",.connector] else [] end)
            + (if .preferred_vk_device != "" then ["--prefer-vk-device",.preferred_vk_device] else [] end)
            | .[]
          ' <<<"$profile_json"
        )
      else
        mapfile -t gamescope_args < <(jq -r '.gamescope_args[]' <<<"$profile_json")
      fi
      if [ "$emulator_id" = "pico8" ] || [ "$emulator_id" = "pico8-hotkeys" ]; then
        gamescope_args+=("--xwayland-count" "1")
      fi
      run_cmd=(gamescope "''${gamescope_args[@]}" -- "''${run_cmd[@]}")
    fi
    if command -v gamemoderun >/dev/null 2>&1; then
      run_cmd=(gamemoderun "''${run_cmd[@]}")
    fi
    if [ -n "$run_cwd" ]; then
      cd "$run_cwd"
    fi
    setsid "''${run_cmd[@]}" &
    emulator_pid="$!"
    hotkey_pid=""
    if [ -n "$hotkey_profile" ]; then
      ${lib.getExe standaloneHotkeyBroker} \
        --profile "$hotkey_profile" \
        --pid "$emulator_pid" \
        --hmp-socket "$hotkey_hmp_socket" \
        --snapshot-tag "$hotkey_snapshot_tag" \
        --system "$system_id" \
        --emulator "$emulator_id" \
        --log "$log_file" &
      hotkey_pid="$!"
    fi

    process_group_alive() {
      kill -0 -- "-$1" >/dev/null 2>&1
    }

    terminate_process_group() {
      pid="$1"
      reason="$2"
      process_group_alive "$pid" || return 0
      log_event "exit-request" "$reason sent SIGTERM to emulator process group"
      kill -TERM -- "-$pid" >/dev/null 2>&1 || true
      for _ in $(seq 1 50); do
        process_group_alive "$pid" || return 0
        sleep 0.1
      done
      process_group_alive "$pid" || return 0
      log_event "force-kill" "$reason still alive after 5 seconds; sent SIGKILL to emulator process group"
      kill -KILL -- "-$pid" >/dev/null 2>&1 || true
    }

    cleanup() {
      if [ -n "$hotkey_pid" ]; then
        kill "$hotkey_pid" >/dev/null 2>&1 || true
      fi
      terminate_process_group "$emulator_pid" "run-emulator cleanup"
      if [ -n "$hotkey_runtime_dir" ]; then
        rm -rf "$hotkey_runtime_dir"
      fi
    }
    trap cleanup INT TERM HUP
    set +e
    wait "$emulator_pid"
    status="$?"
    set -e
    if [ -n "$hotkey_pid" ]; then
      kill "$hotkey_pid" >/dev/null 2>&1 || true
      wait "$hotkey_pid" >/dev/null 2>&1 || true
    fi
    if [ -n "$hotkey_runtime_dir" ]; then
      rm -rf "$hotkey_runtime_dir"
    fi
    exit "$status"
  '';

  romCoverageCheck = pkgs.writeShellScriptBin "rom-coverage-check" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:$PATH
    source_root="''${1:-/mnt/z/Library/ROMs/roms}"
    [ -d "$source_root" ] || source_root="${cfg.romRoot}"
    missing=0
    printf '%s\n' "Checking ROM folder coverage under $source_root"
    while read -r folder; do
      if [ -e "$source_root/$folder" ]; then
        printf 'ok %s\n' "$folder"
      else
        printf 'missing %s\n' "$folder"
        missing=1
      fi
    done < <(printf '%s' '${emu.allSystemsJson}' | jq -r '.[].folder')
    exit "$missing"
  '';

  updateRyubingCanary = pkgs.writeShellScriptBin "update-ryubing-canary" ''
        set -euo pipefail
        export PATH=${
          lib.makeBinPath [
            pkgs.coreutils
            pkgs.curl
            pkgs.gnugrep
            pkgs.gnused
            pkgs.nix
          ]
        }:$PATH

        repo="''${1:-$PWD}"
        pin_file="$repo/modules/emulation/ryubing-canary-pin.nix"
        latest_endpoint="https://update.ryujinx.app/latest/canary"

        if [ ! -f "$pin_file" ]; then
          echo "Missing pin file: $pin_file" >&2
          exit 66
        fi

        final_url="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$latest_endpoint")"
        version="$(printf '%s\n' "$final_url" | sed -n 's#.*/\([0-9][0-9.]*\)$#\1#p')"
        if [ -z "$version" ]; then
          echo "Could not resolve Ryubing Canary version from $latest_endpoint -> $final_url" >&2
          exit 65
        fi

        current="$(sed -n 's/.*version = "\(.*\)";.*/\1/p' "$pin_file")"
        if [ "''${2:-}" != "--force" ] && [ "$current" = "$version" ]; then
          echo "Ryubing Canary is already pinned to latest version $version"
          exit 0
        fi

        url="https://git.ryujinx.app/Ryubing/Canary/releases/download/$version/ryujinx-canary-$version-linux_x64.tar.gz"
        hash_base32="$(nix-prefetch-url "$url")"
        hash_sri="$(nix hash convert --hash-algo sha256 --to sri "$hash_base32")"

        tmp="$(mktemp)"
        cat >"$tmp" <<EOF
    {
      version = "$version";
      url = "$url";
      hash = "$hash_sri";
    }
EOF
        mv "$tmp" "$pin_file"
        echo "Pinned Ryubing Canary $version"
        echo "$hash_sri"
  '';

  syncEmulatorConfigs = pkgs.writeShellScriptBin "sync-emulator-configs" ''
        set -euo pipefail
        export PATH=${emu.scriptPath}:$PATH
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
          "${cfg.configRoot}/display" \
          "${cfg.configRoot}/emulators" \
          "${cfg.configRoot}/emulators/azahar" \
          "${cfg.configRoot}/emulators/dolphin" \
          "${cfg.configRoot}/emulators/cemu" \
          "${cfg.configRoot}/emulators/pcsx2" \
          "${cfg.configRoot}/emulators/ppsspp" \
          "${cfg.configRoot}/emulators/xemu" \
          "${cfg.configRoot}/emulators/ryubing" \
          "${cfg.configRoot}/emulators/supermodel" \
          "${cfg.configRoot}/emulators/gzdoom" \
          "${cfg.configRoot}/emulators/pico8" \
          "${cfg.configRoot}/emulators/teknoparrot" \
          "${cfg.configRoot}/teknoparrot"
        if [ -d "${cfg.configRoot}/teknoparrot/TeknoParrot" ]; then
          chgrp ${cfg.group} "${cfg.configRoot}/teknoparrot/TeknoParrot"
          chmod 0775 "${cfg.configRoot}/teknoparrot/TeknoParrot"
        fi
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "${cfg.configRoot}/teknoparrot/TeknoParrot/UserProfiles"
        install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${displayPolicy} "${cfg.configRoot}/display/policy.json"
        ps2_rom_dir="${cfg.romRoot}/Sony - PlayStation 2 (2000)"
        ps2_disc_dir="$ps2_rom_dir/.discs"
        ps2_soulcalibur_top_disc="$ps2_rom_dir/Soulcalibur III (USA).chd"
        ps2_soulcalibur_disc="$ps2_disc_dir/Soulcalibur III (USA).chd"
        ps2_soulcalibur_playlist="$ps2_rom_dir/Soulcalibur III (USA).m3u"
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$ps2_disc_dir"
        if [ -f "$ps2_soulcalibur_top_disc" ] && [ ! -e "$ps2_soulcalibur_disc" ]; then
          mv "$ps2_soulcalibur_top_disc" "$ps2_soulcalibur_disc"
        fi
        if [ -f "$ps2_soulcalibur_disc" ]; then
          chown ${cfg.user}:${cfg.group} "$ps2_soulcalibur_disc"
          chmod 0644 "$ps2_soulcalibur_disc"
          printf '%s\n' ".discs/Soulcalibur III (USA).chd" >"$ps2_soulcalibur_playlist.tmp"
          chown ${cfg.user}:${cfg.group} "$ps2_soulcalibur_playlist.tmp"
          chmod 0644 "$ps2_soulcalibur_playlist.tmp"
          mv "$ps2_soulcalibur_playlist.tmp" "$ps2_soulcalibur_playlist"
        fi
        runuser -u ${cfg.user} -- env PCSX2_CONFIG_ONLY=1 ${runEmulator}/bin/run-emulator ps2 pcsx2 "$ps2_soulcalibur_disc"
        xemu_data_dir="${cfg.dataRoot}/xdg/share/xemu/xemu"
        xemu_bios_dir="${cfg.biosRoot}/xbox"
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$xemu_data_dir"
        if [ ! -f "$xemu_data_dir/eeprom.bin" ]; then
          dd if=/dev/zero of="$xemu_data_dir/eeprom.bin" bs=256 count=1 status=none
          chown ${cfg.user}:${cfg.group} "$xemu_data_dir/eeprom.bin"
          chmod 0644 "$xemu_data_dir/eeprom.bin"
        fi
        printf '%s\n' \
          '[general]' \
          'show_welcome = false' \
          'skip_boot_anim = true' \
          "" \
          '[audio]' \
          'use_dsp = false' \
          'hrtf = false' \
          "" \
          '[display]' \
          "renderer = 'VULKAN'" \
          "" \
          '[display.vulkan]' \
          'preferred_physical_device = ""' \
          "" \
          '[display.window]' \
          'fullscreen_on_startup = true' \
          'vsync = false' \
          "" \
          '[display.quality]' \
          'surface_scale = 3' \
          "" \
          '[display.ui]' \
          'show_menubar = false' \
          "fit = 'scale'" \
          "" \
          '[sys.files]' \
          "bootrom_path = '$xemu_bios_dir/mcpx_1.0.bin'" \
          "flashrom_path = '$xemu_bios_dir/Complex_4627.bin'" \
          "eeprom_path = '$xemu_data_dir/eeprom.bin'" \
          "hdd_path = '$xemu_bios_dir/xbox_hdd.qcow2'" \
          >"$xemu_data_dir/xemu.toml"
        chown ${cfg.user}:${cfg.group} "$xemu_data_dir/xemu.toml"
        chmod 0644 "$xemu_data_dir/xemu.toml"
        ${lib.optionalString (packages.supermodelPackage != null) ''
          supermodel_config_dir="${cfg.dataRoot}/xdg/config/supermodel/Config"
          supermodel_assets_dir="${cfg.dataRoot}/xdg/share/supermodel/Assets"
          install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$supermodel_config_dir"
          install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$supermodel_assets_dir"
          install -m 0644 -o ${cfg.user} -g ${cfg.group} \
            ${packages.supermodelPackage}/share/supermodel/Config/Games.xml \
            "$supermodel_config_dir/Games.xml"
          ${pkgs.python3}/bin/python3 - "$supermodel_config_dir/Games.xml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
start = text.index('<game name="swtrilgy">')
end = text.index('</game>', start) + len('</game>')
block = text[start:end]
drive_board = """      <!-- Force feedback controller prg -->
      <region name="driveboard_program" stride="1" chunk_size="1" required="false">
        <file offset="0" name="epr-21119.ic8" crc32="0x65082B14" />
      </region>
"""
if drive_board not in block:
    raise SystemExit("swtrilgy driveboard_program block not found")
path.write_text(text[:start] + block.replace(drive_board, "") + text[end:])
PY
          install -m 0644 -o ${cfg.user} -g ${cfg.group} \
            ${packages.supermodelPackage}/share/supermodel/Config/Music.xml \
            "$supermodel_config_dir/Music.xml"
          install -m 0644 -o ${cfg.user} -g ${cfg.group} \
            ${packages.supermodelPackage}/share/supermodel/Assets/* \
            "$supermodel_assets_dir/"
        ''}
        dolphin_config_dir="${cfg.dataRoot}/xdg/config/dolphin-emu"
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$dolphin_config_dir"
        cat >"$dolphin_config_dir/Dolphin.ini" <<'EOF'
[Analytics]
PermissionAsked = True
Enabled = False
[Core]
CPUThread = True
SkipIPL = True
GFXBackend = Vulkan
SIDevice0 = 6
SIDevice1 = 6
SIDevice2 = 6
SIDevice3 = 6
WiimoteContinuousScanning = True
WiimoteEnableSpeaker = False
[Display]
Fullscreen = True
RenderWindowWidth = 1920
RenderWindowHeight = 1080
RenderWindowAutoSize = False
[Interface]
ConfirmStop = False
UsePanicHandlers = False
OnScreenDisplayMessages = True
[General]
HotkeysRequireFocus = False
[DSP]
DSPThread = True
Backend = Cubeb
Volume = 100
EOF
        cat >"$dolphin_config_dir/GFX.ini" <<'EOF'
[Settings]
BackendMultithreading = True
InternalResolution = 3
AspectRatio = 0
ShaderCompilationMode = 2
ShaderCache = True
WaitForShadersBeforeStarting = False
BorderlessFullscreen = True
[Hardware]
VSync = False
[Enhancements]
MaxAnisotropy = 4
EOF
        cat >"$dolphin_config_dir/Hotkeys.ini" <<'EOF'
[Hotkeys]
Device = XInput2/0/Virtual core pointer
General/Toggle Pause = F10
General/Reset = @(Ctrl+R)
General/Take Screenshot = F9
Emulation Speed/Disable Emulation Speed Limit = Tab
Load State/Load State Slot 1 = F1
Save State/Save State Slot 1 = @(Shift+F1)
EOF
        : >"$dolphin_config_dir/GCPadNew.ini"
        for slot in 1 2 3 4; do
          index=$((slot - 1))
          cat >>"$dolphin_config_dir/GCPadNew.ini" <<EOF
[GCPad$slot]
Device = SDL/$index/Nintendo Switch Pro Controller
Buttons/A = \`Button B\`
Buttons/B = \`Button Y\`
Buttons/X = \`Button A\`
Buttons/Y = \`Button X\`
Buttons/Z = \`Trigger R\`
Buttons/Start = \`Start\`
Main Stick/Up = \`Axis 1-\`
Main Stick/Down = \`Axis 1+\`
Main Stick/Left = \`Axis 0-\`
Main Stick/Right = \`Axis 0+\`
Main Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
C-Stick/Up = \`Axis 3-\`
C-Stick/Down = \`Axis 3+\`
C-Stick/Left = \`Axis 2-\`
C-Stick/Right = \`Axis 2+\`
C-Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
Triggers/L = \`Shoulder L\`
Triggers/R = \`Shoulder R\`
D-Pad/Up = \`Hat 0 N\`
D-Pad/Down = \`Hat 0 S\`
D-Pad/Left = \`Hat 0 W\`
D-Pad/Right = \`Hat 0 E\`
EOF
        done
        : >"$dolphin_config_dir/WiimoteNew.ini"
        for slot in 1 2 3 4; do
          index=$((slot - 1))
          cat >>"$dolphin_config_dir/WiimoteNew.ini" <<EOF
[Wiimote$slot]
Source = 1
Device = SDL/$index/Nintendo Switch Pro Controller
Buttons/A = \`Button B\`
Buttons/B = \`Trigger L\`
Buttons/1 = \`Button A\`
Buttons/2 = \`Button X\`
Buttons/- = \`Back\`
Buttons/+ = \`Start\`
Buttons/Home = \`Misc 1\`
D-Pad/Up = \`Hat 0 N\`
D-Pad/Down = \`Hat 0 S\`
D-Pad/Left = \`Hat 0 W\`
D-Pad/Right = \`Hat 0 E\`
IR/Up = \`Axis 3-\`
IR/Down = \`Axis 3+\`
IR/Left = \`Axis 2-\`
IR/Right = \`Axis 2+\`
Shake/X = \`Shoulder R\`
Shake/Y = \`Shoulder R\`
Shake/Z = \`Shoulder R\`
Extension = Nunchuk
Nunchuk/Buttons/C = \`Back\`
Nunchuk/Buttons/Z = \`Guide\`
Nunchuk/Stick/Up = \`Axis 1-\`
Nunchuk/Stick/Down = \`Axis 1+\`
Nunchuk/Stick/Left = \`Axis 0-\`
Nunchuk/Stick/Right = \`Axis 0+\`
Nunchuk/Stick/Calibration = 100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42
EOF
        done
        cat >>"$dolphin_config_dir/WiimoteNew.ini" <<'EOF'
[BalanceBoard]
Source = 0
EOF
        cat >"$dolphin_config_dir/Logger.ini" <<'EOF'
[Options]
Verbosity = 1
WriteToFile = False
WriteToConsole = False
EOF
        chown -R ${cfg.user}:${cfg.group} "$dolphin_config_dir"
        find "$dolphin_config_dir" -type f -exec chmod 0644 {} +
        sed 's/^    //' >"${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg" <<'EOF'
    // Boomer Switch Pro controller defaults. Managed by Nix.
    use_joystick true
    freelook true
    lookstrafe false

    // GZDoom regenerates generic Joy*/POV1* defaults before this cfg runs.
    // Fixed Joy indices based on observed +1 shift (R2=9, R1=7, L2=8, L1=6).
    // B -> Joy1 -> jump
    // A -> Joy2 -> use/open
    // X -> Joy3 -> crouch
    // Y -> Joy4 -> reload
    // L1 -> Joy5/6 -> User 1 (Mod special)
    // R1 -> Joy7 -> Alt-Fire (ADS)
    // L2 -> Joy8 -> User 2 (Zoom/Grenade)
    // R2 -> Joy9 -> Primary Fire
    // Select -> Joy10 -> Automap
    // Start -> Joy11 -> Menu
    // L3 -> Joy12 -> Speed/Run toggle
    // R3 -> Joy13 -> Quick turn / User 4
    // R-Trigger -> Joy14 -> Primary Fire (User request)
    bind Joy1 +jump
    bind Joy2 +use
    bind Joy3 crouch
    bind Joy4 +reload
    bind Joy5 +user1
    bind Joy6 +user1
    bind Joy7 +altattack
    bind Joy8 +user2
    bind Joy9 +attack
    bind Joy10 togglemap
    bind Joy11 menu_main
    bind Joy12 +speed
    bind Joy13 +user4
    bind Joy14 +attack
    bind Axis3Plus +user2
    bind Axis4Plus +user2
    bind Axis4Minus +user2
    bind Axis5Plus +attack
    bind Axis5Minus +attack
    bind Axis6Plus +attack
    bind Axis6Minus +attack
    // D-pad left/right -> previous/next weapon; up/down -> inventory prev/use.
    bind POV1Left weapprev
    bind POV1Right weapnext
    bind POV1Up invprev
    bind POV1Down invuse

    // Alias fallbacks for standard SDL naming
    bind pad_a +use
    bind pad_b +jump
    bind pad_x crouch
    bind pad_y +reload
    bind rtrigger +attack
    bind ltrigger +user2
    bind rshoulder +altattack
    bind lshoulder +user1
    bind pad_start menu_main
    bind pad_back togglemap
    bind lthumb +speed
    bind rthumb +user4
    bind dpadleft weapprev
    bind dpadright weapnext
    bind dpadup invprev
    bind dpaddown invuse

    mapbind Joy10 togglemap
    mapbind pad_back togglemap
    mapbind pad_y am_togglefollow
    mapbind pad_a am_setmark
    mapbind pad_b am_clearmarks
    mapbind POV1Right +am_panright
    mapbind POV1Left +am_panleft
    mapbind POV1Up +am_panup
    mapbind POV1Down +am_pandown
    mapbind POV1Down +am_pandown
    mapbind POV1Up +am_panup
    mapbind POV1Down +am_pandown
    mapbind dpadright +am_panright
    mapbind dpadleft +am_panleft
    mapbind dpadup +am_panup
    mapbind dpaddown +am_pandown
    mapbind lshoulder +am_zoomout
    mapbind rshoulder +am_zoomin
EOF
        chown ${cfg.user}:${cfg.group} "${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg"
        chmod 0644 "${cfg.configRoot}/emulators/gzdoom/boomer-controls.cfg"
        user_home="$(awk -F: -v user=${lib.escapeShellArg cfg.user} '$1 == user { print $6; exit }' /etc/passwd)"
        if [ -n "$user_home" ]; then
          gzdoom_ini="$user_home/.config/gzdoom/gzdoom.ini"
          install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$gzdoom_ini")"
          ${pkgs.python3}/bin/python3 - "$gzdoom_ini" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if path.exists() else []

# Keep only the stick calibration in the INI. The first Boomer control layout
# deliberately lets GZDoom regenerate its own binding defaults, then layers
# boomer-controls.cfg over them at launch.
axis_settings = {
    "Axis0deadzone": "0.20",
    "Axis0map": "3",
    "Axis1deadzone": "0.20",
    "Axis1map": "2",
    "Axis2deadzone": "0.20",
    "Axis2map": "0",
    "Axis3deadzone": "0.20",
    "Axis3map": "1",
    "Axis3scale": "0.25",
    "Axis4deadzone": "0.25",
    "Axis4map": "-1",
    "Axis5deadzone": "0.25",
    "Axis5map": "-1",
    "Axis6deadzone": "0.10",
    "Axis6map": "-1",
    "Axis7deadzone": "0.10",
    "Axis7map": "-1",
}

def drop_section(input_lines, section):
    out = []
    in_section = False
    for line in input_lines:
        stripped = line.strip()
        starts_section = stripped.startswith("[") and stripped.endswith("]")
        if starts_section:
            in_section = stripped == f"[{section}]"
        if not in_section:
            out.append(line)
    return out

def upsert_section(input_lines, section, settings):
    out = []
    in_section = False
    found_section = False
    seen = set()

    def append_missing():
        for key, value in settings.items():
            if key not in seen and value is not None:
                out.append(f"{key}={value}\n")
                seen.add(key)

    for line in input_lines:
        stripped = line.strip()
        starts_section = stripped.startswith("[") and stripped.endswith("]")
        if starts_section:
            if in_section:
                append_missing()
            in_section = stripped == f"[{section}]"
            if in_section:
                found_section = True
                seen = set()
            out.append(line)
            continue
        if in_section and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in settings:
                if settings[key] is not None:
                    out.append(f"{key}={settings[key]}\n")
                seen.add(key)
                continue
        out.append(line)

    if in_section:
        append_missing()
    if not found_section:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        if out and out[-1].strip():
            out.append("\n")
        out.append(f"[{section}]\n")
        for key, value in settings.items():
            if value is not None:
                out.append(f"{key}={value}\n")
    return out

for index in range(4):
    lines = upsert_section(lines, f"Joy:JS:{index}", axis_settings)
for section in ("Doom.Bindings", "Doom.DoubleBindings", "Doom.AutomapBindings"):
    lines = drop_section(lines, section)

path.write_text("".join(lines), encoding="utf-8")
PY
          chown ${cfg.user}:${cfg.group} "$gzdoom_ini"
          chmod 0644 "$gzdoom_ini"
        fi
        for dir in azahar dolphin cemu pcsx2 ppsspp xemu ryubing supermodel gzdoom pico8 teknoparrot; do
          readme="${cfg.configRoot}/emulators/$dir/README.txt"
          if [ ! -e "$readme" ]; then
            printf '%s\n' "Runtime config scaffold for $dir. Durable defaults are managed by Nix; hardware tuning can start here." >"$readme"
            chown ${cfg.user}:${cfg.group} "$readme"
            chmod 0644 "$readme"
          fi
        done
        cat >"${cfg.configRoot}/emulators/scaling-policy.json" <<'EOF'
    {
      "gamescope_fsr": false,
      "aspect_policy": "preserve",
      "standalone_defaults": {
        "azahar": "use emulator internal resolution scaling",
        "cemu": "use Vulkan and graphics packs/internal resolution",
        "dolphin": "use standalone internal resolution",
        "pcsx2": "use Vulkan hardware renderer and internal resolution",
        "ppsspp": "use Vulkan and PPSSPP rendering resolution",
        "ryubing": "use Vulkan, docked mode, 16x AF, and emulator-native scaling/filtering",
        "supermodel": "launch with -res=<output_width>,<output_height>",
        "xemu": "use xemu internal resolution scale",
        "xemu-hotkeys": "use xemu internal resolution scale",
        "pico8": "use PICO-8 native 4:3 output through Gamescope",
        "pico8-hotkeys": "use PICO-8 native 4:3 output through Gamescope"
      }
    }
EOF
        chown ${cfg.user}:${cfg.group} "${cfg.configRoot}/emulators/scaling-policy.json"
        chmod 0644 "${cfg.configRoot}/emulators/scaling-policy.json"
        cat >"${cfg.configRoot}/emulators/controller-policy.json" <<'EOF'
    {
      "primary_controller": "Nintendo Switch Pro Controller",
      "vendor_product": "057e:2009",
      "button_policy": "physical_switch_labels",
      "shared_layout": {
        "face_south": "physical B / lower face / primary or confirm where applicable",
        "face_east": "physical A / right face / secondary or cancel where applicable",
        "face_north": "physical X / upper face",
        "face_west": "physical Y / left face",
        "digital_movement": "RetroArch launch config sets left analog to D-pad only for systems whose original controller has no left analog stick; analog-capable systems keep analog sticks as analog input, and standalone SDL emulators keep their native mappings",
        "player_slots": "map every stable declarative player slot exposed by the emulator"
      },
      "global_sdl_hints": {
        "SDL_GAMECONTROLLER_USE_BUTTON_LABELS": "1"
      },
      "hotkey_policy": {
        "scheme": "Per-emulator hotkeys with a shared per-launch Minus + Plus double-press exit broker; expanded standalone hotkey brokers are opt-in per emulator",
        "retroarch_menu": "RetroArch only: Minus + X opens the quick menu",
        "console_home": "Square/Capture opens emulated console Home only where a stable native binding is generated; currently Dolphin Wii Remote Home",
        "modifier": "Minus",
        "retroarch_save_state": "RetroArch only: Minus + R1",
        "retroarch_load_state": "RetroArch only: Minus + L1",
        "retroarch_reset": "RetroArch only: Minus + B",
        "retroarch_fps": "RetroArch only: Minus + Y",
        "retroarch_screenshot": "RetroArch only: Minus + A",
        "retroarch_fast_forward": "RetroArch only: Minus + R2",
        "normal_exit": "Minus + Plus twice exits the active run-emulator process group",
        "dolphin_gamecube_hotkeys": "Dolphin GameCube uses the raw standalone hotkey broker, matching the Xemu approach: Minus + B resets, Minus + L1 loads state slot 1, Minus + R1 saves state slot 1, Minus + A screenshots, Minus + R2 toggles fast mode, and Minus + X quick actions plus Minus + Y debug monitor are intentionally unbound because Dolphin has no equivalent normal runtime actions",
        "pcsx2_hotkeys": "PCSX2 uses native PCSX2 hotkey bindings: Minus + X opens the pause menu, Minus + B resets the VM, Minus + L1 loads state slot 1, Minus + R1 saves state slot 1, Minus + A saves a screenshot, Minus + Y toggles the OSD/FPS overlay, and Minus + R2 holds turbo/fast-forward",
        "xemu_hotkeys": "Default Xbox launch: Minus + X opens quick actions, B resets, L1 loads esde-slot1, R1 saves esde-slot1, A screenshots, Y toggles the debug monitor, and Minus + R2 is unbound",
        "pico8_hotkeys": "Default PICO-8 launch: Minus + X opens pause/menu, B resets the cart, A saves a screenshot, Y saves the current GIF buffer, and Minus + R2 is unbound",
        "ryubing_hotkeys": "Default Switch launch: Minus + X sends F4 for Ryubing UI, Minus + A sends F8 for screenshot, Square/Capture sends F5 for pause, and Minus + Plus twice exits",
        "gzdoom": "GZDoom button map: Start/+ opens the menu, Minus toggles the automap, and Square/Capture is intentionally unbound",
        "pico8": "fallback plain PICO-8 launch: Start/+ opens pause/menu; PICO-8 uses an explicit managed -home config directory"
      },
      "managed_defaults": {
        "retroarch": "Switch Pro and 8BitDo autoconfig map physical B/A/Y/X to RetroPad B/A/Y/X, then launch-time RetroArch append config pins connected players, sets analog-to-D-pad for digital-only systems, and applies the Dreamcast physical face override; RetroArch uses the managed base retroarch.cfg, generated RetroAchievements append config, XDG global.slangp, and XDG per-core .opt files; PC Engine-family cores default to 6-button pads for all five players; RetroArch Minus hotkeys keep the same physical buttons for menu, save/load, reset, FPS, screenshot, and fast-forward; Square/Capture has no stable Home binding",
        "dolphin": "GameCube ports 1-4 and Wii slots 1-4 use resolved SDL slots; GameCube maps A/B/X/Y by physical position for Boomer's Switch Pro controller, enables only connected launch slots, launches fullscreen without analytics, panic, or stop-confirm prompts, and uses the raw hotkey broker for reset, save/load slot 1, screenshot, and fast mode; Square/Capture opens Wii Remote Home only where Dolphin exposes it; D-pad stays on physical D-pad and analog movement stays on analog sticks",
        "ppsspp": "inherits SDL Switch label hints from run-emulator; Minus + Plus twice exits through the per-launch broker",
        "pcsx2": "launches through standalone PCSX2 with managed no-wizard config, launcher-side m3u first-disc resolution, Vulkan 3x internal resolution, native PCSX2 hotkey chords for pause menu/reset/save/load/screenshot/OSD/turbo, port 1 multitap for players 1-4, token-backed RetroAchievements when RETROACHIEVEMENTS_TOKEN is projected, and Minus + Plus twice exits through the per-launch broker; Square/Capture is intentionally unbound until a stable Boomer SDL guide binding is proven",
        "azahar": "inherits SDL Switch label hints from run-emulator; Minus + Plus twice exits through the per-launch broker",
        "cemu": "inherits SDL Switch label hints from run-emulator; Minus + Plus twice exits through the per-launch broker",
        "xemu": "fallback plain Xemu launch uses resolved controller ports with physical Xbox face layout through SDL and per-launch Minus + Plus twice exit",
        "xemu-hotkeys": "default Xbox launch uses resolved controller ports with physical Xbox face layout through SDL plus the standalone broker for quick actions, save/load, reset, screenshots, debug monitor, and pause",
        "ryubing": "inherits SDL Switch label hints from run-emulator, installs the newest local firmware archive into Ryubing's registered firmware store, uses managed Vulkan/docked/fullscreen Ryubing settings, and maps Minus + X to F4, Minus + A to F8, Square/Capture to F5, and Minus + Plus twice to exit through the per-launch broker",
        "supermodel": "inherits SDL Switch label hints from run-emulator; Minus + Plus twice exits through the per-launch broker",
        "teknoparrot": "inherits SDL Switch label hints through the Wine launch path where supported; Minus + Plus twice exits through the per-launch broker",
        "gzdoom": "run-emulator executes the managed GZDoom control cfg: A is Use/Confirm, B is Jump/Back, X crouches, Y reloads, D-pad left/right select previous/next weapon, D-pad up/down select/use inventory, L1/R1 are User 1/User 2, L2/R2 are alt fire/fire, Minus toggles automap, Start/+ opens menu, and right stick controls look with 25% vertical sensitivity",
        "pico8": "fallback plain PICO-8 launch using an explicit managed -home directory; D-pad or left stick moves, physical B is O/primary, physical A is X/secondary, and Start/+ opens pause/menu",
        "pico8-hotkeys": "default PICO-8 launch with the standalone broker for screenshot, GIF save, cart reset, and pause/menu chords"
      },
      "known_gaps": {
        "motion": "hid_nintendo exposes a separate IMU device; emulator support varies",
        "rumble": "hid_nintendo exposes force feedback through ff-memless; emulator support varies"
      }
    }
EOF
        chown ${cfg.user}:${cfg.group} "${cfg.configRoot}/emulators/controller-policy.json"
        chmod 0644 "${cfg.configRoot}/emulators/controller-policy.json"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit
        displayProfile
        controllerResolve
        romCoverageCheck
        runEmulator
        standaloneHotkeyBroker
        standaloneHotkeyBrokerSmokeTest
        switchProButtonProbe
        syncEmulatorConfigs
        teknoparrotFree
        updateRyubingCanary
        ;
    };
    ghostship.emulation.internal.setupScripts = [ syncEmulatorConfigs ];
  };
}
