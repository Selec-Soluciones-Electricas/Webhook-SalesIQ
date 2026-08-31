import os

from flask import jsonify, request, send_from_directory

from conversation.state_machine import (
    build_reply,
    elegir_owner_session,
    manejar_menu_principal,
    reply_menu_principal,
    es_saludo_inicio,
)

from conversation.quotation import (
    manejar_flujo_cotizacion_empresa_bloque,
    manejar_flujo_cotizacion_bloque,
)

from conversation.postventa import manejar_flujo_postventa_bloque

from services.email_service import enviar_correo_primer_contacto

from services.salesiq_service import (
    extraer_mensaje,
    get_visitor_id,
)

from utils.security import (
    mask_value,
    scrub_payload,
)


def register_routes(app, sessions, access_token):

    # =========================================================
    # RUTA PRINCIPAL
    # =========================================================

    @app.route("/", methods=["GET"])
    def index():
        return "Webhook server running"

    # =========================================================
    # FRONTEND DE PRUEBAS
    # =========================================================

    @app.route("/test", methods=["GET"])
    def test_frontend():

        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        )

        frontend_dir = os.path.join(
            base_dir,
            "frontend"
        )

        print("=== FRONTEND DEBUG ===")
        print("base_dir:", base_dir)
        print("frontend_dir:", frontend_dir)
        print(
            "index existe:",
            os.path.isfile(
                os.path.join(
                    frontend_dir,
                    "index.html"
                )
            )
        )
        print("======================")

        return send_from_directory(
            frontend_dir,
            "index.html"
        )

    # =========================================================
    # SALESIQ WEBHOOK
    # =========================================================

    @app.route("/salesiq-webhook", methods=["GET", "POST"])
    def salesiq_webhook():

        if request.method == "GET":
            return jsonify({
                "status": "ok",
                "message": "Use POST desde Zoho SalesIQ"
            })

        payload = request.get_json(
            force=True,
            silent=True
        ) or {}

        handler = payload.get("handler")
        visitor_id = get_visitor_id(payload)

        session = sessions.setdefault(
            visitor_id,
            {
                "state": "inicio",
                "data": {}
            }
        )

        actualizar_num_chat(
            session,
            payload
        )

        print("=== SalesIQ payload (safe) ===")
        print(scrub_payload(payload))

        if handler == "trigger":
            return procesar_trigger(
                session,
                payload,
                access_token
            )

        if handler == "message":
            return procesar_mensaje(
                session,
                payload
            )

        return jsonify(
            build_reply(
                "He recibido su mensaje."
            )
        )


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def actualizar_num_chat(session, payload):
    """
    Guarda el identificador de la conversación
    o visita actual dentro de la sesión.
    """

    visitor = payload.get("visitor") or {}

    visitid = visitor.get("visitid")

    conversation_id = str(
        visitor.get("active_conversation_id") or ""
    ).strip()

    if visitid:
        session["data"]["num_chat"] = f"#{visitid}"

    elif conversation_id:
        session["data"]["num_chat"] = conversation_id


def procesar_trigger(session, payload, access_token):
    """
    Procesa el evento trigger enviado por SalesIQ.
    """

    session["state"] = "menu_principal"

    owner = elegir_owner_session(session)

    if not session.get("primer_correo_enviado"):

        enviar_correo_primer_contacto(
            owner,
            payload,
            access_token,
        )

        session["primer_correo_enviado"] = True

    return jsonify(
        reply_menu_principal()
    )


def procesar_mensaje(session, payload):
    """
    Procesa un mensaje recibido desde SalesIQ
    según el estado actual de la conversación.
    """

    message_text = extraer_mensaje(payload)

    print(
        "=== mensaje extraído ===",
        repr(
            mask_value(
                message_text,
                0,
                0
            )[:120]
        )
    )

    # =========================================================
    # REINICIO POR SALUDO
    # =========================================================
    #
    # El frontend de pruebas utiliza un visitor_id fijo. Si una
    # sesión anterior quedó a mitad de una cotización, un nuevo
    # "hola" no debe interpretarse como datos de empresa.
    #
    # El saludo tiene prioridad sobre cualquier estado anterior.
    # =========================================================

    if es_saludo_inicio(message_text):

        print(
            "[procesar_mensaje] Saludo detectado. "
            "Reiniciando sesión."
        )

        session.clear()
        session["state"] = "menu_principal"
        session["data"] = {}

        elegir_owner_session(session)

        return jsonify(
            reply_menu_principal()
        )

    state = session.get(
        "state",
        "inicio"
    )

    # =========================================================
    # INICIO
    # =========================================================

    if state == "inicio":

        session["state"] = "menu_principal"

        return jsonify(
            reply_menu_principal()
        )

    # =========================================================
    # MENU PRINCIPAL
    # =========================================================

    if state == "menu_principal":

        return jsonify(
            manejar_menu_principal(
                session,
                message_text
            )
        )

    # =========================================================
    # DATOS DE EMPRESA - COTIZACION
    # =========================================================

    if state == "cotizacion_empresa_bloque":

        return jsonify(
            manejar_flujo_cotizacion_empresa_bloque(
                session,
                message_text
            )
        )

    # =========================================================
    # PRODUCTO - COTIZACION
    # =========================================================

    if state == "cotizacion_producto_bloque":

        session["state"] = "cotizacion_bloque"

        return jsonify(
            manejar_flujo_cotizacion_bloque(
                session,
                message_text
            )
        )

    # =========================================================
    # COTIZACION
    # =========================================================

    if state == "cotizacion_bloque":

        return jsonify(
            manejar_flujo_cotizacion_bloque(
                session,
                message_text
            )
        )

    # =========================================================
    # POSTVENTA
    # =========================================================

    if state == "postventa_bloque":

        return jsonify(
            manejar_flujo_postventa_bloque(
                session,
                message_text
            )
        )

    # =========================================================
    # ESTADO DESCONOCIDO
    # =========================================================

    session["state"] = "menu_principal"

    return jsonify(
        reply_menu_principal()
    )
