import re

from services import zoho_service


def buscar_asunto_control_zoho(modulo, asunto, *, conexion=None):
    """
    Busca un identificador de control en Zoho CRM.

    Solo lectura. No crea registros ni envia correos.

    Esta funcion NO confirma que una notificacion
    haya sido enviada.
    """

    error = {
        "estado": "error",
        "registro_id": None,
    }

    if modulo not in ("Cases", "Tasks"):
        return error

    if (
        not isinstance(asunto, str)
        or not re.fullmatch(
            r"[A-Za-z0-9_-]{3,200}",
            asunto,
        )
    ):
        return error

    try:
        if not isinstance(conexion, dict):
            return error

        base = conexion.get("base")
        obtener_token = conexion.get("obtener_token")
        http_get = conexion.get("http_get")

        if (
            base != "https://sandbox.zohoapis.com"
            or not callable(obtener_token)
            or not callable(http_get)
        ):
            return error

        token = obtener_token()

        if not isinstance(token, str) or not token.strip():
            return error

        respuesta = http_get(

            f"{base}/crm/v8/{modulo}/search",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}"
            },
            params={
                "criteria": f"(Subject:equals:{asunto})",
                "fields": "Subject",
                "per_page": 200,
            },
            timeout=15,
        )

        if respuesta.status_code == 204:
            return {
                "estado": "no_encontrado",
                "registro_id": None,
            }

        if respuesta.status_code != 200:
            return error

        datos = respuesta.json()

        registros = datos.get("data")
        info = datos.get("info")

        if (
            not isinstance(registros, list)
            or not isinstance(info, dict)
            or info.get("more_records") is not False
        ):
            return error

        coincidencias = [
            registro
            for registro in registros
            if (
                isinstance(registro, dict)
                and registro.get("Subject") == asunto
            )
        ]

        if len(coincidencias) > 1:
            return error

        if not coincidencias:
            return {
                "estado": "no_encontrado",
                "registro_id": None,
            }

        registro_id = coincidencias[0].get("id")

        if not isinstance(registro_id, str) or not registro_id:
            return error

        return {
            "estado": "encontrado",
            "registro_id": registro_id,
        }

    except Exception:
        return error

def construir_asunto_control_zoho(id_notificacion):
    """
    Genera un identificador estable compatible
    con las busquedas de Zoho CRM.

    No consulta Zoho ni modifica registros.
    """
    from hashlib import sha256

    if not isinstance(id_notificacion, str):
        raise ValueError("Identificador invalido")

    partes = id_notificacion.split(":", 2)

    if (
        len(partes) != 3
        or partes[0] != "sofia"
        or partes[1] not in ("postventa", "revision")
        or not partes[2].strip()
        or any(c in partes[2] for c in "\r\n")
    ):
        raise ValueError("Identificador invalido")

    huella = sha256(
        id_notificacion.encode("utf-8")
    ).hexdigest().upper()

    return f"SOFIA_{partes[1].upper()}_{huella}"

def preparar_borrador_caso_control_zoho(borrador):
    """
    Prepara un Case de control para una notificacion
    de Sofia.

    Solo construye datos.
    No consulta ni modifica Zoho CRM.
    No envia correos.
    """

    if not isinstance(borrador, dict):
        raise ValueError("Borrador invalido")

    tipo = borrador.get("tipo")
    call_id = borrador.get("call_id")
    identificador = borrador.get("id_notificacion")

    if tipo not in ("postventa", "revision"):
        raise ValueError("Tipo de seguimiento invalido")

    if (
        not isinstance(call_id, str)
        or not call_id.strip()
        or any(c in call_id for c in "\r\n")
    ):
        raise ValueError("Call ID invalido")

    esperado = f"sofia:{tipo}:{call_id}"

    if identificador != esperado:
        raise ValueError(
            "Identificador de notificacion inconsistente"
        )

    asunto = construir_asunto_control_zoho(
        identificador
    )

    descripcion = (
        "Control de seguimiento telefonico de Sofia.\n\n"
        f"Call ID: {call_id}\n"
        f"Tipo: {tipo}\n"
        f"ID notificacion: {identificador}\n"
        "Estado inicial: PENDIENTE\n\n"
        "Este registro no confirma el envio de correos."
    )

    return {
        "modulo": "Cases",
        "asunto_control": asunto,
    "campos_nuevo_registro": {
        "Subject": asunto,
        "Case_Origin": "SELEC",
        "Status": "New",
        "Description": descripcion,
    },
    }

def preparar_upsert_control_zoho(borrador):
    """
    Prepara una solicitud upsert para Cases.

    No ejecuta solicitudes HTTP.
    No modifica registros.
    No envia correos.

    IMPORTANTE:
    El upsert puede actualizar registros existentes.
    No ejecutarlo sin comprobar previamente el estado
    del Case y proteger sus campos de seguimiento.
    """

    control = preparar_borrador_caso_control_zoho(
        borrador
    )

    campos = control[
        "campos_nuevo_registro"
    ].copy()

    return {
        "modulo": "Cases",
        "operacion": "upsert",
        "asunto_control": control["asunto_control"],
        "payload": {
            "data": [campos],
            "duplicate_check_fields": ["Subject"],
            "trigger": [],
        },
    }

def planificar_registro_control_zoho(
    borrador,
    resultado_busqueda,
):
    """
    Planifica el registro de control de Sofia.

    No realiza escrituras ni envia correos.
    Nunca autoriza directamente un upsert.
    """

    control = preparar_borrador_caso_control_zoho(
        borrador
    )

    asunto = control["asunto_control"]

    bloqueado = {
        "estado": "bloqueado",
        "asunto_control": asunto,
        "registro_id": None,
        "solicitud_propuesta": None,
        "autorizar_escritura": False,
    }

    if not isinstance(resultado_busqueda, dict):
        return bloqueado

    estado = resultado_busqueda.get("estado")
    registro_id = resultado_busqueda.get("registro_id")

    if estado == "encontrado":
        if (
            not isinstance(registro_id, str)
            or not registro_id.strip()
        ):
            return bloqueado

        return {
            "estado": "existente",
            "asunto_control": asunto,
            "registro_id": registro_id,
            "solicitud_propuesta": None,
            "autorizar_escritura": False,
        }

    if estado == "no_encontrado":
        if registro_id is not None:
            return bloqueado

        return {
            "estado": "candidato_creacion",
            "asunto_control": asunto,
            "registro_id": None,
            "solicitud_propuesta": (
                preparar_upsert_control_zoho(borrador)
            ),
            "autorizar_escritura": False,
        }

    return bloqueado

def interpretar_respuesta_upsert_control_zoho(
    codigo_http,
    datos,
):
    """
    Interpreta la respuesta de Zoho CRM.

    No realiza conexiones.
    No autoriza correos.
    No modifica registros.
    """

    bloqueado = {
        "estado": "bloqueado",
        "registro_id": None,
        "autorizar_correo": False,
    }

    if codigo_http not in (200, 201):
        return bloqueado

    if not isinstance(datos, dict):
        return bloqueado

    registros = datos.get("data")

    if (
        not isinstance(registros, list)
        or len(registros) != 1
    ):
        return bloqueado

    registro = registros[0]

    if not isinstance(registro, dict):
        return bloqueado

    if (
        registro.get("status") != "success"
        or registro.get("code") != "SUCCESS"
    ):
        return bloqueado

    accion = registro.get("action")
    detalles = registro.get("details")

    if accion not in ("insert", "update"):
        return bloqueado

    if not isinstance(detalles, dict):
        return bloqueado

    registro_id = detalles.get("id")

    if (
        not isinstance(registro_id, str)
        or not registro_id.strip()
    ):
        return bloqueado

    return {
        "estado": (
            "creado"
            if accion == "insert"
            else "existente"
        ),
        "registro_id": registro_id,
        "autorizar_correo": False,
    }