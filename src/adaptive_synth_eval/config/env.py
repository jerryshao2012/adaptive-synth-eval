from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ENV_PATTERN = re.compile(r"\$\{([^}]+)}")


def load_project_env(*, override: bool = False, anchor: Path | None = None) -> None:
    """Load environment variables from .env files.

    Resolution order:
    1) `ASE_ENV_FILE` when set.
    2) `.env` discovered from an optional anchor path.
    """

    env_file = os.getenv("ASE_ENV_FILE")
    if env_file:
        candidate = Path(env_file).expanduser()
        if candidate.exists():
            load_dotenv(candidate, override=override)
            return

    if anchor is not None:
        for parent in [anchor, *anchor.parents]:
            candidate = parent / ".env"
            if candidate.exists():
                load_dotenv(candidate, override=override)
                return


def resolve_env_placeholders(obj: Any) -> Any:
    """Resolve `${VAR}` and `${VAR:-default}` recursively in nested structures.

    `${VAR}` resolves to an empty string when the variable is missing.
    """

    if isinstance(obj, str):
        return _ENV_PATTERN.sub(_replace_placeholder, obj)
    if isinstance(obj, dict):
        return {k: resolve_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_placeholders(v) for v in obj]
    return obj


def _replace_placeholder(match: re.Match[str]) -> str:
    expr = match.group(1)
    if ":-" in expr:
        name, default = expr.split(":-", 1)
        return os.getenv(name, default)
    return os.getenv(expr, "")
