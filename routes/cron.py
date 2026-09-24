import os
import time
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from services.salesiq_service import (
    listar_conversaciones_cerradas,
    obtener_tags_actuales,
    obtener_transcripcion_completa,
    agregar_tag_conversacion,
)
from services.zoho_service import get_salesiq_access_token
from services.clasificacion_cotizacion import decidir_resultado
from services.crm_lookup_service import (
    extraer_candidatos_telefono,
    buscar_deal_id_por_telefono,
)
from services.analytics_service import agregar_fila_analytics


# Margen de horas hacia atrás en cada corrida. El timeout real
# configurado en SalesIQ es de 24h; se usa el doble para no
# perder ningún chat por pequeños desfaces de reloj o husos
# horarios. Reprocesar un chat ya tageado es inofensivo (se
# detecta y se salta antes de tocar nada).
VENTANA_HORAS = 48

PAUSA_ENTRE_LLAMADAS = 0.4


def _tag_ids_conocidos():
    return {
        os.environ.get("SALESIQ_TAG_ID_CRM_OK"),
        os.environ.get("SALESIQ_TAG_ID_CRM_ERROR"),
        os.environ.get("SALESIQ_TAG_ID_INCOMPLETO"),
    } - {None}

# Funcion desarrollada con el fin de registrar una fila en el sistema de analytics.
def _registrar_en_analytics(
    conversation_id: str,
    visitid: str,
    resultado: str,
    deal_id: str,
    fecha,
) -> bool:

    fecha_str = fecha.strftime("%d-%b-%Y %H:%M:%S") if fecha else ""

    return agregar_fila_analytics(
        {
            "Conversation ID": conversation_id or "",
            "Visit ID": f"#{visitid}" if visitid else "",
            "Resultado": resultado,
            "Deal ID": deal_id or "",
            "Fecha": fecha_str,
        },
        date_format="dd-MMM-yyyy HH:mm:ss",
    )

# Funcion desarrollada con el fin de obtener un access token de Zoho CRM con permisos de solo lectura, para poder realizar consultas sin modificar datos en el CRM.
def ejecutar_reconciliacion():

    screenname = os.environ.get("SALESIQ_SCREENNAME")
    tag_id_ok = os.environ.get("SALESIQ_TAG_ID_CRM_OK")
    tag_id_error = os.environ.get("SALESIQ_TAG_ID_CRM_ERROR")
    tag_id_incompleto = os.environ.get("SALESIQ_TAG_ID_INCOMPLETO")

    resumen = {
        "revisados": 0,
        "ya_tageados": 0,
        "ok": 0,
        "error": 0,
        "incompleto": 0,
        "postventa_excluidos": 0,
        "fallos_tag": 0,
        "registrados_analytics": 0,
    }

    if not screenname or not tag_id_ok or not tag_id_error or not tag_id_incompleto:
        return {
            "error": (
                "Faltan variables de entorno: SALESIQ_SCREENNAME / "
                "SALESIQ_TAG_ID_CRM_OK / SALESIQ_TAG_ID_CRM_ERROR / "
                "SALESIQ_TAG_ID_INCOMPLETO"
            )
        }

    salesiq_token = get_salesiq_access_token()

    if not salesiq_token:
        return {"error": "No se pudo obtener el access token de SalesIQ."}

    ahora = datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=VENTANA_HORAS)

    desde_ms = int(desde.timestamp() * 1000)
    hasta_ms = int(ahora.timestamp() * 1000)

    conversaciones = listar_conversaciones_cerradas(
        screenname, salesiq_token, desde_ms, hasta_ms
    )

    tags_conocidos = _tag_ids_conocidos()

    for conv in conversaciones:

        visitor = conv.get("visitor") or {}

        if visitor.get("channel") != "whatsapp":
            continue

        conversation_id = str(
            conv.get("id") or visitor.get("active_conversation_id") or ""
        )

        if not conversation_id:
            continue

        resumen["revisados"] += 1

        tags_actuales = obtener_tags_actuales(
            conversation_id, screenname, salesiq_token
        )

        if any(t in tags_conocidos for t in tags_actuales):
            resumen["ya_tageados"] += 1
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        texto = obtener_transcripcion_completa(
            conversation_id, screenname, salesiq_token
        )

        decision = decidir_resultado(texto)

        if decision == "POSTVENTA":
            resumen["postventa_excluidos"] += 1
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        hora_creacion = None
        start_time = conv.get("start_time") or visitor.get("in_time")

        if start_time:
            try:
                hora_creacion = datetime.fromtimestamp(
                    int(start_time) / 1000, tz=timezone.utc
                )
            except Exception:
                hora_creacion = None

        visitid = visitor.get("visitid") or ""

        if decision == "SIN_DATOS":

            resumen["incompleto"] += 1

            if not agregar_tag_conversacion(
                conversation_id, tag_id_incompleto, salesiq_token
            ):
                resumen["fallos_tag"] += 1

            if _registrar_en_analytics(
                conversation_id, visitid, "Incompleto", None, hora_creacion
            ):
                resumen["registrados_analytics"] += 1

            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        # decision es "OK" o "ERROR"

        tag_id = tag_id_ok if decision == "OK" else tag_id_error
        resumen["ok" if decision == "OK" else "error"] += 1

        deal_id = None

        if decision == "OK":
            candidatos = extraer_candidatos_telefono(texto)
            deal_id = buscar_deal_id_por_telefono(
                candidatos, hora_creacion, hora_creacion
            )

        if not agregar_tag_conversacion(
            conversation_id, tag_id, salesiq_token
        ):
            resumen["fallos_tag"] += 1

        if _registrar_en_analytics(
            conversation_id,
            visitid,
            "OK" if decision == "OK" else "Error",
            deal_id,
            hora_creacion,
        ):
            resumen["registrados_analytics"] += 1

        time.sleep(PAUSA_ENTRE_LLAMADAS)

    return resumen


def register_cron_routes(app):

    @app.route("/cron/reconciliar", methods=["GET", "POST"])
    def reconciliar_endpoint():

        secreto_esperado = os.environ.get("CRON_SECRET")

        secreto_recibido = (
            request.headers.get("X-Cron-Secret")
            or request.args.get("secret")
        )

        if not secreto_esperado or secreto_recibido != secreto_esperado:
            return jsonify({"error": "No autorizado"}), 401

        resultado = ejecutar_reconciliacion()

        return jsonify(resultado), 200