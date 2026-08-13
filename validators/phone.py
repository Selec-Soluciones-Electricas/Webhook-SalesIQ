import re


def limpiar_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def es_telefono_plausible(s: str) -> bool:
    d = limpiar_digitos(s or "")
    return 5 <= len(d) <= 12