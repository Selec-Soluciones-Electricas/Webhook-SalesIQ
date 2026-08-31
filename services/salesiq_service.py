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

