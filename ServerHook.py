# ServerHook.py
# Webhook básico para Zobot (Zoho SalesIQ) en Python + Flask

import os
import unicodedata
from flask import Flask, request, jsonify

app = Flask(__name__)

# Sesiones en memoria: {visitor_id: {"state": "...", "data": {...}}}
sessions = {}


def get_visitor_id(payload: dict) -> str:
    """Obtiene un identificador estable del visitante."""
    visitor = payload.get("visitor") or {}
    return str(
        visitor.get("id")
        or visitor.get("visitor_id")
        or visitor.get("email")
        or visitor.get("phone")
        or visitor.get("ip")
        or "anon"
    )


def build_reply(texts, input_card=None, action="reply") -> dict:
    """Crea la estructura mínima de respuesta que Zobot entiende."""
    if isinstance(texts, str):
        replies = [texts]
    else:
        replies = list(texts)

    response = {
        "action": action,
        "replies": replies
    }

    if input_card is not None:
        response["input"] = input_card

    return response


def normalizar_texto(txt: str) -> str:
    """Normaliza texto (minúsculas y sin acentos) para comparar opciones."""
    if not txt:
        return ""
    txt = txt.lower()
    txt = "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    )
    return txt.strip()


# Ruta simple para comprobar que el servidor está arriba
@app.route("/", methods=["GET"])
def index():
    return "Webhook server running"


@app.route("/salesiq-webhook", methods=["GET", "POST"])
def salesiq_webhook():
    # GET solo para pruebas rápidas en el navegador
    if request.method == "GET":
        return jsonify({"status": "ok", "message": "Use POST desde Zoho SalesIQ"})

    payload = request.get_json(force=True, silent=True) or {}
    handler = payload.get("handler")          # "trigger", "message", "context", etc.
    operation = payload.get("operation")      # "chat", "message"... (puede venir vacío)
    visitor_id = get_visitor_id(payload)

    # Recuperar o crear sesión
    session = sessions.setdefault(visitor_id, {
        "state": "inicio",
        "data": {}
    })

    print("=== SalesIQ payload ===")
    print(payload)

    # 1) Primera entrada (trigger)
    if handler == "trigger":
        session["state"] = "menu_principal"
        respuesta = build_reply(
            [
                "¡Bienvenido! Gracias por contactar con Selec.",
                "Por favor, seleccione una de las siguientes opciones para atender su solicitud."
            ],
            input_card={
                "type": "select",
                "options": [
                    "Solicitud Cotización",
                    "Servicio PostVenta"
                ]
            }
        )
        return jsonify(respuesta)

    # 2) Mensajes del usuario
    if handler == "message":
        message_text = extraer_mensaje(payload)
        print("=== mensaje extraído ===", repr(message_text))
        state = session.get("state", "inicio")

        # Menú principal (o inicio)
        if state in ("menu_principal", "inicio"):
            return jsonify(manejar_menu_principal(session, message_text))

        # Flujo de solicitud de cotización
        if state.startswith("cotizacion_"):
            return jsonify(manejar_flujo_cotizacion(session, message_text))

        # Flujo de postventa
        if state.startswith("postventa_"):
            return jsonify(manejar_flujo_postventa(session, message_text))

        # Fallback genérico
        session["state"] = "menu_principal"
        respuesta = build_reply(
            [
                "No he comprendido su mensaje.",
                "Por favor, indique si desea 'Solicitud Cotización' o 'Servicio PostVenta'."
            ]
        )
        return jsonify(respuesta)

    # 3) Otros handlers (context, etc.)
    return jsonify(build_reply("He recibido su mensaje."))


def extraer_mensaje(payload: dict) -> str:
    """
    Extrae el texto del mensaje desde el JSON de SalesIQ.
    Intenta primero en payload['message'], luego en payload['request']['message'].
    """
    # 1) Formato estándar: mensaje a nivel raíz
    msg_obj = payload.get("message")

    # 2) Alternativa: dentro de 'request'
    if not msg_obj:
        req_obj = payload.get("request") or {}
        msg_obj = req_obj.get("message")

    if isinstance(msg_obj, dict):
        txt = msg_obj.get("text") or msg_obj.get("value") or ""
        return str(txt).strip()

    if isinstance(msg_obj, str):
        return msg_obj.strip()

    return ""


def manejar_menu_principal(session: dict, message_text: str) -> dict:
    texto_norm = normalizar_texto(message_text)

    # Coincidencias amplias para "Solicitud Cotización"
    if (
        "cotiz" in texto_norm
        or "solicitud cotizacion" in texto_norm
        or texto_norm == "cotizacion"
    ):
        session["state"] = "cotizacion_empresa"
        return build_reply(
            [
                "Perfecto, trabajaremos en su solicitud de cotización.",
                "Por favor complete la siguiente información.",
                "Nombre de la empresa:"
            ]
        )

    # Coincidencias amplias para "Servicio PostVenta"
    if (
        "postventa" in texto_norm
        or "post venta" in texto_norm
        or "servicio postventa" in texto_norm
    ):
        session["state"] = "postventa_nombre"
        return build_reply(
            [
                "Perfecto, trabajaremos en su solicitud de postventa.",
                "Por favor, indique su nombre:"
            ]
        )

    # Si no reconoce la opción, volvemos a mostrar el menú
    return build_reply(
        [
            "No he podido identificar la opción.",
            "Seleccione una de las siguientes opciones:"
        ],
        input_card={
            "type": "select",
            "options": [
                "Solicitud Cotización",
                "Servicio PostVenta"
            ]
        }
    )


def manejar_flujo_cotizacion(session: dict, message_text: str) -> dict:
    data = session["data"]
    state = session["state"]

    if state == "cotizacion_empresa":
        data["empresa"] = message_text
        session["state"] = "cotizacion_giro"
        return build_reply("Giro:")

    if state == "cotizacion_giro":
        data["giro"] = message_text
        session["state"] = "cotizacion_rut"
        return build_reply("RUT:")

    if state == "cotizacion_rut":
        data["rut"] = message_text
        session["state"] = "cotizacion_contacto"
        return build_reply("Nombre de contacto:")

    if state == "cotizacion_contacto":
        data["contacto"] = message_text
        session["state"] = "cotizacion_correo"
        return build_reply("Correo:")

    if state == "cotizacion_correo":
        data["correo"] = message_text
        session["state"] = "cotizacion_telefono"
        return build_reply("Teléfono:")

    if state == "cotizacion_telefono":
        data["telefono"] = message_text
        session["state"] = "cotizacion_num_parte"
        return build_reply("Número de parte (o descripción detallada):")

    if state == "cotizacion_num_parte":
        data["num_parte"] = message_text
        session["state"] = "cotizacion_marca"
        return build_reply("Marca:")

    if state == "cotizacion_marca":
        data["marca"] = message_text
        session["state"] = "cotizacion_cantidad"
        return build_reply("Cantidad:")

    if state == "cotizacion_cantidad":
        data["cantidad"] = message_text
        session["state"] = "cotizacion_direccion"
        return build_reply("Dirección de entrega:")

    if state == "cotizacion_direccion":
        data["direccion_entrega"] = message_text

        resumen = (
            "Resumen de su solicitud de cotización:\n"
            f"Nombre de la empresa: {data.get('empresa')}\n"
            f"Giro: {data.get('giro')}\n"
            f"RUT: {data.get('rut')}\n"
            f"Nombre de contacto: {data.get('contacto')}\n"
            f"Correo: {data.get('correo')}\n"
            f"Teléfono: {data.get('telefono')}\n"
            f"Número de parte / descripción: {data.get('num_parte')}\n"
            f"Marca: {data.get('marca')}\n"
            f"Cantidad: {data.get('cantidad')}\n"
            f"Dirección de entrega: {data.get('direccion_entrega')}"
        )

        session["state"] = "menu_principal"

        return {
            "action": "reply",
            "replies": [
                "Gracias. Hemos registrado su solicitud con el siguiente detalle:",
                resumen,
                "Un ejecutivo de Selec se pondrá en contacto con usted."
            ]
        }

    session["state"] = "menu_principal"
    return build_reply(
        [
            "Ha ocurrido un problema con la conversación.",
            "Volvamos al inicio. ¿Desea 'Solicitud Cotización' o 'Servicio PostVenta'?"
        ]
    )


def manejar_flujo_postventa(session: dict, message_text: str) -> dict:
    data = session["data"]
    state = session["state"]

    if state == "postventa_nombre":
        data["nombre"] = message_text
        session["state"] = "postventa_rut"
        return build_reply("Indique su RUT:")

    if state == "postventa_rut":
        data["rut"] = message_text
        session["state"] = "postventa_numero_factura"
        return build_reply("Indique el número de factura (si lo tiene):")

    if state == "postventa_numero_factura":
        data["numero_factura"] = message_text
        session["state"] = "postventa_detalle"
        return build_reply("Describa brevemente el problema o solicitud de postventa:")

    if state == "postventa_detalle":
        data["detalle"] = message_text

        resumen = (
            f"Resumen de su solicitud de postventa:\n"
            f"Nombre: {data.get('nombre')}\n"
            f"RUT: {data.get('rut')}\n"
            f"Número de factura: {data.get('numero_factura')}\n"
            f"Detalle: {data.get('detalle')}"
        )

        session["state"] = "menu_principal"

        return {
            "action": "reply",
            "replies": [
                "Gracias. Hemos registrado su solicitud de postventa con el siguiente detalle:",
                resumen,
                "Un ejecutivo se pondrá en contacto con usted."
            ]
        }

    session["state"] = "menu_principal"
    return build_reply(
        [
            "Ha ocurrido un problema con la conversación.",
            "Volvamos al inicio. ¿Desea 'Solicitud Cotización' o 'Servicio PostVenta'?"
        ]
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=True)
