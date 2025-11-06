"""Configuration helpers for the kabupilot backend."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DB_FILENAME = "kabupilot.db"


def get_database_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Return the filesystem path to the SQLite database.

    Parameters
    ----------
    path:
        Optional override. When ``None`` (the default), the value is resolved
        from the ``KABUPILOT_DB_PATH`` environment variable. If the environment
        variable is not defined the database is stored in the current working
        directory under ``kabupilot.db``.
    """

    if path is not None:
        return Path(path).expanduser().resolve()

    env_value = os.environ.get("KABUPILOT_DB_PATH")
    if env_value:
        return Path(env_value).expanduser().resolve()

    return Path.cwd() / DEFAULT_DB_FILENAME
