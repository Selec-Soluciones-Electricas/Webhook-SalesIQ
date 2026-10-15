"""
Opción 3 del menú: "Contactar con agente".
La conversación la atiende el agente IA hasta que el cliente escribe "menú".
"""

import time

from conversation.state_machine import (
    build_reply,
    normalizar_texto,
    reply_menu_principal,
)

MAX_MENSAJES = 30  # historial que se envía al modelo
PALABRAS_SALIDA = {"menu", "volver", "salir", "inicio"}


def log(mensaje: str) -> None:
    # flush=True: el log aparece en Railway al instante
    print(f"[agente_ia] {mensaje}", flush=True)


def manejar_agente(session: dict, message_text: str) -> dict:

    data = session.get("data", {})
    chat = data.get("num_chat") or "sin-id"

    if normalizar_texto(message_text) in PALABRAS_SALIDA:
        log(f"chat={chat} el cliente volvió al menú")
        session["state"] = "menu_principal"
        session.pop("agente", None)
        return reply_menu_principal()

    from agente.nucleo import responder  # import diferido: el bot arranca aunque falte la API key

    estado = session.setdefault("agente", {"historial": [], "registros": {}})
    historial = estado["historial"]
    historial.append({"role": "user", "content": message_text or "(mensaje sin texto)"})

    # "registros" es el mismo dict de la sesión: así se recuerda entre mensajes
    contexto = {
        "owner_asignado": data.get("owner_asignado"),
        "conversation_id": data.get("conversation_id"),
        "num_chat": data.get("num_chat"),
        "registros": estado["registros"],
    }

    inicio = time.time()

    try:
        texto, acciones = responder(historial, "whatsapp", contexto)
    except Exception as e:
        log(f"chat={chat} ERROR tras {round(time.time() - inicio, 1)}s: {e}")
        historial.pop()
        return build_reply(
            "Disculpe, tuve un problema para procesar su mensaje. "
            "Intente nuevamente o escriba \"menú\" para volver a las opciones."
        )

    segundos = round(time.time() - inicio, 1)

    log(
        f"chat={chat} {segundos}s "
        f"cliente={(message_text or '')[:100]!r} "
        f"-> sofia={texto[:200]!r}"
    )

    for a in acciones:
        log(f"chat={chat} {a['herramienta']} -> {a['resultado']}")

    historial.append({"role": "assistant", "content": texto})

    # Recortar de a pares para que el historial siempre empiece con "user"
    while len(historial) > MAX_MENSAJES:
        del historial[:2]

    return build_reply(texto)