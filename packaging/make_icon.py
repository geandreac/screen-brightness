"""Gera assets/lume.ico e assets/lume.png a partir do ícone desenhado no app."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import struct  # noqa: E402

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lume.ui.widgets import app_icon  # noqa: E402

app = QApplication([])
icon = app_icon()
out = ROOT / "assets"
out.mkdir(exist_ok=True)
icon.pixmap(QSize(256, 256)).save(str(out / "lume.png"))


def png_bytes(size: int) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    icon.pixmap(QSize(size, size)).toImage().save(buf, "PNG")
    return bytes(data)


# ICO com vários tamanhos (PNG embutido): nítido na bandeja (16–32 px) e no Explorer.
sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
images = [png_bytes(s) for s in sizes]
header = struct.pack("<HHH", 0, 1, len(sizes))
offset = len(header) + 16 * len(sizes)
entries = b""
for size, data in zip(sizes, images):
    dim = 0 if size >= 256 else size
    entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
(out / "lume.ico").write_bytes(header + entries + b"".join(images))
print("Ícones gerados em", out)
