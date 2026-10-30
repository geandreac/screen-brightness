"""Pasta de configuração por usuário, seguindo a convenção de cada sistema."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from lume import APP_ID


def config_dir() -> Path:
    override = os.environ.get("LUME_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Lume"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Lume"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_ID
