"""Bootstrap stdlib logging (stderr): human-readable timestamps and logger names."""

from __future__ import annotations

import logging
import sys


def normalize_log_level(name: str) -> int:
    upper = name.strip().upper()
    mapping = logging.getLevelNamesMapping()
    if upper in mapping:
        return mapping[upper]
    return logging.INFO


def configure_logging(
    *,
    verbose: bool = False,
    log_level_env: str = "INFO",
) -> None:
    """Configure root logging. Diagnostics go to stderr."""

    root_level = logging.DEBUG if verbose else normalize_log_level(log_level_env)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(root_level)
    root.addHandler(handler)
