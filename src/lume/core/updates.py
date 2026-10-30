"""Verificação e download de atualizações a partir das releases do GitHub.

Nada aqui acontece sem consentimento: a interface só chama estas funções se a
pessoa autorizou a verificação, e só baixa/instala depois de um clique.
O único dado enviado é a requisição HTTP pública à API de releases.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lume import __version__

REPO = "geandreac/screen-brightness"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CHECK_INTERVAL_S = 24 * 60 * 60
ASSET_PATTERN = re.compile(r"^Lume-Setup-.*\.exe$", re.IGNORECASE)


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    page_url: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int = 0
    sha256: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """``v1.2.10`` → (1, 2, 10). Sufixos (``-beta``) são ignorados."""
    match = re.match(r"^\D*(\d+(?:\.\d+)*)", text.strip())
    if not match:
        raise UpdateError(f"Versão inválida: {text!r}")
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except UpdateError:
        return False


def parse_release(data: dict) -> Release:
    if not isinstance(data, dict) or "tag_name" not in data:
        raise UpdateError("Resposta inesperada do GitHub.")
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("A release mais recente não é uma versão estável.")
    asset = next(
        (a for a in data.get("assets") or [] if ASSET_PATTERN.match(str(a.get("name", "")))), None
    )
    digest = (asset or {}).get("digest") or ""
    sha256 = digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else None
    return Release(
        version=str(data["tag_name"]).lstrip("vV"),
        notes=str(data.get("body") or "").strip(),
        page_url=str(data.get("html_url") or RELEASES_PAGE),
        asset_name=asset.get("name") if asset else None,
        asset_url=asset.get("browser_download_url") if asset else None,
        asset_size=int(asset.get("size") or 0) if asset else 0,
        sha256=sha256,
    )


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": f"Lume/{__version__} (+{RELEASES_PAGE})"}
    )


def fetch_latest(timeout: float = 10, opener=urllib.request.urlopen) -> Release:
    try:
        with opener(_request(LATEST_URL, "application/vnd.github+json"), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except UpdateError:
        raise
    except Exception as exc:  # noqa: BLE001 — rede, TLS, JSON: tudo vira mensagem compreensível
        code = getattr(exc, "code", None)
        if code == 404:
            raise UpdateError("Ainda não há nenhuma versão publicada.") from exc
        raise UpdateError(f"Não foi possível consultar o GitHub ({exc}).") from exc
    return parse_release(data)


def download(
    release: Release,
    dest_dir: Path,
    progress: Callable[[int, int], None] = lambda done, total: None,
    *,
    timeout: float = 30,
    opener=urllib.request.urlopen,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """Baixa o instalador e confere tamanho e SHA‑256 antes de devolvê-lo."""
    if not release.asset_url or not release.asset_name:
        raise UpdateError("Esta versão não tem instalador para Windows anexado.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / Path(release.asset_name).name
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    done = 0
    try:
        with opener(_request(release.asset_url, "application/octet-stream"), timeout=timeout) as resp:
            total = release.asset_size or int(resp.headers.get("Content-Length") or 0)
            with open(partial, "wb") as out:
                while chunk := resp.read(256 * 1024):
                    if cancelled():
                        raise UpdateError("Download cancelado.")
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done, total)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Falha no download ({exc}).") from exc
    if release.asset_size and done != release.asset_size:
        partial.unlink(missing_ok=True)
        raise UpdateError("O arquivo baixado está incompleto. Tente novamente.")
    if release.sha256 and digest.hexdigest() != release.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError("O arquivo baixado não confere com a assinatura SHA‑256 da release. Nada foi instalado.")
    partial.replace(target)
    return target


def installer_command(installer: Path) -> list[str]:
    """Instalação silenciosa (com barra de progresso) que reabre o Lume ao terminar.

    Uma pequena espera garante que o Lume já fechou (e restaurou as cores)
    antes de o instalador verificar se ele ainda está aberto.
    """
    args = f'"{installer}" /SILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH'
    return ["cmd.exe", "/c", f"ping -n 3 127.0.0.1 >nul & start \"\" {args}"]
