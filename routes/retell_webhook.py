
import json
import os

from flask import Blueprint, jsonify, request
from retell.lib.webhook_auth import verify

retell_bp = Blueprint("retell", __name__)


@retell_bp.post("/retell/webhook")
def recibir_webhook_retell():

    api_key = os.getenv("RETELL_API_KEY")

    if not api_key:
        return jsonify({
            "error": "Retell no configurado"
        }), 503

    raw_body = request.get_data(as_text=True)
    signature = request.headers.get(
        "X-Retell-Signature", ""
    )

    if not signature:
        return jsonify({
            "error": "Firma ausente"
        }), 401

    try:
        firma_valida = verify(
            raw_body,
            api_key,
            signature,
        )

    except Exception:
        return jsonify({
            "error": "No se pudo verificar la firma"
        }), 401

    if not firma_valida:
        return jsonify({
            "error": "Firma invalida"
        }), 401

    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        return jsonify({
            "error": "JSON invalido"
        }), 400

    evento = payload.get("event")
    llamada = payload.get("call") or {}
    call_id = llamada.get("call_id")

    if not evento or not call_id:
        return jsonify({
            "error": "Evento incompleto"
        }), 400


    # Verificar que el evento pertenezca a Sofia
    agente_autorizado = (
        os.getenv("RETELL_SOFIA_AGENT_ID") or ""
    ).strip()

    if not agente_autorizado:
        print(
            "[RETELL] ERROR: Agent ID de Sofia no configurado"
        )
        return jsonify({
            "error": "Agente no configurado"
        }), 503

    agente_recibido = llamada.get("agent_id")

    if agente_recibido != agente_autorizado:
        print(
            "[RETELL] Evento ignorado: agente no autorizado"
        )
        return "", 204


    print(
        "[RETELL] Evento:",
        evento,
        "| Call ID:",
        call_id,
    )


    # =====================================================
    # RETELL - CONFIRMACION RAPIDA DEL WEBHOOK
    # =====================================================
    #
    # Este endpoint solamente valida y confirma eventos.
    #
    # La recuperacion y clasificacion de llamadas se
    # realizara mediante el procesador independiente.
    #
    # No consultar ni modificar Zoho CRM aqui.
    # =====================================================

    if evento == "call_analyzed":
        print(
            "[RETELL] Analisis recibido.",
            "Pendiente de recuperacion independiente.",
            "| Call ID:",
            call_id,
        )

    # HTTP 204 confirma la recepcion del evento.
    # No significa que la llamada ya fue registrada en Zoho.
    return "", 204
