
"""Seleccion segura de consultas generales para Zoho Sandbox."""

import re


def seleccionar_consultas_lote_seguro(
    consultas,
    *,
    inicio_minimo_ms,
    max_por_ejecucion=3,
):
    """
    Selecciona consultas recientes y validadas.
    No consulta APIs ni crea registros.
    """
    if not isinstance(consultas, list):
        raise ValueError("Lista de consultas invalida")

    if type(inicio_minimo_ms) is not int or inicio_minimo_ms <= 0:
        raise ValueError("Fecha minima invalida")

    if (
        type(max_por_ejecucion) is not int
        or not 1 <= max_por_ejecucion <= 5
    ):
        raise ValueError("Limite de lote invalido")

    recientes = []
    ids = set()

    for consulta in consultas:
        if not isinstance(consulta, dict):
            raise ValueError("Consulta invalida")

        if (
            consulta.get("estado") != "candidata_caso"
            or consulta.get("tipo") != "consulta"
            or consulta.get("tipo_solicitud") != "consulta"
        ):
            raise ValueError("Consulta no autorizada")

        call_id = consulta.get("call_id")

        if (
            not isinstance(call_id, str)
            or not re.fullmatch(
                r"call_[A-Za-z0-9_-]{1,123}",
                call_id,
            )
        ):
            raise ValueError("Call ID invalido")

        if call_id in ids:
            raise ValueError("Call ID duplicado")

        ids.add(call_id)

        fecha = consulta.get("start_timestamp")

        if type(fecha) is not int or fecha <= 0:
            raise ValueError("Fecha de llamada invalida")

        if fecha >= inicio_minimo_ms:
            recientes.append(consulta.copy())

    recientes.sort(
        key=lambda c: (
            c["start_timestamp"],
            c["call_id"],
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
