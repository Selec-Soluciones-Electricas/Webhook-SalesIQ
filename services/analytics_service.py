import os
import time
import json

import requests


ACCOUNTS_BASE = "https://accounts.zoho.com"
ANALYTICS_API_BASE = "https://analyticsapi.zoho.com/restapi/v2"


# =========================================================
# CACHE DEL ACCESS TOKEN - ZOHO ANALYTICS (independiente de
# los de CRM y SalesIQ; usa sus propias credenciales)
# =========================================================

analytics_access_token_cache = {
    "token": None,
    "expires_at": 0.0,
}


def get_analytics_access_token() -> str:
    """
    Obtiene el access token de Zoho Analytics usando su propio
    refresh token.

    Variables de entorno requeridas:
        ANALYTICS_CLIENT_ID
        ANALYTICS_CLIENT_SECRET
        ANALYTICS_REFRESH_TOKEN
        (scope: ZohoAnalytics.data.create, ZohoAnalytics.data.read)
    """

    now = time.time()

    if (
        analytics_access_token_cache["token"]
        and analytics_access_token_cache["expires_at"] - 60 > now
    ):
        return analytics_access_token_cache["token"]

    client_id = os.environ.get("ANALYTICS_CLIENT_ID")
    client_secret = os.environ.get("ANALYTICS_CLIENT_SECRET")
    refresh_token = os.environ.get("ANALYTICS_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        print(
            "[get_analytics_access_token] ERROR: faltan "
            "ANALYTICS_CLIENT_ID / ANALYTICS_CLIENT_SECRET / "
            "ANALYTICS_REFRESH_TOKEN. Se omite el registro en "
            "Analytics."
        )
        return None

    try:

        resp = requests.post(
            f"{ACCOUNTS_BASE}/oauth/v2/token",
            params={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )

        if resp.status_code != 200:
            print(
                "[get_analytics_access_token] "
                f"ERROR {resp.status_code}: {resp.text[:300]}"
            )
            return None

        data = resp.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))

        if not token:
            print(
                "[get_analytics_access_token] "
                "ERROR: respuesta sin access_token."
            )
            return None

        analytics_access_token_cache["token"] = token
        analytics_access_token_cache["expires_at"] = (
            time.time() + expires_in
        )

        return token

    except Exception as e:

        print(
            "[get_analytics_access_token] "
            f"ERROR llamando a Zoho Accounts: {e}"
        )

        return None


def agregar_fila_analytics(
    columnas: dict,
    date_format: str = None,
) -> bool:
    """
    Inserta una fila en la tabla de Zoho Analytics configurada
    por ANALYTICS_WORKSPACE_ID / ANALYTICS_VIEW_ID.

    columnas: dict con {"NombreColumna": "valor", ...} — los
    nombres deben coincidir EXACTO con los nombres de columna
    de la tabla en Analytics (mayúsculas/espacios incluidos).

    date_format: si la fila incluye una columna de tipo Fecha,
    pasa aquí el patrón exacto usado al formatear ese valor
    (ej. "dd-MMM-yyyy HH:mm:ss"), para que Analytics no intente
    adivinarlo — el auto-detect puede fallar según la config
    regional de la cuenta.

    Nunca lanza excepción hacia quien la llama: si algo falla,
    imprime el detalle y devuelve False, para no interrumpir la
    respuesta al visitante por un problema de reporting.
    """

    org_id = os.environ.get("ANALYTICS_ORG_ID")
    workspace_id = os.environ.get("ANALYTICS_WORKSPACE_ID")
    view_id = os.environ.get("ANALYTICS_VIEW_ID")

    if not org_id or not workspace_id or not view_id:
        print(
            "[agregar_fila_analytics] ERROR: faltan "
            "ANALYTICS_ORG_ID / ANALYTICS_WORKSPACE_ID / "
            "ANALYTICS_VIEW_ID. Se omite el registro."
        )
        return False

    access_token = get_analytics_access_token()

    if not access_token:
        return False

    url = (
        f"{ANALYTICS_API_BASE}/workspaces/{workspace_id}"
        f"/views/{view_id}/rows"
    )

    headers = {
        "ZANALYTICS-ORGID": org_id,
        "Authorization": f"Zoho-oauthtoken {access_token}",
    }

    config = {"columns": columnas}

    if date_format:
        config["dateFormat"] = date_format

    try:

        resp = requests.post(
            url,
            headers=headers,
            params={"CONFIG": json.dumps(config)},
            timeout=10,
        )

        print(
            "[agregar_fila_analytics] "
            f"status={resp.status_code} body={resp.text[:300]}"
        )

        return resp.status_code in (200, 201)

    except Exception as e:

        print(
            "[agregar_fila_analytics] "
            f"ERROR llamando a la API de Analytics: {e}"
        )

        return False

def existe_attempt_id_analytics(attempt_id: str):
    """
    Comprueba si un Attempt ID ya existe en Zoho Analytics.

    Devuelve:
        True  -> ya existe.
        False -> la consulta funcionó y no existe.
        None  -> no fue posible comprobarlo.
    """

    if not attempt_id:
        return None

    org_id = os.environ.get("ANALYTICS_ORG_ID")
    workspace_id = os.environ.get("ANALYTICS_WORKSPACE_ID")
    view_id = os.environ.get("ANALYTICS_VIEW_ID")

    if not org_id or not workspace_id or not view_id:
        print(
            "[existe_attempt_id_analytics] ERROR: faltan "
            "ANALYTICS_ORG_ID / ANALYTICS_WORKSPACE_ID / "
            "ANALYTICS_VIEW_ID."
        )
        return None

    access_token = get_analytics_access_token()

    if not access_token:
        return None

    url = (
        f"{ANALYTICS_API_BASE}/workspaces/{workspace_id}"
        f"/views/{view_id}/data"
    )

    headers = {
        "ZANALYTICS-ORGID": org_id,
        "Authorization": f"Zoho-oauthtoken {access_token}",
    }

    attempt_id_seguro = str(attempt_id).replace(
        "'",
        "''",
    )

    config = {
        "responseFormat": "json",
        "criteria": (
            f"\"Attempt ID\"='{attempt_id_seguro}'"
        ),
        "selectedColumns": [
            "Attempt ID"
        ],
        "keyValueFormat": True,
    }

    try:

        resp = requests.get(
            url,
            headers=headers,
            params={
                "CONFIG": json.dumps(config)
            },
            timeout=10,
        )

        if resp.status_code != 200:
            print(
                "[existe_attempt_id_analytics] "
                f"ERROR {resp.status_code}: "
                f"{resp.text[:300]}"
            )
            return None

        data = resp.json()

        filas = data.get("data") or []

        return len(filas) > 0

    except Exception as e:

        print(
            "[existe_attempt_id_analytics] "
            f"ERROR llamando a Analytics: {e}"
        )

        return None