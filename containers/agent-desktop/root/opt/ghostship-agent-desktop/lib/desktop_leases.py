"""Bounded public lease records shared by the reaper, viewer and stage."""
import json
import math
import os
import re
import stat

MARKER = re.compile(r"[0-9a-f]{32}")
TARGET = re.compile(r"[A-Za-z0-9]{1,64}")


def records(directory, identity, schema=2):
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    result = []
    for name in names:
        if not name.endswith(".json") or not MARKER.fullmatch(name[:-5]):
            continue
        try:
            fd = os.open(os.path.join(directory, name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    continue
                raw = os.read(fd, 16385)
            finally:
                os.close(fd)
            row = json.loads(raw) if len(raw) <= 16384 else None
            if (schema == 1 and isinstance(row, dict) and row.get("schema") == 1
                    and row.get("run_id") == name[:-5] and row.get("identity") == identity):
                result.append(row)
                continue
            if (schema == 2 and isinstance(row, dict) and row.get("schema") == 2 and row.get("run_id") == name[:-5]
                    and row.get("identity") == identity
                    and type(row.get("chrome_window_id")) is int and row["chrome_window_id"] > 0
                    and isinstance(row.get("target_id"), str) and TARGET.fullmatch(row["target_id"])
                    and isinstance(row.get("target_ids", []), list) and len(row.get("target_ids", [])) <= 256
                    and all(isinstance(t, str) and TARGET.fullmatch(t) for t in row.get("target_ids", []))
                    and type(row.get("expires_at")) in (int, float)
                    and math.isfinite(row["expires_at"]) and row["expires_at"] > 0):
                result.append(row)
        except (OSError, ValueError, UnicodeError):
            continue
    return result


def bound_records(rows, windows):
    """A numeric window id alone never grants authority: its target must still match."""
    bound = []
    for row in rows:
        target = next((t for t in [row["target_id"], *row.get("target_ids", [])]
                       if windows.get(t) == row["chrome_window_id"]), None)
        if target:
            bound.append(dict(row, target_id=target))
    return bound
