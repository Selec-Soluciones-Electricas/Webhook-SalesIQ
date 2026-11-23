
def clasificar_postventa_sofia(llamada, agent_id):
    """
    Prepara una postventa telefonica para registrar
    un Caso de Sofia en Zoho CRM.

    No realiza conexiones ni escrituras.
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

    if not isinstance(tipo, str) or tipo.strip().lower() != "postventa":
        return {"estado": "ignorar", "motivo": "otro_tipo"}

    def limpiar(campo, limite=200):
        valor = datos.get(campo)

        if not isinstance(valor, str):
            return None

        valor = " ".join(valor.split())

        if not valor or len(valor) > limite:
            return None

        return valor

    resumen = analisis.get("call_summary")

    if isinstance(resumen, str) and resumen.strip():
        resumen = resumen.strip()[:4000]
    else:
        resumen = None

    descripcion = limpiar("descripcion_problema", 2000)

    if not resumen and not descripcion:
        return {
            "estado": "revision",
            "motivo": "detalle_postventa_ausente",
        }


    # Validar informacion minima para registrar
    # automaticamente una postventa en Zoho CRM.
    faltantes = []

    if not limpiar("nombre_cliente"):
        faltantes.append("nombre_cliente")

    if not limpiar("rut_cliente"):
        faltantes.append("rut_cliente")

    if not (
        limpiar("telefono_cliente")
        or limpiar("email_cliente")
    ):
        faltantes.append("telefono_o_email")

    if not (
        limpiar("numero_factura")
        or limpiar("numero_oc")
    ):
        faltantes.append("numero_factura_o_oc")

    if not descripcion:
        faltantes.append("descripcion_problema")

    if faltantes:
        return {
            "estado": "revision",
            "motivo": "datos_postventa_incompletos",
            "faltantes": faltantes,
        }

    contacto = {
        "nombre_cliente": limpiar("nombre_cliente"),
        "email_cliente": limpiar("email_cliente"),
        "telefono_cliente": limpiar("telefono_cliente"),
        "empresa": limpiar("empresa"),
        "rut_cliente": limpiar("rut_cliente"),
        "numero_factura": limpiar("numero_factura"),
        "numero_oc": limpiar("numero_oc"),
        "motivo_contacto": limpiar("motivo_contacto"),
        "descripcion_problema": descripcion,
    }

    return {
        "estado": "candidata_caso",
        "call_id": call_id.strip(),
        "tipo_solicitud": "postventa",
        "tipo_interlocutor": "cliente",
        "resultado_atencion": limpiar("resultado_atencion"),
        "resumen": resumen or descripcion,
        "contacto": contacto,
    }
