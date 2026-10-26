
import re

from services import zoho_service


def buscar_negocio_por_call_id(call_id):
    """
    Busca en Zoho CRM un negocio asociado a una
    llamada de Retell.

    Estados:
    - encontrado: ya existe el negocio.
    - no_encontrado: Zoho confirma que no existe.
    - error: no se pudo comprobar con seguridad.
    """

    error = {
        "estado": "error",
        "negocio_id": None,
    }

    if not isinstance(call_id, str):
        return error

    call_id = call_id.strip()

    # Evitar identificadores invalidos en la consulta
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", call_id):
        return error

    try:
        token = zoho_service.get_access_token()

        if not token:
            return error

        respuesta = zoho_service.requests.get(
            f"{zoho_service.CRM_BASE}/Deals/search",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}"
            },
            params={
                "criteria": (
                    f"(Retell_Call_ID:equals:{call_id})"
                )
            },
            timeout=10,
        )

        # Zoho confirma que no encontro el negocio
        if respuesta.status_code == 204:
            return {
                "estado": "no_encontrado",
                "negocio_id": None,
            }

        # Cualquier error HTTP bloquea el proceso
        if respuesta.status_code != 200:
            return error

        contenido = respuesta.json()

        if not isinstance(contenido, dict):
            return error

        negocios = contenido.get("data")

        # Una respuesta inconsistente requiere revision
        if not isinstance(negocios, list):
            return error

        if len(negocios) != 1:
            return error

        negocio = negocios[0]

        if not isinstance(negocio, dict):
            return error

        # Confirmar coincidencia exacta del Call ID
        if negocio.get("Retell_Call_ID") != call_id:
            return error

        negocio_id = str(negocio.get("id") or "").strip()

        if not negocio_id:
            return error

        return {
            "estado": "encontrado",
            "negocio_id": negocio_id,
        }

    except Exception as e:
        print(
            "[RETELL] Error buscando negocio:",
            type(e).__name__,
        )
        return error


def buscar_negocios_por_call_ids(call_ids):
    """
    Busca varios Retell_Call_ID en una sola consulta.

    Solo lectura. No crea ni modifica negocios.

    Estados generales:
    - ok: consulta completada.
    - error: resultado no confiable.

    Cada resultado individual contiene:
    - encontrado
    - no_encontrado
    """

    def fallo():
        return {
            "estado": "error",
            "resultados": {},
        }

    if not isinstance(call_ids, list):
        return fallo()

    if len(call_ids) > 30:
        return fallo()

    if not call_ids:
        return {
            "estado": "ok",
            "resultados": {},
        }

    ids = []

    for call_id in call_ids:

        if not isinstance(call_id, str):
            return fallo()

        call_id = call_id.strip()

        if not re.fullmatch(
            r"[A-Za-z0-9_-]{1,255}",
            call_id,
        ):
            return fallo()

        ids.append(call_id)

    # Evitar identificadores repetidos
    if len(set(ids)) != len(ids):
        return fallo()

    try:
        token = zoho_service.get_access_token()

        if not token:
            return fallo()

        criteria = (
            "(Retell_Call_ID:in:"
            + ",".join(ids)
            + ")"
        )

        respuesta = zoho_service.requests.get(
            f"{zoho_service.CRM_BASE}/Deals/search",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}"
            },
            params={
                "criteria": criteria,
                "per_page": 200,
            },
            timeout=10,
        )

        if respuesta.status_code == 204:
            negocios = []

        elif respuesta.status_code == 200:
            contenido = respuesta.json()

            if not isinstance(contenido, dict):
                return fallo()

            negocios = contenido.get("data")
            info = contenido.get("info")

            if not isinstance(negocios, list):
                return fallo()

            # No aceptar resultados paginados incompletos
            if not isinstance(info, dict):
                return fallo()

            if info.get("more_records") is not False:
                return fallo()

        else:
            return fallo()

        resultados = {
            call_id: {
                "estado": "no_encontrado",
                "negocio_id": None,
            }
            for call_id in ids
        }

        encontrados = set()

        for negocio in negocios:

            if not isinstance(negocio, dict):
                return fallo()

            call_id = negocio.get("Retell_Call_ID")
            negocio_id = negocio.get("id")

            # Exigir coincidencia exacta
            if call_id not in resultados:
                return fallo()

            if call_id in encontrados:
                return fallo()

            if not isinstance(negocio_id, str):
                return fallo()

            negocio_id = negocio_id.strip()

            if not negocio_id:
                return fallo()

            encontrados.add(call_id)

            resultados[call_id] = {
                "estado": "encontrado",
                "negocio_id": negocio_id,
            }

        return {
            "estado": "ok",
            "resultados": resultados,
        }

    except Exception as error:
        print(
            "[RETELL] Error en busqueda multiple:",
            type(error).__name__,
        )

        return fallo()
