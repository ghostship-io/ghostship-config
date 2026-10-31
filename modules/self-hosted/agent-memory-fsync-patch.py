"""Apply the Basic Memory v1.0.0 durability patch by exact source replacement.

A unified diff for this change carries blank context lines, which the repository
whitespace check rejects. These replacements assert the pinned source text and
fail the image build if a version bump moves it.

Run inside the image: python agent-memory-fsync-patch.py
"""

import os
from pathlib import Path

TARGET = Path(os.environ.get("AGENT_MEMORY_FILE_UTILS", "/app/src/basic_memory/file_utils.py"))


def replace(source: str, old: str, new: str, *, count: int = 1) -> str:
    if source.count(old) != count:
        raise SystemExit(f"expected {count} occurrence(s) of the pinned source text, found {source.count(old)}")
    return source.replace(old, new)


source = TARGET.read_text()

source = replace(source, "import asyncio\nimport hashlib", "import asyncio\nimport errno\nimport hashlib")

helper = '''def _fsync_directory(directory: Path) -> None:
    """Persist a directory entry after an atomic rename."""
    try:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as error:
        if error.errno in (errno.EINVAL, errno.ENOTSUP):
            return
        raise
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


'''

anchor = "async def write_file_atomic(path: FilePath, content: str) -> None:"
source = replace(source, anchor, helper + anchor)

source = replace(
    source,
    '''        async with aiofiles.open(temp_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
''',
    '''        async with aiofiles.open(temp_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
            await f.flush()
            os.fsync(f.fileno())
''',
)

source = replace(
    source,
    '''        async with aiofiles.open(temp_path, mode="wb") as f:
            await f.write(content)
''',
    '''        async with aiofiles.open(temp_path, mode="wb") as f:
            await f.write(content)
            await f.flush()
            os.fsync(f.fileno())
''',
)

source = replace(
    source,
    '''        temp_path.replace(path_obj)
        logger.debug("Wrote file atomically"''',
    '''        temp_path.replace(path_obj)
        _fsync_directory(path_obj.parent)
        # The parent directory must exist for the temp file, so its own entry in
        # the grandparent is the one a newly created folder has not persisted
        # yet. Fsync it unconditionally; a redundant fsync is cheaper than
        # losing the first note written into active/ or archive/.
        _fsync_directory(path_obj.parent.parent)
        logger.debug("Wrote file atomically"''',
    count=2,
)

if source.count("_fsync_directory(path_obj.parent.parent)") != 2:
    raise SystemExit("durability patch did not land in both atomic writers")

TARGET.write_text(source)
print("agent-memory durability patch applied")
