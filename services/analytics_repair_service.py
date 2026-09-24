import os
import json

import requests

from services.analytics_service import (
    ANALYTICS_API_BASE,
    get_analytics_access_token,
)


# =========================================================
# LECTURA Y ACTUALIZACIÓN DE FILAS EN ZOHO ANALYTICS
# =========================================================
# Requiere que ANALYTICS_REFRESH_TOKEN tenga los scopes:
#   ZohoAnalytics.data.create
#   ZohoAnalytics.data.read
#   ZohoAnalytics.data.update
# =========================================================


def _config_base():

    org_id = os.environ.get("ANALYTICS_ORG_ID")
    workspace_id = os.environ.get("ANALYTICS_WORKSPACE_ID")
    view_id = os.environ.get("ANALYTICS_VIEW_ID")

    if not org_id or not workspace_id or not view_id:
        print(
            "[analytics_repair] ERROR: faltan ANALYTICS_ORG_ID / "
            "ANALYTICS_WORKSPACE_ID / ANALYTICS_VIEW_ID."
        )
        return None

    token = get_analytics_access_token()

    if not token:
        return None

    url = (
        f"{ANALYTICS_API_BASE}/workspaces/{workspace_id}"
        f"/views/{view_id}"
    )

    headers = {
        "ZANALYTICS-ORGID": org_id,
        "Authorization": f"Zoho-oauthtoken {token}",
    }

    return url, headers


# Último error de actualización, para devolverlo en el
# diagnóstico sin revisar los logs.
ultimo_error_analytics = {"detalle": None}


# Funcion desarrollada con el fin de leer filas de la tabla Registro_CRM_WhatsApp que cumplan un criterio.
def listar_filas_analytics(criteria: str = None) -> list:
    """
    Devuelve una lista de dicts {columna: valor}, o None si la
    consulta falla (para distinguir 'sin filas' de 'error').
    """

    base = _config_base()

    if not base:
        return None

    url, headers = base

    config = {"responseFormat": "json"}

    if criteria:
        config["criteria"] = criteria

    try:

        resp = requests.get(
            f"{url}/data",
            headers=headers,
            params={"CONFIG": json.dumps(config)},
            timeout=30,
        )

    except Exception as e:
        print(f"[listar_filas_analytics] ERROR: {e}")
        return None

    if resp.status_code != 200:
        print(
            "[listar_filas_analytics] "
            f"status={resp.status_code} body={resp.text[:300]}"
        )
        return None

    try:
        cuerpo = resp.json()
    except ValueError:
        print(
            "[listar_filas_analytics] Respuesta no es JSON: "
            f"{resp.text[:300]}"
        )
        return None

    # Formato habitual de la API v2: {"data": [{...}, ...]}
    if isinstance(cuerpo.get("data"), list):
        return cuerpo["data"]

    # Formato alternativo: column_order + rows
    resultado = (cuerpo.get("response") or {}).get("result") or {}
    columnas = resultado.get("column_order") or []
    filas = resultado.get("rows") or []

    return [dict(zip(columnas, fila)) for fila in filas]


# Funcion desarrollada con el fin de actualizar columnas de las filas que cumplan un criterio en la tabla de Analytics.
def actualizar_filas_analytics(columnas: dict, criteria: str) -> bool:

    if not criteria:
        # Nunca actualizar sin criterio: modificaría toda la tabla.
        print("[actualizar_filas_analytics] ERROR: criteria vacío.")
        return False

    base = _config_base()

    ultimo_error_analytics["detalle"] = None

    if not base:
        ultimo_error_analytics["detalle"] = (
            "No se pudo obtener token/config de Analytics."
        )
        return False

    url, headers = base

    config = {
        "columns": columnas,
        "criteria": criteria,
    }

    try:

        resp = requests.put(
            f"{url}/rows",
            headers=headers,
            params={"CONFIG": json.dumps(config)},
            timeout=15,
        )

    except Exception as e:
        ultimo_error_analytics["detalle"] = f"Excepción: {e}"
        print(f"[actualizar_filas_analytics] ERROR: {e}")
        return False

    print(
        "[actualizar_filas_analytics] "
        f"status={resp.status_code} body={resp.text[:300]}"
    )

    if resp.status_code != 200:
        ultimo_error_analytics["detalle"] = (
            f"status={resp.status_code} body={resp.text[:300]} "
            f"criteria={criteria}"
        )
        return False

    return True