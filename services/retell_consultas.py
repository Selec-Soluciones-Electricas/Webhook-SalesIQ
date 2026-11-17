def clasificar_consulta_sofia(llamada, agent_id):
    """
    Identifica consultas generales de Sofia.

    Solo analiza datos de Retell.
    No consulta ni modifica Zoho CRM.
    """

    if not isinstance(llamada, dict):
        return {"estado": "revision", "motivo": "llamada_invalida"}

    if not isinstance(agent_id, str) or not agent_id.strip():
        return {"estado": "revision", "motivo": "agente_invalido"}

    if llamada.get("agent_id") != agent_id:
        return {"estado": "ignorar", "motivo": "otro_agente"}

    if llamada.get("call_type") != "phone_call":
        return {"estado": "ignorar", "motivo": "no_telefonica"}

    if llamada.get("call_status") != "ended":
        return {"estado": "ignorar", "motivo": "no_finalizada"}

    call_id = llamada.get("call_id")

    if (
        not isinstance(call_id, str)
        or not call_id.strip()
        or len(call_id) > 128
        or any(c in call_id for c in "\r\n")
    ):
        return {"estado": "revision", "motivo": "call_id_invalido"}

    analisis = llamada.get("call_analysis")

    if not isinstance(analisis, dict):
        return {"estado": "revision", "motivo": "sin_analisis"}

    datos = analisis.get("custom_analysis_data")

    if not isinstance(datos, dict):
        return {"estado": "revision", "motivo": "sin_datos"}

    tipo = datos.get("tipo_solicitud")

    if not isinstance(tipo, str) or not tipo.strip():
        return {
            "estado": "revision",
            "motivo": "tipo_solicitud_ausente",
        }

    if tipo.strip().lower() != "consulta":
        return {"estado": "ignorar", "motivo": "otro_tipo"}

    interlocutor = datos.get("tipo_interlocutor")
    interlocutor = (
        interlocutor.strip().lower()
        if isinstance(interlocutor, str)
        else None
    )

    if interlocutor not in ("cliente", "proveedor", "otro"):
        interlocutor = None

    prioridad = datos.get("prioridad_caso")
    prioridades = {
        "alto": "Alto",
        "medio": "Medio",
        "bajo": "Bajo",
    }

    prioridad = (
        prioridades.get(prioridad.strip().lower())
        if isinstance(prioridad, str)
        else None
    )

    resultado = datos.get("resultado_atencion")
    resultado = (
        resultado.strip().lower()
        if isinstance(resultado, str)
        else None
    )

    if resultado not in (
        "resuelto_por_sofia",
        "requiere_gestion",
        "incompleto",
    ):
        resultado = None


    resumen = analisis.get("call_summary")

    if not isinstance(resumen, str) or not resumen.strip():
        return {
            "estado": "revision",
            "motivo": "resumen_ausente",
        }

    resumen = resumen.strip()


    # Extraer datos de contacto sin inventar valores.
    def limpiar_dato(nombre_campo):
        valor = datos.get(nombre_campo)

        if not isinstance(valor, str):
            return None

        valor = " ".join(valor.split())

        if not valor or len(valor) > 200:
            return None

        return valor

    contacto = {
        "nombre_cliente": limpiar_dato("nombre_cliente"),
        "email_cliente": limpiar_dato("email_cliente"),
        "telefono_cliente": limpiar_dato("telefono_cliente"),
        "empresa": limpiar_dato("empresa"),
        "rut_cliente": limpiar_dato("rut_cliente"),
        "motivo_contacto": limpiar_dato("motivo_contacto"),
    }

    return {
        "estado": "candidata_caso",
        "call_id": call_id.strip(),
        "tipo_solicitud": "consulta",
        "tipo_interlocutor": interlocutor,
        "prioridad_caso": prioridad,
        "resultado_atencion": resultado,
        "resumen": resumen,
        "contacto": contacto,
    }