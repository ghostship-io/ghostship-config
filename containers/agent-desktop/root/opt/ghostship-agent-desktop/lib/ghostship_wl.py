"""Minimal pure-Python Wayland client for the desktop's virtual input devices.

Binds wl_seat plus the wlroots virtual pointer (zwlr_virtual_pointer_manager_v1)
and virtual keyboard (zwp_virtual_keyboard_manager_v1) on one compositor, so a
headless output gets the mouse and keyboard a real screen has. Stdlib only:
the desktop's system python3 has no Wayland bindings.
"""
from __future__ import annotations

import os
import socket
import struct
import threading
import time

KEYMAP = b"""xkb_keymap {
  xkb_keycodes { include "evdev+aliases(qwerty)" };
  xkb_types { include "complete" };
  xkb_compat { include "complete" };
  xkb_symbols { include "pc+us+inet(evdev)" };
};
\0"""

# Linux input event codes (linux/input-event-codes.h).
BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112}


class Wayland:
    def __init__(self, path: str):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.next_id = 2
        self.buffer = b""

    def new_id(self) -> int:
        value, self.next_id = self.next_id, self.next_id + 1
        return value

    @staticmethod
    def string(value: str) -> bytes:
        data = value.encode() + b"\0"
        return struct.pack("<I", len(data)) + data + b"\0" * (-len(data) % 4)

    def send(self, obj: int, opcode: int, payload: bytes = b"", fds: list[int] | None = None) -> None:
        message = struct.pack("<II", obj, ((8 + len(payload)) << 16) | opcode) + payload
        if fds:
            socket.send_fds(self.sock, [message], fds)
        else:
            self.sock.sendall(message)

    def events(self):
        while True:
            while len(self.buffer) >= 8:
                obj, word = struct.unpack_from("<II", self.buffer)
                size = word >> 16
                if len(self.buffer) < size:
                    break
                body, self.buffer = self.buffer[8:size], self.buffer[size:]
                yield obj, word & 0xFFFF, body
            data = self.sock.recv(65536)
            if not data:
                return
            self.buffer += data


def socket_path(display: str | None = None) -> str:
    display = display or os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    return display if display.startswith("/") else os.path.join(os.environ["XDG_RUNTIME_DIR"], display)


class VirtualInput:
    """One virtual pointer and one US-layout virtual keyboard on a compositor's seat."""

    WANTED = ("wl_seat", "zwlr_virtual_pointer_manager_v1", "zwp_virtual_keyboard_manager_v1")

    def __init__(self, path: str):
        self.wl = Wayland(path)
        self.lock = threading.Lock()
        registry = self.wl.new_id()
        self.wl.send(1, 1, struct.pack("<I", registry))      # wl_display.get_registry
        callback = self.wl.new_id()
        self.wl.send(1, 0, struct.pack("<I", callback))      # wl_display.sync
        globals_: dict[str, tuple[int, int]] = {}
        for obj, opcode, body in self.wl.events():
            if obj == registry and opcode == 0:              # wl_registry.global
                name, length = struct.unpack_from("<II", body)
                interface = body[8:8 + length - 1].decode()
                (version,) = struct.unpack_from("<I", body, 8 + length + (-length % 4))
                globals_.setdefault(interface, (name, version))
            elif obj == callback:                            # wl_callback.done
                break
        missing = [name for name in self.WANTED if name not in globals_]
        if missing:
            raise OSError(f"compositor lacks {', '.join(missing)}")
        bound = {}
        for interface in self.WANTED:
            name, version = globals_[interface]
            bound[interface] = self.wl.new_id()
            self.wl.send(registry, 0, struct.pack("<I", name) + self.wl.string(interface)
                         + struct.pack("<II", min(version, 1 if interface != "wl_seat" else 5), bound[interface]))
        seat = bound["wl_seat"]
        self.pointer = self.wl.new_id()
        self.wl.send(bound["zwlr_virtual_pointer_manager_v1"], 0, struct.pack("<II", seat, self.pointer))
        self.keyboard = self.wl.new_id()
        self.wl.send(bound["zwp_virtual_keyboard_manager_v1"], 0, struct.pack("<II", seat, self.keyboard))
        keymap = os.memfd_create("ghostship-keymap")
        os.write(keymap, KEYMAP)
        self.wl.send(self.keyboard, 0, struct.pack("<II", 1, len(KEYMAP)), [keymap])  # keymap(XKB_V1, fd, size)
        os.close(keymap)

    def hold(self) -> None:
        """Keep the devices until the compositor goes away (drains events)."""
        for _ in self.wl.events():
            pass

    @staticmethod
    def _now() -> int:
        return int(time.monotonic() * 1000) & 0xFFFFFFFF

    def move(self, x: float, y: float, width: int, height: int) -> None:
        """Absolute pointer motion to output pixel (x, y)."""
        x = min(max(int(round(x)), 0), width - 1)
        y = min(max(int(round(y)), 0), height - 1)
        with self.lock:
            self.wl.send(self.pointer, 1, struct.pack("<IIIII", self._now(), x, y, width, height))
            self.wl.send(self.pointer, 4)                       # frame

    def button(self, button: str, pressed: bool) -> None:
        with self.lock:
            self.wl.send(self.pointer, 2, struct.pack("<III", self._now(), BUTTONS[button], 1 if pressed else 0))
            self.wl.send(self.pointer, 4)

    def scroll(self, dx: float, dy: float) -> None:
        """Wheel scroll in notches (positive dy scrolls down, positive dx right)."""
        with self.lock:
            now = self._now()
            self.wl.send(self.pointer, 5, struct.pack("<I", 0))  # axis_source(wheel)
            for axis, notches in ((0, dy), (1, dx)):
                if notches:
                    value = int(round(notches * 15 * 256))      # wl_fixed, 15 units per notch
                    self.wl.send(self.pointer, 7, struct.pack("<IIii", now, axis, value, int(round(notches))))
            self.wl.send(self.pointer, 4)
