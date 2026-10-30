"""Perfis e preferências salvos em JSON.

Nada além de valores de ajuste é gravado: nenhum dado pessoal ou de saúde.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from lume.core.models import Adjustments

SCHEMA_VERSION = 1
MAX_NAME = 40


class ProfileError(ValueError):
    pass


@dataclass
class Preferences:
    transitions: bool = True
    apply_immediately: bool = True
    ui_scale: int = 100  # %
    close_to_tray: bool = True
    minimize_to_tray: bool = True
    tray_notice_shown: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Preferences":
        prefs = cls()
        for name in ("transitions", "apply_immediately", "close_to_tray", "minimize_to_tray", "tray_notice_shown"):
            if isinstance(data.get(name), bool):
                setattr(prefs, name, data[name])
        scale = data.get("ui_scale")
        if isinstance(scale, int) and 80 <= scale <= 200:
            prefs.ui_scale = scale
        return prefs


@dataclass
class Store:
    path: Path
    profiles: dict[str, Adjustments] = field(default_factory=dict)
    preferences: Preferences = field(default_factory=Preferences)
    load_warning: str = ""

    @classmethod
    def load(cls, directory: Path) -> "Store":
        path = directory / "settings.json"
        store = cls(path)
        if not path.exists():
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("formato inesperado")
        except (OSError, ValueError) as exc:
            backup = path.with_suffix(".json.bak")
            try:
                os.replace(path, backup)
                where = f" Uma cópia foi guardada em {backup}."
            except OSError:
                where = ""
            store.load_warning = f"O arquivo de configurações estava ilegível ({exc}) e foi reiniciado.{where}"
            return store
        for name, raw in (data.get("profiles") or {}).items():
            if isinstance(raw, dict) and isinstance(name, str) and name.strip():
                store.profiles[name.strip()[:MAX_NAME]] = Adjustments.from_dict(raw)
        store.preferences = Preferences.from_dict(data.get("preferences") or {})
        return store

    def save(self) -> None:
        data = {
            "version": SCHEMA_VERSION,
            "profiles": {name: adj.to_dict() for name, adj in self.profiles.items()},
            "preferences": vars(self.preferences),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # escrita atômica: nunca deixa o arquivo pela metade

    @staticmethod
    def clean_name(name: str) -> str:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ProfileError("Dê um nome ao perfil.")
        if len(cleaned) > MAX_NAME:
            raise ProfileError(f"Use no máximo {MAX_NAME} caracteres.")
        return cleaned

    def save_profile(self, name: str, adjustments: Adjustments) -> str:
        name = self.clean_name(name)
        self.profiles[name] = adjustments
        self.save()
        return name

    def delete_profile(self, name: str) -> None:
        if self.profiles.pop(name, None) is not None:
            self.save()
