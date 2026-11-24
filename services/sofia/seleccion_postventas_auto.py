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

def seleccionar_postventas_prueba_segura(
    postventas,
    *,
    inicio_minimo_ms,
):
    """
    Seleccion controlada para la primera prueba automatica.

    Solo permite postventas validadas y posteriores
    a la fecha minima indicada.

    Si hay mas de una candidata nueva, bloquea
    toda la seleccion.

    No realiza conexiones ni escrituras.
    """
    if (
        type(inicio_minimo_ms) is not int
        or inicio_minimo_ms <= 0
    ):
        raise ValueError("Fecha minima invalida")

    validadas = seleccionar_postventas_automaticas(
        postventas
    )

    recientes = []

    for postventa in validadas:
        fecha = postventa.get("start_timestamp")

        if type(fecha) is not int or fecha <= 0:
            raise ValueError(
                "Fecha de llamada no verificable"
            )

        if fecha >= inicio_minimo_ms:
            recientes.append(postventa)

    if len(recientes) > 1:
        raise ValueError(
            "Multiples postventas nuevas: revision requerida"
        )

    return recientes


def seleccionar_postventas_lote_seguro(
    postventas,
    *,
    inicio_minimo_ms,
    max_por_ejecucion=3,
):
    """
    Prepara lotes acotados de postventas pendientes.

    El consumidor debe verificar previamente en Zoho
    cuales Casos existen.

    No realiza consultas ni escrituras.
    """
    if (
        type(inicio_minimo_ms) is not int
        or inicio_minimo_ms <= 0
    ):
        raise ValueError("Fecha minima invalida")

    if (
        type(max_por_ejecucion) is not int
        or not 1 <= max_por_ejecucion <= 5
    ):
        raise ValueError("Limite de lote invalido")

    validadas = seleccionar_postventas_automaticas(
        postventas
    )

    recientes = []

    for postventa in validadas:
        fecha = postventa.get("start_timestamp")

        if type(fecha) is not int or fecha <= 0:
            raise ValueError("Fecha de llamada invalida")

        if fecha >= inicio_minimo_ms:
            recientes.append(postventa)

    recientes.sort(
        key=lambda p: (
            p["start_timestamp"],
            p["call_id"],
        )
    )

    seleccionadas = recientes[:max_por_ejecucion]

    return {
        "seleccionadas": seleccionadas,
        "total_recientes": len(recientes),
        "pendientes_por_continuar": (
            len(recientes) - len(seleccionadas)
        ),
    }
