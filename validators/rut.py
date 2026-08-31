import re

from validators.phone import limpiar_digitos


def es_rut_plausible(s: str) -> bool:
    s_norm = (s or "").strip()
    if re.search(r"\d{1,3}.?\d{3}.?\d{3}-[\dkK]", s_norm):
        return True
    d = limpiar_digitos(s_norm)
    return 7 <= len(d) <= 12