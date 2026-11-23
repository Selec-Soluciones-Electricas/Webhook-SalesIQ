
import os
import requests
import hashlib
import threading
import time


SANDBOX_BASE = "https://sandbox.zohoapis.com"
OAUTH_URL = "https://accounts.zoho.com/oauth/v2/token"

# Cache de proceso: evitar exceder el limite de renovaciones Zoho.
# En un nuevo proceso, un token nuevo se verifica nuevamente por /org.
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE = {"key": None, "token": None, "hasta": 0.0}


def obtener_token_sandbox():
    """Obtiene un token exclusivo del Sandbox de Sofía."""

    client_id = os.getenv("SOFIA_SANDBOX_CLIENT_ID")
    client_secret = os.getenv("SOFIA_SANDBOX_CLIENT_SECRET")
    refresh_token = os.getenv("SOFIA_SANDBOX_REFRESH_TOKEN")

    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError(
            "Credenciales del Sandbox no configuradas"
        )

    # Verificar las credenciales y el entorno una vez por token activo.
    clave = hashlib.sha256(
        "\0".join((client_id, client_secret, refresh_token)).encode()
    ).digest()

    with _TOKEN_LOCK:
        if (
            _TOKEN_CACHE["key"] == clave
            and isinstance(_TOKEN_CACHE["token"], str)
            and time.monotonic() < _TOKEN_CACHE["hasta"]
        ):
            return _TOKEN_CACHE["token"]

        return _renovar_y_verificar(clave, client_id, client_secret, refresh_token)


def _renovar_y_verificar(clave, client_id, client_secret, refresh_token):
    """Se llama con el bloqueo de cache adquirido."""
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

    # Margen de seguridad para no utilizar tokens cercanos a caducar.
    try:
        segundos = int(datos.get("expires_in", 3600))
    except (TypeError, ValueError):
        segundos = 3600
    duracion = max(30, min(segundos - 120, 3000))
    _TOKEN_CACHE.update({
        "key": clave,
        "token": token,
        "hasta": time.monotonic() + duracion,
    })
    return token


def obtener_conexion_sandbox():
    """Entrega la conexion aislada para consultas de Sofia."""

    return {
        "base": SANDBOX_BASE,
        "obtener_token": obtener_token_sandbox,
        "http_get": requests.get,
    }
