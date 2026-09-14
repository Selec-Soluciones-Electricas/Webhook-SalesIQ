import os
import requests


# =========================================================
# SALESIQ - UTILIDADES
# =========================================================

def get_visitor_id(payload: dict) -> str:
    """
    Obtiene un identificador único para la sesión del visitante.

    Se intenta utilizar, en este orden:
    1. active_conversation_id
    2. phone
    3. id
    4. visitor_id
    5. email
    6. anon como último recurso
    """

    visitor = payload.get("visitor") or {}

    return str(
        visitor.get("active_conversation_id")
        or visitor.get("phone")
        or visitor.get("id")
        or visitor.get("visitor_id")
        or visitor.get("email")
        or "anon"
    )


def extraer_mensaje(payload: dict) -> str:
    """
    Extrae el texto enviado por el visitante.

    Primero busca el mensaje dentro de:
        payload["message"]["text"]

    Si no existe, intenta utilizar:
        payload["question"]

    Si tampoco existe, devuelve una cadena vacía.
    """

    message = payload.get("message") or {}

    text = message.get("text")

    if text:
        return str(text).strip()

    question = payload.get("question")

    if question:
        return str(question).strip()

    return ""


def get_conversation_id(payload: dict) -> str:
    """
    Obtiene el ID real de la conversación (active_conversation_id),
    el mismo identificador que exige la API de SalesIQ para
    operaciones como el etiquetado de conversaciones.

    OJO: esto NO es lo mismo que el número visible "#282" en la UI
    (ese es 'visitid'). Para llamar a la API de tags se necesita
    específicamente active_conversation_id.
    """

    visitor = payload.get("visitor") or {}

    conversation_id = visitor.get("active_conversation_id")

    return str(conversation_id).strip() if conversation_id else ""


# =========================================================
# SALESIQ - ETIQUETADO DE CONVERSACIONES
# =========================================================

SALESIQ_API_BASE = "https://salesiq.zoho.com/api/v2"


def agregar_tag_conversacion(
    conversation_id: str,
    tag_id: str,
    access_token: str,
) -> bool:
    """
    Asocia un tag existente a una conversación de SalesIQ.

    Requiere:
    - Un access token de Zoho con scope SalesIQ.conversations.UPDATE
    - SALESIQ_SCREENNAME configurado como variable de entorno
      (el nombre de portal que aparece en la URL de SalesIQ,
      ej: https://salesiq.zoho.com/<screenname>/...)

    Devuelve True si el tag quedó asociado, False en cualquier
    otro caso (nunca lanza excepción hacia quien la llama, para
    no interrumpir la respuesta al visitante si esto falla).
    """

    screenname = os.environ.get("SALESIQ_SCREENNAME")

    if not screenname:
        print(
            "[agregar_tag_conversacion] "
            "Falta SALESIQ_SCREENNAME; se omite el etiquetado."
        )
        return False

    if not conversation_id:
        print(
            "[agregar_tag_conversacion] "
            "conversation_id vacío; se omite el etiquetado."
        )
        return False

    if not access_token:
        print(
            "[agregar_tag_conversacion] "
            "No hay access token disponible; se omite el etiquetado."
        )
        return False

    url = (
        f"{SALESIQ_API_BASE}/{screenname}"
        f"/conversations/{conversation_id}/tags"
    )

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }

    payload = {"ids": [str(tag_id)]}

    try:

        resp = requests.put(
            url,
            headers=headers,
            json=payload,
            timeout=10,
        )

        print(
            "[agregar_tag_conversacion] "
            f"status={resp.status_code} body={resp.text[:300]}"
        )

        return resp.status_code in (200, 201)

    except Exception as e:

        print(
            "[agregar_tag_conversacion] "
            f"ERROR llamando a la API de SalesIQ: {e}"
        )

        return False