"""Input actions for a virtual pointer and keyboard on one region of a Wayland screen.

Shared by app-session (one app per headless screen) and stage-control (one
Chrome window per output of a browser stage). Coordinates are pixels of the
captured region (its frame); `origin` places that region in the compositor's
output layout and `extent` is the layout's size, which absolute pointer
motion is relative to. A caller whose layout changes underneath passes `move`
instead: it places the pointer at a region point itself, one event at a time. Keys and text go through wtype; typed text is passed on
stdin, never in process arguments. Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
import time

KEY_ALIASES = {"enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape", "tab": "Tab",
               "backspace": "BackSpace", "delete": "Delete", "del": "Delete", "space": "space",
               "home": "Home", "end": "End", "pageup": "Page_Up", "page_up": "Page_Up",
               "pagedown": "Page_Down", "page_down": "Page_Down", "insert": "Insert",
               "up": "Up", "down": "Down", "left": "Left", "right": "Right",
               "arrowup": "Up", "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right"}
MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "option": "alt",
             "super": "logo", "meta": "logo", "cmd": "logo", "win": "logo", "logo": "logo"}


class InputError(Exception):
    """The keyboard tool failed (the caller reports it as unavailable)."""


def key_args(combo: str) -> list[str]:
    """wtype arguments for a key or combo such as Return or ctrl+shift+s."""
    parts = combo.replace(" ", "").split("+")
    if not all(parts) or len(combo) > 64 or parts[-1].lower() in MODIFIERS:
        raise ValueError("key needs a name such as Return or ctrl+s")
    mods, key = parts[:-1], parts[-1]
    args = []
    for mod in mods:
        if mod.lower() not in MODIFIERS:
            raise ValueError(f"unknown modifier {mod!r}")
        args += ["-M", MODIFIERS[mod.lower()]]
    key = KEY_ALIASES.get(key.lower(), key)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}|[!-~]", key):
        raise ValueError(f"unknown key {key!r}")
    args += ["-k", key] if len(key) > 1 else [key]
    for mod in reversed(mods):
        args += ["-m", MODIFIERS[mod.lower()]]
    return args


class Actions:
    """Run Pelorus-style actions (left_click, type, key, scroll, ...) on one region."""

    def __init__(self, devices, env: dict, width: int, height: int,
                 origin: tuple[int, int] = (0, 0), extent: tuple[int, int] | None = None, move=None):
        self.input, self.env = devices, env
        self.move = move
        self.width, self.height = width, height
        self.origin = origin
        self.extent = extent or (width, height)
        self.pointer = (width // 2, height // 2)

    def _point(self, value, default=None) -> tuple[int, int]:
        if value is None:
            if default is None:
                raise ValueError("coordinate is required")
            return default
        if not (isinstance(value, (list, tuple)) and len(value) == 2):
            raise ValueError("coordinate must be [x, y]")
        x, y = float(value[0]), float(value[1])
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"coordinate outside the {self.width}x{self.height} screen")
        return int(x), int(y)

    def _move(self, point: tuple[int, int]) -> None:
        if self.move:
            self.move(*point)
        else:
            self.input.move(self.origin[0] + point[0], self.origin[1] + point[1], *self.extent)
        self.pointer = point

    def _click(self, button: str, count: int) -> None:
        for _ in range(count):
            self.input.button(button, True)
            time.sleep(0.02)
            self.input.button(button, False)
            time.sleep(0.06)

    def _wtype(self, args: list[str], text: str | None = None) -> None:
        proc = subprocess.run(["wtype", *args], input=text.encode() if text is not None else None,
                              capture_output=True, timeout=30, env=self.env)
        if proc.returncode:
            raise InputError("keyboard input failed")

    def act(self, action: dict) -> dict:
        kind = action.get("action")
        coordinate = action.get("coordinate")
        if kind in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
            self._move(self._point(coordinate, self.pointer))
            button = {"right_click": "right", "middle_click": "middle"}.get(kind, "left")
            self._click(button, {"double_click": 2, "triple_click": 3}.get(kind, 1))
        elif kind == "mouse_move":
            self._move(self._point(coordinate))
        elif kind in ("left_mouse_down", "left_mouse_up"):
            if coordinate is not None:
                self._move(self._point(coordinate))
            self.input.button("left", kind == "left_mouse_down")
        elif kind == "button":  # viewer pointer events: any button, down or up
            if coordinate is not None:
                self._move(self._point(coordinate))
            button = action.get("button", "left")
            if button not in ("left", "right", "middle") or action.get("state") not in ("down", "up"):
                raise ValueError("button needs button left|right|middle and state down|up")
            self.input.button(button, action["state"] == "down")
        elif kind == "left_click_drag":
            start, end = self._point(action.get("start_coordinate")), self._point(action.get("end_coordinate"))
            self._move(start)
            self.input.button("left", True)
            for step in range(1, 11):
                time.sleep(0.02)
                self._move((start[0] + (end[0] - start[0]) * step // 10, start[1] + (end[1] - start[1]) * step // 10))
            self.input.button("left", False)
        elif kind == "scroll":
            if coordinate is not None:
                self._move(self._point(coordinate))
            if "dx" in action or "dy" in action:  # viewer wheel, in notches
                dx = max(min(float(action.get("dx", 0)), 50.0), -50.0)
                dy = max(min(float(action.get("dy", 0)), 50.0), -50.0)
            else:
                amount = min(max(int(action.get("scroll_amount", 3)), 1), 50)
                direction = action.get("scroll_direction", "down")
                vectors = {"down": (0, amount), "up": (0, -amount), "right": (amount, 0), "left": (-amount, 0)}
                if direction not in vectors:
                    raise ValueError("scroll_direction must be up, down, left or right")
                dx, dy = vectors[direction]
            self.input.scroll(dx, dy)
        elif kind == "key":
            self._wtype(key_args(str(action.get("text", ""))))
        elif kind == "type":
            text = action.get("text")
            if not isinstance(text, str) or not text or len(text) > 4000:
                raise ValueError("type needs text (1-4000 characters)")
            self._wtype(["-d", "8", "-"], text)  # stdin: typed text may be private, never argv
        elif kind == "wait":
            time.sleep(min(max(float(action.get("duration", 1)), 0), 10))
        elif kind == "cursor_position":
            return {"action": kind, "position": list(self.pointer)}
        else:
            raise ValueError(f"unknown action {kind!r}")
        return {"action": kind, "ok": True}
