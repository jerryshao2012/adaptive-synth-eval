"""Cross-platform process and thread file locking."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None
    import msvcrt as _msvcrt
else:
    _msvcrt = None


_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _acquire(handle: BinaryIO, *, shared: bool) -> None:
    if _fcntl is not None:
        operation = _fcntl.LOCK_SH if shared else _fcntl.LOCK_EX
        _fcntl.flock(handle.fileno(), operation)
        return

    # msvcrt locks a byte range from the current position. Ensure byte zero
    # exists, then always use an exclusive lock because it has no portable
    # shared-lock equivalent.
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    _msvcrt.locking(handle.fileno(), _msvcrt.LK_LOCK, 1)


def _release(handle: BinaryIO) -> None:
    if _fcntl is not None:
        _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
        return
    handle.seek(0)
    _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)


@contextmanager
def file_lock(path: str | Path, *, shared: bool = False) -> Iterator[None]:
    """Lock ``path`` across threads and processes for the context duration."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(lock_path):
        with lock_path.open("a+b") as handle:
            _acquire(handle, shared=shared)
            try:
                yield
            finally:
                _release(handle)
