"""Erros que a interface sabe explicar para a pessoa usuária."""


class BackendError(Exception):
    """Falha ao ler ou aplicar um ajuste.

    ``message`` explica o que aconteceu; ``hint`` sugere uma ação útil.
    """

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} {self.hint}".strip()


class UnsupportedError(BackendError):
    """O recurso não existe nesta combinação de sistema, conexão e monitor."""


class PermissionDeniedError(BackendError):
    """O sistema exige uma permissão que o programa não tem."""
