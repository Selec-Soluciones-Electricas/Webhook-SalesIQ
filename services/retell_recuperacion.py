
from services.retell_validacion import (
    preparar_cotizacion_desde_llamada_retell,
)


def clasificar_llamada_recuperacion(
    llamada, agent_id, *, permitir_rut_ficticio=False
):
    """
    Clasifica llamadas para una futura recuperacion.

    Solo evalua cotizaciones telefonicas del agente
    indicado. No consulta ni modifica Zoho CRM.
    """

    if not isinstance(llamada, dict):
        return {"estado": "revision", "motivo": "llamada_invalida"}

    if not isinstance(agent_id, str) or not agent_id.strip():
        return {"estado": "revision", "motivo": "agente_invalido"}

    if llamada.get("agent_id") != agent_id:
        return {"estado": "ignorar", "motivo": "otro_agente"}

    # No procesar pruebas realizadas desde el navegador
    if llamada.get("call_type") != "phone_call":
        return {"estado": "ignorar", "motivo": "no_telefonica"}

    if llamada.get("call_status") != "ended":
        return {"estado": "ignorar", "motivo": "no_finalizada"}

    analisis = llamada.get("call_analysis")

    if not isinstance(analisis, dict):
        return {"estado": "revision", "motivo": "sin_analisis"}

    datos = analisis.get("custom_analysis_data")

    if not isinstance(datos, dict):
        return {"estado": "revision", "motivo": "sin_datos"}


    tipo = str(
        datos.get("tipo_solicitud") or ""
    ).strip().lower()

    # Si Retell no identifica el tipo de solicitud,
    # no asumir que el cliente pidio otra cosa.
    if not tipo:
        return {
            "estado": "revision",
            "motivo": "tipo_solicitud_ausente",
        }

    # Solo descartar de la recuperacion de
    # cotizaciones las solicitudes identificadas
    # explicitamente como otro tipo.
    if tipo != "cotizacion":
        return {
            "estado": "otra_solicitud",
            "tipo": tipo,
        }


    try:
        resultado = preparar_cotizacion_desde_llamada_retell(
            llamada,
            permitir_rut_ficticio=permitir_rut_ficticio
        )
    except Exception:
        return {"estado": "revision", "motivo": "error_validacion"}

    if not resultado.get("lista"):
        return {
            "estado": "revision",
            "motivo": "datos_incompletos",
            "faltantes": resultado.get("faltantes", []),
        }

    return {
        "estado": "candidata",
        "call_id": llamada["call_id"],
    }


def revisar_pendiente_retell(llamada, agent_id):
    """
    Clasifica una llamada y verifica si su negocio
    ya existe en Zoho CRM.

    No crea ni modifica registros.
    """

    from services.retell_duplicados import (
        buscar_negocio_por_call_id
    )

    # 1. Clasificar la llamada
    clasificacion = clasificar_llamada_recuperacion(
        llamada,
        agent_id,
    )

    # Ignorar llamadas que no sean candidatas
    if clasificacion.get("estado") != "candidata":
        return clasificacion

    call_id = clasificacion["call_id"]

    # 2. Consultar Zoho CRM
    try:
        consulta = buscar_negocio_por_call_id(call_id)

    except Exception as error:
        print(
            "[RETELL] Error verificando llamada:",
            type(error).__name__,
        )
        return {
            "estado": "no_verificada",
            "call_id": call_id,
        }

    if not isinstance(consulta, dict):
        return {
            "estado": "no_verificada",
            "call_id": call_id,
        }

    # 3. Negocio ya registrado
    if (
        consulta.get("estado") == "encontrado"
        and consulta.get("negocio_id")
    ):
        return {
            "estado": "registrada",
            "call_id": call_id,
            "negocio_id": consulta["negocio_id"],
        }

    # 4. Negocio no encontrado
    if consulta.get("estado") == "no_encontrado":
        return {
            "estado": "posible_pendiente",
            "call_id": call_id,
        }

    # 5. Respuesta incierta o error
    return {
        "estado": "no_verificada",
        "call_id": call_id,
    }


def auditar_llamadas_retell(llamadas, agent_id, limite_consultas=10):
    """
    Revisa un conjunto de llamadas de Retell y
    genera un resumen de sus estados.

    No crea ni modifica registros en Zoho CRM.
    """

    if not isinstance(llamadas, list):
        raise ValueError("Las llamadas deben ser una lista")

    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("Agent ID invalido")

    if (
        type(limite_consultas) is not int
        or not 1 <= limite_consultas <= 50
    ):
        raise ValueError("Limite de consultas invalido")

    resultados = []
    consultas = 0

    for llamada in llamadas:

        # 1. Clasificar antes de consultar Zoho
        clasificacion = clasificar_llamada_recuperacion(
            llamada,
            agent_id,
        )

        estado = clasificacion["estado"]

        call_id = (
            llamada.get("call_id")
            if isinstance(llamada, dict)
            else None
        )

        # 2. Consultar Zoho solamente para candidatas
        if estado == "candidata":

            if consultas >= limite_consultas:
                estado = "sin_consultar"

            else:
                consultas += 1

                try:
                    revision = revisar_pendiente_retell(
                        llamada,
                        agent_id,
                    )

                    estado = revision.get(
                        "estado",
                        "no_verificada",
                    )

                except Exception as error:
                    print(
                        "[RETELL] Error auditando llamada:",
                        type(error).__name__,
                    )
                    estado = "no_verificada"


        # 3. Guardar el resultado de la auditoria
        detalle = {
            "call_id": call_id,
            "estado": estado,
        }

        # Conservar el motivo cuando una llamada
        # necesite revision humana.
        if estado == "revision":

            motivo = clasificacion.get("motivo")

            if isinstance(motivo, str) and motivo:
                detalle["motivo"] = motivo

            faltantes = clasificacion.get("faltantes")

            if isinstance(faltantes, list):
                detalle["faltantes"] = faltantes.copy()

        resultados.append(detalle)


    # 4. Preparar resumen de la auditoria
    estados = (
        "registrada",
        "posible_pendiente",
        "no_verificada",
        "sin_consultar",
        "revision",
        "ignorar",
        "otra_solicitud",
    )

    resumen = {
        estado: sum(
            1
            for resultado in resultados
            if resultado["estado"] == estado
        )
        for estado in estados
    }

    return {
        "total_llamadas": len(llamadas),
        "consultas_zoho": consultas,
        "resumen": resumen,
        "resultados": resultados,
    }



def auditar_historial_sofia(
    agent_id,
    max_paginas=3,
    limite_consultas=10,
):
    """
    Recupera el historial de Sofia desde Retell
    y audita las cotizaciones en Zoho CRM.

    Solo realiza consultas.
    No crea ni modifica registros.
    """

    from services.retell_historial import (
        obtener_historial_retell,
    )

    # 1. Recuperar llamadas desde Retell
    historial = obtener_historial_retell(
        agent_id,
        limite_por_pagina=50,
        max_paginas=max_paginas,
    )

    # 2. Auditar las llamadas recuperadas
    auditoria = auditar_llamadas_retell(
        historial["llamadas"],
        agent_id,
        limite_consultas=limite_consultas,
    )

    # 3. Agregar informacion del historial
    auditoria["paginas_retell"] = historial["paginas"]
    auditoria["historial_completo"] = historial["completa"]

    return auditoria
