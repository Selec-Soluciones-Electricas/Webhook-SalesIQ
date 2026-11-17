
"""Identificadores deterministas para vincular SalesIQ y CRM."""

import hashlib
import re


PATRON_INTENTO = re.compile(
    r"SIQ-[0-9]{4,30}-[A-Za-z0-9_-]{1,128}"
)


def generar_id_crm(attempt_id: str) -> str:
    """Convierte un Attempt ID de Analytics en 32 caracteres hex."""

    if not isinstance(attempt_id, str):
        raise ValueError("Attempt ID debe ser texto")

    if not PATRON_INTENTO.fullmatch(attempt_id):
        raise ValueError("Formato de Attempt ID invalido")

    identificador = hashlib.blake2s(
        attempt_id.encode("utf-8"),
        digest_size=16,
    ).hexdigest()

    return identificador
