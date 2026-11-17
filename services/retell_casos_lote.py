
from services.retell_casos import (
    preparar_borrador_caso_consulta,
)


def preparar_borradores_consultas(consultas):
    """
    Prepara borradores de Casos para consultas de Sofia.

    No consulta Retell ni Zoho CRM.
    No realiza escrituras.
    Bloquea Call ID duplicados en el mismo lote.
    """

    if not isinstance(consultas, list):
        raise ValueError("Lista de consultas invalida")

    borradores = []
    call_ids_vistos = set()

    for consulta in consultas:

        if not isinstance(consulta, dict):
            raise ValueError("Consulta invalida")

        borrador = preparar_borrador_caso_consulta(
            consulta
        )

        if not isinstance(borrador, dict):
            raise ValueError("Borrador invalido")

        call_id = borrador.get("call_id")

        if not isinstance(call_id, str) or not call_id.strip():
            raise ValueError("Call ID invalido")

        if call_id in call_ids_vistos:
            raise ValueError(
                "Call ID duplicado en consultas"
            )

        call_ids_vistos.add(call_id)
        borradores.append(borrador)

    return borradores


def dividir_consultas_en_lotes(consultas, tamano_lote=10):
    """
    Divide consultas de Sofia en lotes controlados.

    No consulta Retell ni Zoho CRM.
    No modifica registros.
    Conserva el orden de las consultas.
    """

    if not isinstance(consultas, list):
        raise ValueError("Lista de consultas invalida")

    if (
        type(tamano_lote) is not int
        or not 1 <= tamano_lote <= 10
    ):
        raise ValueError("Tamano de lote invalido")

    lotes = []

    for inicio in range(0, len(consultas), tamano_lote):
        lote = consultas[
            inicio:inicio + tamano_lote
        ]

        lotes.append(lote)

    return lotes


def planificar_lotes_consultas(
    consultas,
    tamano_lote=10,
    max_consultas=30,
):
    """
    Planifica los lotes de consultas de Sofia.

    Aplica un limite global antes de permitir
    verificaciones contra Zoho CRM.

    No consulta APIs ni modifica registros.
    """

    if (
        type(max_consultas) is not int
        or not 1 <= max_consultas <= 30
    ):
        raise ValueError("Limite global invalido")

    # Validar la lista y el tamano de cada lote.
    lotes = dividir_consultas_en_lotes(
        consultas,
        tamano_lote=tamano_lote,
    )

    total = len(consultas)

    if total > max_consultas:
        return {
            "estado": "limite_global_superado",
            "total_consultas": total,
            "limite_global": max_consultas,
            "lotes": [],
        }

    return {
        "estado": "listo",
        "total_consultas": total,
        "limite_global": max_consultas,
        "lotes": lotes,
    }


def planificar_recuperacion_consultas(
    consultas,
    resultados_por_id,
    max_pendientes=30,
):
    """
    Separa consultas registradas y pendientes.

    No consulta APIs ni modifica registros.
    Solo selecciona hasta 30 pendientes.
    """

    if not isinstance(consultas, list):
        raise ValueError("Consultas invalidas")

    if not isinstance(resultados_por_id, dict):
        raise ValueError("Resultados CRM invalidos")

    if (
        type(max_pendientes) is not int
        or not 1 <= max_pendientes <= 30
    ):
        raise ValueError("Limite invalido")

    ids = []

    for consulta in consultas:
        if not isinstance(consulta, dict):
            raise ValueError("Consulta invalida")

        call_id = consulta.get("call_id")

        if (
            not isinstance(call_id, str)
            or not call_id.strip()
            or call_id != call_id.strip()
        ):
            raise ValueError("Call ID invalido")

        ids.append(call_id)

    if len(ids) != len(set(ids)):
        raise ValueError("Call ID duplicado")

    if set(resultados_por_id) != set(ids):
        raise ValueError("Busqueda CRM incompleta")

    pendientes = []
    ya_registradas = 0

    for consulta in consultas:
        call_id = consulta["call_id"]
        resultado = resultados_por_id[call_id]

        if not isinstance(resultado, dict):
            raise ValueError("Resultado CRM invalido")

        estado = resultado.get("estado")
        registro_id = resultado.get("registro_id")

        if estado == "encontrado":
            if (
                not isinstance(registro_id, str)
                or not registro_id.strip()
            ):
                raise ValueError("Caso encontrado sin ID")

            ya_registradas += 1

        elif estado == "no_encontrado":
            if registro_id is not None:
                raise ValueError("Resultado contradictorio")

            pendientes.append(consulta)

        else:
            raise ValueError("Estado CRM no confirmado")

    seleccionadas = pendientes[:max_pendientes]
    restantes = len(pendientes) - len(seleccionadas)

    return {
        "estado": (
            "listo"
            if restantes == 0
            else "pendientes_por_continuar"
        ),
        "total_consultas": len(consultas),
        "ya_registradas": ya_registradas,
        "total_pendientes": len(pendientes),
        "seleccionadas": seleccionadas,
        "pendientes_fuera_de_limite": restantes,
        "recuperacion_completada": False,
    }


def consultar_consultas_en_lotes(
    consultas,
    consultar_lote,
    tamano_lote=10,
    max_lotes=10,
):
    """
    Consulta los estados de Casos por lotes.

    El cliente de Zoho se recibe como argumento.
    No crea ni modifica registros.
    Nunca devuelve resultados parciales como validos.
    """

    if not callable(consultar_lote):
        raise ValueError("Consultor invalido")

    if (
        type(max_lotes) is not int
        or not 1 <= max_lotes <= 10
    ):
        raise ValueError("Limite de lotes invalido")

    lotes = dividir_consultas_en_lotes(
        consultas,
        tamano_lote=tamano_lote,
    )

    permitidos = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789_-"
    )

    ids_vistos = set()

    # Validar todas las consultas antes de buscar.
    for consulta in consultas:

        if not isinstance(consulta, dict):
            raise ValueError("Consulta invalida")

        call_id = consulta.get("call_id")

        if (
            not isinstance(call_id, str)
            or not 3 <= len(call_id) <= 128
            or any(c not in permitidos for c in call_id)
            or call_id in ids_vistos
        ):
            raise ValueError("Call ID invalido o duplicado")

        ids_vistos.add(call_id)

    total_lotes = len(lotes)

    # No iniciar busquedas si se supera el presupuesto.
    if total_lotes > max_lotes:
        return {
            "estado": "limite_busquedas_superado",
            "resultados": {},
            "lotes_consultados": 0,
            "total_lotes": total_lotes,
        }

    resultados = {}
    lotes_consultados = 0

    def fallo():
        return {
            "estado": "error_consulta",
            "resultados": {},
            "lotes_consultados": lotes_consultados,
            "total_lotes": total_lotes,
        }

    for lote in lotes:
        ids_lote = [
            consulta["call_id"]
            for consulta in lote
        ]

        try:
            respuesta = consultar_lote(ids_lote)
        except Exception:
            return fallo()

        lotes_consultados += 1

        if (
            not isinstance(respuesta, dict)
            or respuesta.get("estado") != "ok"
        ):
            return fallo()

        datos = respuesta.get("resultados")

        if (
            not isinstance(datos, dict)
            or set(datos) != set(ids_lote)
        ):
            return fallo()

        for call_id in ids_lote:
            item = datos[call_id]

            if not isinstance(item, dict):
                return fallo()

            estado = item.get("estado")
            registro_id = item.get("registro_id")

            if estado == "encontrado":
                if (
                    not isinstance(registro_id, str)
                    or not registro_id.strip()
                ):
                    return fallo()

            elif estado == "no_encontrado":
                if registro_id is not None:
                    return fallo()

            else:
                return fallo()

        resultados.update(datos)

    return {
        "estado": "ok",
        "resultados": resultados,
        "lotes_consultados": lotes_consultados,
        "total_lotes": total_lotes,
    }
