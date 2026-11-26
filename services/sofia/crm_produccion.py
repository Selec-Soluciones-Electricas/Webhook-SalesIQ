
import os
import requests

PROD_BASE = "https://www.zohoapis.com"
ORG_PRODUCCION = "706345205"


def obtener_token_produccion():
    """Autenticación exclusiva de Sofía con CRM Producción."""

    client_id = os.getenv("SOFIA_PROD_CLIENT_ID")
    client_secret = os.getenv("SOFIA_PROD_CLIENT_SECRET")
    refresh_token = os.getenv("SOFIA_PROD_REFRESH_TOKEN")

    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError("Credenciales de producción incompletas")

    respuesta = requests.post(
        "https://accounts.zoho.com/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
        allow_redirects=False,
    )

    if respuesta.status_code != 200:
        raise RuntimeError("Error de autenticación con Zoho")

    token = respuesta.json().get("access_token")

    if not isinstance(token, str) or not token:
        raise RuntimeError("Access token no disponible")

    verificacion = requests.get(
        PROD_BASE + "/crm/v8/org",
        headers={"Authorization": "Zoho-oauthtoken " + token},
        timeout=15,
        allow_redirects=False,
    )

    if verificacion.status_code != 200:
        raise RuntimeError("No se pudo verificar la organización")

    organizaciones = verificacion.json().get("org")

    if not isinstance(organizaciones, list) or len(organizaciones) != 1:
        raise RuntimeError("Respuesta de organización inválida")

    organizacion = organizaciones[0]

    if (
        not isinstance(organizacion, dict)
        or str(organizacion.get("zgid", "")).strip() != ORG_PRODUCCION
        or organizacion.get("type") == "sandbox"
    ):
        raise RuntimeError("Organización de producción no autorizada")

    return token


def obtener_conexion_produccion():
    """Entrega una conexión verificada, sin realizar escrituras."""

    return {
        "base": PROD_BASE,
        "obtener_token": obtener_token_produccion,
        "http_get": requests.get,
    }
