"""Garante uma única instância: abrir o app de novo só traz a janela à frente.

Importante para um app de bandeja — duas instâncias brigariam pela curva de cor.
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return f"lume-{''.join(c for c in user if c.isalnum())}"


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, name: str | None = None):
        super().__init__()
        self.name = name or server_name()
        self.server: QLocalServer | None = None

    def notify_running(self) -> bool:
        """True se outra instância respondeu (e foi avisada para aparecer)."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(300):
            return False
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)  # limpa socket órfão após uma queda
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        return self.server.listen(self.name)

    def _on_connection(self) -> None:
        conn = self.server.nextPendingConnection()
        if conn:
            conn.disconnected.connect(conn.deleteLater)
        self.activated.emit()
