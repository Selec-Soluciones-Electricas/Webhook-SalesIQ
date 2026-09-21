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


def listar_conversaciones_cerradas(
    screenname: str,
    access_token: str,
    desde_ms: int,
    hasta_ms: int,
) -> list:
    """
    Lista conversaciones con status='closed' que hayan sido
    actualizadas entre desde_ms y hasta_ms (epoch en
    milisegundos).

    Se usa la hora de actualización y no la hora de inicio,
    porque una conversación de WhatsApp puede haber comenzado
    hace mucho tiempo y cerrarse recién ahora.

    Trae el campo 'visitor' para poder filtrar por canal
    (WhatsApp) del lado del cliente.

    Pagina automáticamente hasta agotar los resultados.
    """

    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    conversaciones = []
    page = 1

    while True:

        resp = requests.get(
            f"{SALESIQ_API_BASE}/{screenname}/conversations",
            headers=headers,
            params={
                "status": "closed",
                "updated_from_time": desde_ms,
                "updated_till_time": hasta_ms,
                "sort_by": "updated_time",
                "limit": 99,
                "page": page,
                "fields": "visitor,status",
            },
            timeout=15,
        )

        if resp.status_code != 200:
            print(
                "[listar_conversaciones_cerradas] "
                f"status={resp.status_code} body={resp.text[:200]}"
            )
            break

        datos = resp.json().get("data") or []

        if not datos:
            break

        conversaciones.extend(datos)

        if len(datos) < 99:
            break

        page += 1

    return conversaciones


def obtener_tags_actuales(
    conversation_id: str,
    screenname: str,
    access_token: str,
) -> list:
    """
    Devuelve la lista de IDs de tags ya asociados a una
    conversación (vacía si no tiene ninguno o si falla la
    consulta — en ese caso se prefiere seguir de largo y
    procesar el chat antes que saltarlo por error).
    """

    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    try:

        resp = requests.get(
            f"{SALESIQ_API_BASE}/{screenname}"
            f"/conversations/{conversation_id}",
            headers=headers,
            timeout=15,
        )

        if resp.status_code != 200:
            return []

        data = resp.json().get("data") or {}

        tags = data.get("tags") or []

        return [str(t.get("id")) for t in tags if t.get("id")]

    except Exception as e:
        print(f"[obtener_tags_actuales] ERROR: {e}")
        return []


def obtener_mensajes_conversacion(
    conversation_id: str,
    screenname: str,
    access_token: str,
) -> list:
    """
    Descarga los mensajes de una conversación conservando
    el orden, la hora y el remitente de cada mensaje.

    Esto permitirá analizar varios intentos de cotización
    dentro de una misma conversación.
    """

    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    mensajes_acumulados = []
    ids_vistos = set()
    from_time = None

    for _ in range(20):

        params = {"limit": 100}

        if from_time is not None:
            params["from_time"] = from_time

        try:

            resp = requests.get(
                f"{SALESIQ_API_BASE}/{screenname}"
                f"/conversations/{conversation_id}/messages",
                headers=headers,
                params=params,
                timeout=15,
            )

        except Exception as e:

            print(
                "[obtener_mensajes_conversacion] "
                f"ERROR llamando a SalesIQ: {e}"
            )

            break

        if resp.status_code != 200:

            print(
                "[obtener_mensajes_conversacion] "
                f"status={resp.status_code} body={resp.text[:200]}"
            )

            break

        data = resp.json()

        mensajes = data.get("data") or []

        if not mensajes:
            break

        tiempos_lote = []

        for m in mensajes:

            message_id = str(m.get("id") or "")

            # Evitamos agregar dos veces el mismo mensaje
            # cuando existe paginación.
            if message_id and message_id in ids_vistos:
                continue

            if message_id:
                ids_vistos.add(message_id)

            contenido = m.get("message") or {}

            texto = contenido.get("text")

            # Algunos eventos pueden guardar el texto
            # dentro de "message".
            if not texto and isinstance(
                contenido.get("message"), str
            ):
                texto = contenido.get("message")

            try:

                time_ms = int(m.get("time"))
                tiempos_lote.append(time_ms)

            except (TypeError, ValueError):

                time_ms = None

            mensajes_acumulados.append(
                {
                    "id": message_id,
                    "sequence_id": m.get("sequence_id"),
                    "time_ms": time_ms,
                    "type": m.get("type"),
                    "sender": m.get("sender") or {},
                    "text": str(texto or ""),
                }
            )

        if not data.get("more_data_available"):
            break

        if not tiempos_lote:
            break

        siguiente_from_time = max(tiempos_lote) + 1

        if (
            from_time is not None
            and siguiente_from_time <= from_time
        ):
            break

        from_time = siguiente_from_time

    # Nos aseguramos de que todos los mensajes estén
    # ordenados cronológicamente.
    mensajes_acumulados.sort(
        key=lambda m: (
            m.get("time_ms")
            if m.get("time_ms") is not None
            else 0,
            str(m.get("sequence_id") or ""),
        )
    )

    return mensajes_acumulados


def obtener_transcripcion_completa(
    conversation_id: str,
    screenname: str,
    access_token: str,
) -> str:
    """
    Mantiene el funcionamiento antiguo para las partes
    del sistema que todavía necesitan recibir toda la
    conversación como un solo texto.
    """

    mensajes = obtener_mensajes_conversacion(
        conversation_id,
        screenname,
        access_token,
    )

    return "\n".join(
        m.get("text") or ""
        for m in mensajes
        if m.get("text")
    )