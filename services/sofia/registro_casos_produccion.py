
import os
import requests

from services.sofia.crm_produccion import (
    obtener_conexion_produccion,
)
from services.sofia.marcas_prueba import (
    marcar_registro_prueba,
)

BASE = "https://www.zohoapis.com/crm/v8"


def registrar_caso_prueba_produccion(campos):
    """Crea un Caso de prueba autorizado, sin tocar otros registros."""

    # Desactivado por defecto.
    if os.getenv(
        "SOFIA_PROD_CASES_WRITES_ENABLED", "false"
    ).strip().lower() != "true":
        return {"estado": "desactivado"}

    if not isinstance(campos, dict):
        return {"estado": "bloqueado", "motivo": "datos_invalidos"}

    call_id = campos.get("ID_de_llamada_Retell")
    autorizado = os.getenv(
        "SOFIA_PROD_CASES_ALLOWED_CALL_ID", ""
    ).strip()

    # Solo una llamada expresamente autorizada.
    if not autorizado or call_id != autorizado:
        return {"estado": "bloqueado", "motivo": "no_autorizado"}

    try:
        registro = marcar_registro_prueba("Cases", campos)
        conexion = obtener_conexion_produccion()
        token = conexion["obtener_token"]()

        headers = {
            "Authorization": "Zoho-oauthtoken " + token
        }

        # Comprobar los Casos existentes antes de escribir.
        encontrados = []

        for pagina in range(1, 21):
            respuesta = conexion["http_get"](
                BASE + "/Cases",
                headers=headers,
                params={
                    "fields": "id,ID_de_llamada_Retell",
                    "page": pagina,
                    "per_page": 200,
                },
                timeout=20,
                allow_redirects=False,
            )

            if respuesta.status_code == 204 and pagina == 1:
                break

            if respuesta.status_code != 200:
                return {
                    "estado": "bloqueado",
                    "motivo": "consulta_inconclusa",
                }

            cuerpo = respuesta.json()
            filas = cuerpo.get("data")
            info = cuerpo.get("info")

            if (
                not isinstance(filas, list)
                or not isinstance(info, dict)
                or type(info.get("more_records")) is not bool
            ):
                return {
                    "estado": "bloqueado",
                    "motivo": "listado_invalido",
                }

            for fila in filas:
                if not isinstance(fila, dict):
                    return {"estado": "bloqueado"}

                if fila.get("ID_de_llamada_Retell") == call_id:
                    encontrados.append(fila.get("id"))

            if not info["more_records"]:
                break
        else:
            return {
                "estado": "bloqueado",
                "motivo": "listado_incompleto",
            }

        if len(encontrados) == 1 and encontrados[0]:
            return {
                "estado": "ya_registrado",
                "case_id": encontrados[0],
            }

        if encontrados:
            return {
                "estado": "bloqueado",
                "motivo": "duplicados",
            }

        # Escritura individual, sin reintentos automáticos.
        respuesta = requests.post(
            BASE + "/Cases",
            headers={
                **headers,
                "Content-Type": "application/json",
            },
            json={"data": [registro], "trigger": []},
            timeout=20,
            allow_redirects=False,
        )

        cuerpo = respuesta.json()
        filas = cuerpo.get("data", [])
        fila = filas[0] if len(filas) == 1 else {}
        identificador = str(
            (fila.get("details") or {}).get("id") or ""
        )

        if (
            respuesta.status_code in (200, 201)
            and fila.get("code") == "SUCCESS"
            and fila.get("status") == "success"
            and identificador.isascii()
            and identificador.isdecimal()
        ):
            return {
                "estado": "creado",
                "case_id": identificador,
            }

        return {
            "estado": "resultado_incierto",
            "motivo": "creacion_no_confirmada",
        }

    except Exception:
        return {
            "estado": "resultado_incierto",
            "motivo": "error_procesamiento",
        }


def procesar_caso_prueba_desde_clasificacion(clasificacion):
    """
    Prepara un Caso de Sofia y lo entrega al escritor
    protegido de Zoho CRM Produccion.
    """

    from services.retell_casos import (
        preparar_borrador_caso_consulta,
    )

    if not isinstance(clasificacion, dict):
        return {
            "estado": "bloqueado",
            "motivo": "clasificacion_invalida",
        }

    if clasificacion.get("estado") != "candidata_caso":
        return {
            "estado": "bloqueado",
            "motivo": "llamada_no_elegible",
        }

    tipo = clasificacion.get("tipo_solicitud")

    if tipo not in ("postventa", "consulta"):
        return {
            "estado": "bloqueado",
            "motivo": "tipo_invalido",
        }

    contacto = clasificacion.get("contacto") or {}

    if not isinstance(contacto, dict):
        return {
            "estado": "bloqueado",
            "motivo": "contacto_invalido",
        }

    telefono = str(
        contacto.get("telefono_cliente") or ""
    ).strip()

    correo = str(
        contacto.get("email_cliente") or ""
    ).strip()

    if not telefono and not correo:
        return {
            "estado": "bloqueado",
            "motivo": "sin_medio_contacto",
        }

    try:
        borrador = preparar_borrador_caso_consulta(
            clasificacion
        )

        if borrador.get("tipo_solicitud") != tipo:
            raise ValueError("Tipo inconsistente")

        campos = borrador["campos_propuestos"]

        if campos.get("Case_Origin") != "Teléfono":
            raise ValueError("Origen de Caso invalido")

    except (ValueError, TypeError, KeyError):
        return {
            "estado": "bloqueado",
            "motivo": "preparacion_invalida",
        }

    return registrar_caso_prueba_produccion(campos)
