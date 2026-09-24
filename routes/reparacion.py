import os
import time
from datetime import datetime, timezone

from flask import jsonify, request

from services.salesiq_service import (
    obtener_detalle_conversacion,
    obtener_mensajes_conversacion,
)
from services.zoho_service import get_salesiq_access_token
from services.crm_lookup_service import buscar_deal_id_por_chat
from services.analytics_repair_service import (
    listar_filas_analytics,
    actualizar_filas_analytics,
)
from routes.cron import _texto_mensaje, _a_epoch_ms


PAUSA_ENTRE_LLAMADAS = 0.4

# Margen de días alrededor del chat para buscar el Deal. Más
# amplio que en el cron porque aquí se reparan chats antiguos
# cuya fecha registrada puede no ser la de inicio.
MARGEN_DIAS_REPARACION = 2

FORMATOS_FECHA_ANALYTICS = (
    "%d-%b-%Y %H:%M:%S",
    "%d %b, %Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
)


def _vacio(valor) -> bool:
    return valor is None or str(valor).strip() == ""


def _escapar(valor) -> str:
    return str(valor).replace("'", "''")


# Funcion desarrollada con el fin de interpretar la fecha que devuelve Analytics, probando varios formatos.
def _parsear_fecha_analytics(valor):

    if _vacio(valor):
        return None

    texto = str(valor).strip()

    for formato in FORMATOS_FECHA_ANALYTICS:
        try:
            return datetime.strptime(texto, formato).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue

    return None


# Funcion desarrollada con el fin de obtener la ventana de tiempo real del chat (inicio y fin) desde SalesIQ, con la fecha de Analytics como respaldo.
def _ventana_chat(detalle: dict, fila: dict):

    inicio = None
    fin = None

    for campo in ("start_time", "chat_start_time", "created_time"):
        ms = _a_epoch_ms(detalle.get(campo))
        if ms:
            inicio = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            break

    for campo in ("end_time", "chat_end_time", "closed_time"):
        ms = _a_epoch_ms(detalle.get(campo))
        if ms:
            fin = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            break

    fecha_fila = _parsear_fecha_analytics(fila.get("Fecha"))

    inicio = inicio or fecha_fila or fin
    fin = fin or fecha_fila

    return inicio, fin


# Funcion desarrollada con el fin de completar el Deal ID de todas las filas OK que lo tengan vacío en Analytics.
def reparar_deal_ids(dry_run: bool = False) -> dict:

    screenname = os.environ.get("SALESIQ_SCREENNAME")

    if not screenname:
        return {"error": "Falta SALESIQ_SCREENNAME"}

    salesiq_token = get_salesiq_access_token()

    if not salesiq_token:
        return {"error": "No se pudo obtener el access token de SalesIQ."}

    filas_ok = listar_filas_analytics("\"Resultado\"='OK'")

    if filas_ok is None:
        return {
            "error": (
                "No se pudieron leer las filas de Analytics. Revisa "
                "que el token tenga el scope ZohoAnalytics.data.read."
            )
        }

    pendientes = [f for f in filas_ok if _vacio(f.get("Deal ID"))]

    # Cuántas filas OK tiene cada conversación: si una fila sin
    # Attempt ID comparte conversación con otras filas OK, no se
    # puede actualizar sin riesgo de pisar un Deal ID correcto.
    ok_por_conversacion = {}

    for f in filas_ok:
        cid = str(f.get("Conversation ID") or "")
        ok_por_conversacion[cid] = ok_por_conversacion.get(cid, 0) + 1

    resumen = {
        "dry_run": dry_run,
        "filas_ok": len(filas_ok),
        "ok_sin_deal_id": len(pendientes),
        "reparadas": 0,
        "no_encontradas": [],
        "requieren_revision_manual": [],
        "fallos_actualizacion": [],
        "propuestas": [],
    }

    for fila in pendientes:

        conversation_id = str(fila.get("Conversation ID") or "").strip()
        visit_id = str(fila.get("Visit ID") or "")
        attempt_id = str(fila.get("Attempt ID") or "").strip()

        referencia = {
            "conversation_id": conversation_id,
            "visit_id": visit_id,
            "attempt_id": attempt_id or None,
        }

        if not conversation_id:
            resumen["requieren_revision_manual"].append(
                {**referencia, "motivo": "Fila sin Conversation ID"}
            )
            continue

        if not attempt_id and ok_por_conversacion.get(conversation_id, 0) > 1:
            resumen["requieren_revision_manual"].append(
                {
                    **referencia,
                    "motivo": (
                        "Varias filas OK en la misma conversación "
                        "sin Attempt ID"
                    ),
                }
            )
            continue

        try:

            detalle = obtener_detalle_conversacion(
                conversation_id, screenname, salesiq_token
            ) or {}

            mensajes = obtener_mensajes_conversacion(
                conversation_id, screenname, salesiq_token
            ) or []

            texto_chat = "\n".join(_texto_mensaje(m) for m in mensajes)

            inicio, fin = _ventana_chat(detalle, fila)

            deal_id = buscar_deal_id_por_chat(
                texto_chat,
                inicio,
                fin,
                margen_dias=MARGEN_DIAS_REPARACION,
            )

        except Exception as e:

            print(f"[reparar_deal_ids] ERROR en {conversation_id}: {e}")

            resumen["requieren_revision_manual"].append(
                {**referencia, "motivo": f"Error: {e}"}
            )
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        if not deal_id:
            resumen["no_encontradas"].append(referencia)
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        resumen["propuestas"].append({**referencia, "deal_id": deal_id})

        if dry_run:
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        criteria = (
            f"\"Conversation ID\"='{_escapar(conversation_id)}' "
            "AND \"Resultado\"='OK'"
        )

        if attempt_id:
            criteria += f" AND \"Attempt ID\"='{_escapar(attempt_id)}'"

        if actualizar_filas_analytics({"Deal ID": str(deal_id)}, criteria):
            resumen["reparadas"] += 1
        else:
            resumen["fallos_actualizacion"].append(
                {**referencia, "deal_id": deal_id}
            )

        time.sleep(PAUSA_ENTRE_LLAMADAS)

    return resumen


def register_reparacion_routes(app):

    @app.route("/cron/reparar-deal-ids", methods=["GET", "POST"])
    def reparar_deal_ids_endpoint():

        secreto_esperado = os.environ.get("CRON_SECRET")

        secreto_recibido = (
            request.headers.get("X-Cron-Secret")
            or request.args.get("secret")
        )

        if not secreto_esperado or secreto_recibido != secreto_esperado:
            return jsonify({"error": "No autorizado"}), 401

        dry_run = request.args.get("dry_run", "").lower() in ("1", "true", "si")

        try:
            resultado = reparar_deal_ids(dry_run=dry_run)
        except Exception as e:
            print(f"[reparar-deal-ids] ERROR no controlado: {e}")
            return jsonify({"error": str(e)}), 500

        return jsonify(resultado), 200