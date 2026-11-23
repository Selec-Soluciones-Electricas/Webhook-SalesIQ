"""Seleccion segura de postventas para automatizacion Sandbox."""

import re


def seleccionar_postventas_automaticas(postventas):
    """
    Selecciona exclusivamente postventas previamente validadas.

    No consulta APIs ni crea registros.
    Ante datos inconsistentes, detiene la seleccion.
    """
    if not isinstance(postventas, list):
        raise ValueError("Lista de postventas invalida")

    seleccionadas = []
    ids = set()

    for postventa in postventas:
        if not isinstance(postventa, dict):
            raise ValueError("Postventa invalida")

        if (
            postventa.get("tipo") != "postventa"
            or postventa.get("estado") != "candidata_caso"
            or postventa.get("faltantes") not in (None, [])
        ):
            raise ValueError("Postventa no autorizada")

        call_id = postventa.get("call_id")

        if (
            not isinstance(call_id, str)
            or not re.fullmatch(r"call_[A-Za-z0-9_-]{1,123}", call_id)
        ):
            raise ValueError("Call ID invalido")

        if call_id in ids:
            raise ValueError("Call ID duplicado")

        ids.add(call_id)
        seleccionadas.append(postventa.copy())

    return seleccionadas
