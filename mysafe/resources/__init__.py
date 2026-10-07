"""Bundled images (app icon)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def resource_path(name: str) -> Path:
    """Filesystem path of a bundled resource file."""
    return Path(str(resources.files(__name__).joinpath(name)))
