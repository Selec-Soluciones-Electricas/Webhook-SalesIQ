import json
from pathlib import Path

from anthropic import Anthropic

from .herramientas import HERRAMIENTAS, ejecutar

# Timeout corto: SalesIQ espera la respuesta del webhook
client = Anthropic(timeout=25, max_retries=1)  # lee ANTHROPIC_API_KEY

BASE = Path(__file__).parent
INSTRUCCIONES = (BASE / "prompt.md").read_text(encoding="utf-8")
CONOCIMIENTO = (BASE / "conocimiento.md").read_text(encoding="utf-8")

MODELOS = {
    "telefono": "claude-haiku-4-5",
    "whatsapp": "claude-haiku-4-5",
    "correo": "claude-sonnet-5-5",
}
ESTILO = {
    "whatsapp": "Canal actual: WhatsApp. Mensajes cortos, máximo 3 o 4 líneas, sin formato markdown.",
    "correo": "Canal actual: correo electrónico. Incluye saludo, cuerpo claro y firma 'Equipo SELEC'.",
    "telefono": "Canal actual: llamada telefónica. Máximo 2 frases por turno, sin listas ni símbolos.",
}

RESPUESTA_FALLO = "Disculpe, no pude completar su solicitud. Un ejecutivo lo contactará a la brevedad."


def responder(historial: list[dict], canal: str, contexto: dict | None = None) -> tuple[str, list[dict]]:
    """
    historial: [{"role": "user" | "assistant", "content": "..."}], debe terminar en "user".
    contexto: datos de la sesión (owner_asignado, conversation_id, num_chat, registros).
    Devuelve (texto_respuesta, acciones_ejecutadas).
    """
    contexto = contexto if contexto is not None else {}
    system = [
        {"type": "text", "text": f"{INSTRUCCIONES}\n\n{CONOCIMIENTO}", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": ESTILO[canal]},
    ]
    mensajes = list(historial)
    acciones = []

    for _ in range(5):  # máximo 5 vueltas modelo -> herramienta -> modelo
        respuesta = client.messages.create(
            model=MODELOS[canal],
            max_tokens=800,
            system=system,
            tools=HERRAMIENTAS,
            messages=mensajes,
        )

        usos = [b for b in respuesta.content if b.type == "tool_use"]
        if respuesta.stop_reason != "tool_use" or not usos:
            texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
            return texto or RESPUESTA_FALLO, acciones

        resultados = []

        for uso in usos:

            resultado = ejecutar(
                uso.name,
                uso.input,
                canal,
                contexto,
            )

            acciones.append({
                "herramienta": uso.name,
                "entrada": uso.input,
                "resultado": resultado,
            })

            # =================================================
            # DERIVACIONES A FORMULARIOS
            # =================================================
            # Si la plantilla fue enviada correctamente,
            # terminamos aquí. No necesitamos volver a pedirle
            # otra respuesta al modelo.
            # =================================================

            if (
                resultado.get("ok")
                and uso.name == "derivar_cotizacion"
            ):
                return (
                    "Para continuar con su solicitud de cotización, "
                    "complete el formulario que le acabamos de enviar.",
                    acciones,
                )

            if (
                resultado.get("ok")
                and uso.name == "derivar_postventa"
            ):
                return (
                    "Para continuar con su solicitud de servicio postventa, "
                    "complete el formulario que le acabamos de enviar.",
                    acciones,
                )

            resultados.append({
                "type": "tool_result",
                "tool_use_id": uso.id,
                "content": json.dumps(
                    resultado,
                    ensure_ascii=False,
                ),
            })

        mensajes += [
            {"role": "assistant", "content": respuesta.content},
            {"role": "user", "content": resultados},
        ]

    return RESPUESTA_FALLO, acciones