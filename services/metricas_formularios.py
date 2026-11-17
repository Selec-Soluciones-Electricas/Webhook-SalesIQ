
"""Seguimiento de formularios de cotización SELEC.

Prepara registros para Zoho Analytics.
No realiza consultas ni escrituras externas.
"""

import re
from datetime import datetime, timezone


PATRON_ID_FORMULARIO = re.compile(
    r"[0-9a-f]{32}"
)

ORIGENES_VALIDOS = {
    "whatsapp",
    "web",
}


def preparar_inicio(form_session_id, origen, ahora=None):
    """
    Prepara un registro de inicio del formulario.

    No guarda información en Zoho Analytics.
    """

    if (
        not isinstance(form_session_id, str)
        or not PATRON_ID_FORMULARIO.fullmatch(
            form_session_id
        )
    ):
        raise ValueError(
            "ID de formulario invalido"
        )

    if origen not in ORIGENES_VALIDOS:
        raise ValueError(
            "Origen de formulario invalido"
        )

    if ahora is None:
        ahora = datetime.now(timezone.utc)

    if (
        not isinstance(ahora, datetime)
        or ahora.tzinfo is None
        or ahora.utcoffset() is None
    ):
        raise ValueError(
            "Fecha debe incluir zona horaria"
        )

    fecha = ahora.astimezone(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "ID Formulario": form_session_id,
        "Origen": origen,
        "Estado": "INICIADA",
        "Fecha Inicio": fecha,
        "Fecha Ultima Actividad": fecha,
        "Fecha Actualizacion": fecha,
    }


def preparar_confirmacion(form_session_id, deal_id, ahora=None):
    """
    Prepara la actualizacion de un formulario completado.

    Solo debe utilizarse cuando CRM confirme el Deal ID.
    No realiza escrituras externas.
    """

    if (
        not isinstance(form_session_id, str)
        or not PATRON_ID_FORMULARIO.fullmatch(form_session_id)
    ):
        raise ValueError("ID de formulario invalido")

    if (
        not isinstance(deal_id, str)
        or not re.fullmatch(r"[0-9]{10,30}", deal_id)
    ):
        raise ValueError("ID de negocio invalido")

    if ahora is None:
        ahora = datetime.now(timezone.utc)

    if (
        not isinstance(ahora, datetime)
        or ahora.tzinfo is None
        or ahora.utcoffset() is None
    ):
        raise ValueError("Fecha debe incluir zona horaria")

    fecha = ahora.astimezone(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    return {
        "Estado": "COMPLETADA",
        "ID Negocio": deal_id,
        "Fecha Confirmacion CRM": fecha,
        "Fecha Actualizacion": fecha,
    }


def preparar_actualizacion_analytics(form_session_id, deal_id, ahora=None):
    """
    Prepara la configuracion para actualizar un formulario
    existente en Zoho Analytics.

    No crea filas ni realiza consultas externas.
    """

    columnas = preparar_confirmacion(
        form_session_id,
        deal_id,
        ahora,
    )

    return {
        "columns": columnas,
        "criteria": f'"ID Formulario" = \'{form_session_id}\'',
        "dateFormat": "yyyy-MM-dd HH:mm:ss",
        "addIfNotExist": False,
    }


def preparar_insercion_analytics(form_session_id, origen, ahora=None):
    """
    Prepara la insercion de una sesion iniciada.

    No realiza consultas ni escrituras en Zoho Analytics.
    """

    registro = preparar_inicio(
        form_session_id,
        origen,
        ahora,
    )

    return {
        "columns": registro,
        "dateFormat": "yyyy-MM-dd HH:mm:ss",
    }


def obtener_url_analytics_formularios():
    """
    Obtiene la direccion de la tabla de seguimiento.

    No realiza conexiones ni escrituras.
    """

    import os
    from pathlib import Path
    from dotenv import load_dotenv

    from SELEC_metricas_guardado_seguro import (
        BASE_URL,
        VIEW_ID,
    )

    load_dotenv(
        Path(__file__).resolve().parents[1] / ".env"
    )

    workspace_id = os.getenv(
        "SELEC_FORMULARIOS_WORKSPACE_ID", ""
    ).strip()

    vista_id = os.getenv(
        "SELEC_FORMULARIOS_VIEW_ID", ""
    ).strip()

    if not workspace_id.isdigit() or not vista_id.isdigit():
        raise RuntimeError(
            "Identificadores Analytics no configurados"
        )

    if f"/workspaces/{workspace_id}/" not in BASE_URL:
        raise RuntimeError(
            "El Workspace de Analytics no coincide"
        )

    if not BASE_URL.endswith(f"/views/{VIEW_ID}"):
        raise RuntimeError(
            "La direccion base de Analytics es inesperada"
        )

    if vista_id == str(VIEW_ID):
        raise RuntimeError(
            "La tabla de seguimiento no puede ser "
            "la tabla de intentos SalesIQ"
        )

    return (
        BASE_URL[:-len(str(VIEW_ID))]
        + vista_id
        + "/rows"
    )


def consultar_sesion_analytics(sesion, form_session_id):
    """
    Consulta un formulario por su identificador.

    Solo lectura. No crea ni modifica registros.
    """

    import json

    if (
        not isinstance(form_session_id, str)
        or not PATRON_ID_FORMULARIO.fullmatch(form_session_id)
    ):
        raise ValueError("ID de formulario invalido")

    url_registros = obtener_url_analytics_formularios()
    url_lectura = url_registros[:-len("/rows")] + "/data"

    configuracion = {
        "responseFormat": "json",
        "keyValueFormat": True,
        "selectedColumns": [
            "ID Formulario",
            "Origen",
            "Estado",
            "ID Negocio",
        ],
        "criteria": (
            f'"ID Formulario" = \'{form_session_id}\''
        ),
    }

    respuesta = sesion.get(
        url_lectura,
        params={
            "CONFIG": json.dumps(configuracion)
        },
        timeout=20,
    )

    if respuesta.status_code != 200:
        raise RuntimeError(
            "No fue posible consultar Analytics"
        )

    datos = respuesta.json()

    if (
        not isinstance(datos, dict)
        or datos.get("status") not in (None, "success")
        or not isinstance(datos.get("data"), list)
    ):
        raise RuntimeError(
            "Respuesta de Analytics invalida"
        )

    filas = datos["data"]

    if len(filas) > 1:
        raise RuntimeError(
            "Se detectaron formularios duplicados"
        )

    if not filas:
        return None

    fila = filas[0]

    if (
        not isinstance(fila, dict)
        or fila.get("ID Formulario") != form_session_id
    ):
        raise RuntimeError(
            "Identificador de Analytics inconsistente"
        )

    return fila


def firmar_id_formulario(form_session_id, clave, origen):
    """Genera una firma HMAC para un ID de formulario."""

    import hashlib
    import hmac

    if (
        not isinstance(form_session_id, str)
        or not PATRON_ID_FORMULARIO.fullmatch(form_session_id)
    ):
        raise ValueError("ID de formulario invalido")

    if not isinstance(clave, str) or len(clave) < 32:
        raise ValueError("Clave de firma invalida")

    if origen not in ORIGENES_VALIDOS:
        raise ValueError("Origen invalido para firma")

    mensaje = f"selec-formulario-v2:{origen}:{form_session_id}"

    return hmac.new(
        clave.encode("utf-8"),
        mensaje.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def verificar_firma_formulario(form_session_id, firma, clave, origen):
    """Comprueba que el identificador tenga una firma valida."""

    import hmac

    if (
        not isinstance(firma, str)
        or not re.fullmatch(r"[0-9a-f]{64}", firma)
    ):
        return False

    try:
        firma_esperada = firmar_id_formulario(
            form_session_id,
            clave,
            origen,
        )
    except ValueError:
        return False

    return hmac.compare_digest(
        firma,
        firma_esperada,
    )


from threading import Lock

_BLOQUEO_REGISTROS_FORMULARIOS = Lock()


def _proteger_registro_inicio(funcion):
    """Evita inserciones simultaneas dentro del mismo proceso."""

    def ejecutar(*args, **kwargs):
        with _BLOQUEO_REGISTROS_FORMULARIOS:
            return funcion(*args, **kwargs)

    return ejecutar

@_proteger_registro_inicio
def registrar_inicio_analytics(
    sesion,
    form_session_id,
    origen,
    ahora=None,
    permitir_escritura=False,
):
    """
    Registra el inicio si no existe.

    Escritura deshabilitada por defecto.
    No reintenta POST ante respuestas ambiguas.
    """

    import json

    config = preparar_insercion_analytics(
        form_session_id, origen, ahora
    )

    if not permitir_escritura:
        return "SIMULACION"

    existente = consultar_sesion_analytics(
        sesion, form_session_id
    )

    if existente is not None:
        if existente.get("Origen") != origen:
            raise RuntimeError(
                "Conflicto de origen del formulario"
            )
        return "YA_EXISTE"

    respuesta = sesion.post(
        obtener_url_analytics_formularios(),
        params={"CONFIG": json.dumps(config)},
        timeout=20,
    )

    if respuesta.status_code not in (200, 201):
        raise RuntimeError(
            "Insercion no confirmada; no reintentar"
        )

    try:
        cuerpo = respuesta.json()
    except ValueError as error:
        raise RuntimeError(
            "Respuesta ambigua; no reintentar"
        ) from error

    datos = cuerpo.get("data") if isinstance(
        cuerpo, dict
    ) else None

    if (
        cuerpo.get("status") != "success"
        or not isinstance(datos, dict)
        or not isinstance(datos.get("addedColumns"), dict)
        or datos.get("invalidColumns") not in ({}, None)
    ):
        raise RuntimeError(
            "Analytics no confirmo insercion valida"
        )

    return "INSERTADO"


def registrar_confirmacion_analytics(
    sesion,
    form_session_id,
    deal_id,
    ahora=None,
    permitir_escritura=False,
):
    """
    Marca una sesion existente como COMPLETADA.

    Las escrituras estan deshabilitadas por defecto.
    No crea nuevas filas ni reintenta errores ambiguos.
    """

    import json

    config = preparar_actualizacion_analytics(
        form_session_id,
        deal_id,
        ahora,
    )

    if not permitir_escritura:
        return "SIMULACION"

    existente = consultar_sesion_analytics(
        sesion,
        form_session_id,
    )

    if existente is None:
        raise RuntimeError(
            "No existe inicio del formulario"
        )

    estado = str(existente.get("Estado") or "")
    negocio_actual = str(
        existente.get("ID Negocio") or ""
    ).strip()

    if estado == "COMPLETADA":
        if negocio_actual == deal_id:
            return "YA_COMPLETADA"

        raise RuntimeError(
            "Conflicto: formulario vinculado a otro negocio"
        )

    if estado not in ("INICIADA", "INCOMPLETA"):
        raise RuntimeError(
            "Estado no permitido para confirmacion"
        )


    respuesta = sesion.put(
        obtener_url_analytics_formularios(),
        params={"CONFIG": json.dumps(config)},
        timeout=20,
    )

    if respuesta.status_code != 200:
        raise RuntimeError(
            "Actualizacion no confirmada; no reintentar"
        )

    try:
        cuerpo = respuesta.json()
    except ValueError as error:
        raise RuntimeError(
            "Respuesta ambigua; no reintentar"
        ) from error

    datos = (
        cuerpo.get("data")
        if isinstance(cuerpo, dict)
        else None
    )

    if (
        cuerpo.get("status") != "success"
        or not isinstance(datos, dict)
        or type(datos.get("updatedRows")) is not int
        or datos["updatedRows"] != 1
        or datos.get("invalidColumns") not in ({}, None)
    ):
        raise RuntimeError(
            "No se confirmo exactamente una fila actualizada"
        )

    return "ACTUALIZADO"
