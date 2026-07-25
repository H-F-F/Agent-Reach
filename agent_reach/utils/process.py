"""Subprocess helpers for consistent cross-platform text handling."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping

UTF8_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
}


def resolve_command(command: str) -> str:
    """Return the exact executable path when PATH resolution can find it.

    Windows npm tools are commonly ``.CMD`` shims. Passing the resolved path
    to ``subprocess`` works consistently across Windows, macOS, and Linux.
    The original name is retained so callers still get the usual
    ``FileNotFoundError`` when a command disappears after a prior check.
    """
    return shutil.which(command) or command


def utf8_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that forces Python child processes into UTF-8 mode."""
    env = dict(base or os.environ)
    env.update(UTF8_ENV)
    return env


def mcporter_utf8_env_args() -> list[str]:
    """Return mcporter --env arguments for UTF-8 Python stdio servers."""
    args = []
    for key, value in UTF8_ENV.items():
        args.extend(["--env", f"{key}={value}"])
    return args
