"""Build-time proof that the durability patch fsyncs a brand-new folder.

Upstream creates the target folder with mkdir(parents=True) before the atomic
write, so the writer must fsync the file, its parent and the parent's parent;
otherwise the folder's own entry in the grandparent can be lost on power loss
while file_write_status still reaches "synced". The test writes the first note
into a new `active/` directory and asserts three fsync calls.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest import mock

from basic_memory.file_utils import write_file_atomic_bytes


async def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        target = Path(root) / "active" / "note.md"
        target.parent.mkdir()  # a brand-new folder, as ensure_directory creates
        calls: list[int] = []
        real_fsync = os.fsync

        def record(descriptor: int) -> None:
            calls.append(descriptor)
            return real_fsync(descriptor)

        with mock.patch("basic_memory.file_utils.os.fsync", side_effect=record):
            await write_file_atomic_bytes(target, b"body\n")

        assert target.read_text() == "body\n", target.read_text()
        assert len(calls) >= 3, f"expected file+parent+grandparent fsync, got {len(calls)}"
        print(f"agent-memory fsync test ok: {len(calls)} fsync calls")


asyncio.run(main())
