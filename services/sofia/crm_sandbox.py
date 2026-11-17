
import os
import requests


SANDBOX_BASE = "https://sandbox.zohoapis.com"
OAUTH_URL = "https://accounts.zoho.com/oauth/v2/token"


def obtener_token_sandbox():
    """Obtiene un token exclusivo del Sandbox de Sofía."""

    client_id = os.getenv("SOFIA_SANDBOX_CLIENT_ID")
    client_secret = os.getenv("SOFIA_SANDBOX_CLIENT_SECRET")
    refresh_token = os.getenv("SOFIA_SANDBOX_REFRESH_TOKEN")

    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError(
            "Credenciales del Sandbox no configuradas"
        )

    respuesta = requests.post(
        OAUTH_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )

    if respuesta.status_code != 200:
        raise RuntimeError(
            "No se pudo autenticar con Zoho Sandbox"
        )

    datos = respuesta.json()

    token = datos.get("access_token")

    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("Token de Sandbox invalido")

    # Verificar el entorno real del token.
    # Esta consulta solo lee informacion de la organizacion.
    verificacion = requests.get(
        "https://www.zohoapis.com/crm/v8/org",
        headers={
            "Authorization": f"Zoho-oauthtoken {token}"
        },
        timeout=15,
    )

    if verificacion.status_code != 200:
        raise RuntimeError(
            "No se pudo verificar la organizacion"
        )

    informacion = verificacion.json()
    organizaciones = informacion.get("org")

    if (
        not isinstance(organizaciones, list)
        or len(organizaciones) != 1
        or not isinstance(organizaciones[0], dict)
    ):
        raise RuntimeError(
            "Organizacion de Sofia no identificada"
        )

    organizacion = organizaciones[0]

    tipo_correcto = (
        organizacion.get("type") == "sandbox"
    )

    dominio_correcto = (
        organizacion.get("domain_name") == "sofiaretell"
    )

    zgid_correcto = (
        str(organizacion.get("zgid", "")).strip()
        == "868044837"
    )

    if not (
        tipo_correcto
        and dominio_correcto
        and zgid_correcto
    ):
        raise RuntimeError(
            "El token no pertenece al Sandbox de Sofia"
        )

    return token


def obtener_conexion_sandbox():
    """Entrega la conexion aislada para consultas de Sofia."""

    return {
        "base": SANDBOX_BASE,
        "obtener_token": obtener_token_sandbox,
        "http_get": requests.get,
    }
