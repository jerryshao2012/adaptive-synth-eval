"""Regression tests for Windows-compatible CLI imports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_imports_without_posix_fcntl() -> None:
    """Windows must be able to load the CLI before executing any command."""
    repository_root = Path(__file__).resolve().parents[2]
    source_root = repository_root / "src"
    script = r'''
import builtins
import subprocess  # Load it before exposing the Windows-only msvcrt shim.
import tempfile
import types
from pathlib import Path

real_import = builtins.__import__
msvcrt = types.ModuleType("msvcrt")
msvcrt.LK_LOCK = 1
msvcrt.LK_UNLCK = 0
msvcrt.locking = lambda _fd, _mode, _length: None

def windows_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "fcntl":
        raise ModuleNotFoundError("No module named 'fcntl'")
    if name == "msvcrt":
        return msvcrt
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = windows_import
from adaptive_synth_eval.file_lock import file_lock

with tempfile.TemporaryDirectory() as directory:
    with file_lock(Path(directory) / "windows.lock"):
        pass

import adaptive_synth_eval.cli
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (str(source_root), environment.get("PYTHONPATH", ""))
        if value
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
