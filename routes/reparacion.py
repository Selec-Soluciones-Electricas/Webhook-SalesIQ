import os
import time
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from services.salesiq_service import (
    obtener_detalle_conversacion,
    obtener_mensajes_conversacion,
)
from services.zoho_service import get_salesiq_access_token
from services.crm_lookup_service import buscar_deal_id_por_chat_detallado
from services.analytics_repair_service import (
    listar_filas_analytics,
    actualizar_filas_analytics,
)
from routes.cron import _texto_mensaje, _a_epoch_ms


PAUSA_ENTRE_LLAMADAS = 0.4

# cron-job.org corta la conexión a los 30 s. Se procesa por
# lotes y se deja de tomar filas nuevas al llegar a este tiempo,
# para responder siempre antes del corte.
TIEMPO_MAXIMO_SEG = 20

LIMITE_POR_DEFECTO = 5

# Margen de días alrededor del chat para buscar el Deal. Más
# amplio que en el cron porque aquí se reparan chats antiguos
# cuya fecha registrada puede no ser la de inicio.
MARGEN_DIAS_REPARACION = 2

FORMATOS_FECHA_ANALYTICS = (
    "%d-%b-%Y %H:%M:%S",
    "%d %b, %Y %H:%M:%S",
    "%d %b %Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%b %d, %Y %I:%M:%S %p",
    "%d %b, %Y %I:%M:%S %p",
)

# Formatos de visualización sin año (ej. "08-27, 09:31:43 AM",
# como se ve la columna Fecha en la tabla). Se completa el año.
FORMATOS_FECHA_SIN_ANIO = (
    "%m-%d, %I:%M:%S %p",
    "%m-%d, %H:%M:%S",
    "%d-%b %H:%M:%S",
)

CAMPOS_INICIO_CHAT = (
    "start_time",
    "chat_start_time",
    "created_time",
    "start_time_in_ms",
    "time",
)

CAMPOS_FIN_CHAT = (
    "end_time",
    "chat_end_time",
    "closed_time",
    "end_time_in_ms",
    "last_modified_time",
)

_log_detalle_emitido = False


def _vacio(valor) -> bool:
    return valor is None or str(valor).strip() == ""


def _escapar(valor) -> str:
    return str(valor).replace("'", "''")


# Funcion desarrollada con el fin de interpretar la fecha que devuelve Analytics, probando varios formatos (incluidos los que no traen año).
def _parsear_fecha_analytics(valor):

    if _vacio(valor):
        return None

    # Epoch o ISO
    ms = _a_epoch_ms(valor)

    if ms:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

    texto = str(valor).strip()

    for formato in FORMATOS_FECHA_ANALYTICS:
        try:
            return datetime.strptime(texto, formato).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue

    ahora = datetime.now(timezone.utc)

    for formato in FORMATOS_FECHA_SIN_ANIO:
        try:
            # Se agrega el año al texto para evitar el aviso de
            # strptime con fechas sin año (29 de febrero).
            dt = datetime.strptime(
                f"{ahora.year} {texto}", f"%Y {formato}"
            ).replace(tzinfo=timezone.utc)

            # Si queda en el futuro, corresponde al año anterior.
            if dt > ahora + timedelta(days=1):
                dt = dt.replace(year=dt.year - 1)

            return dt

        except ValueError:
            continue

    return None


def _buscar_ms(fuentes, campos):

    for fuente in fuentes:
        if not isinstance(fuente, dict):
            continue
        for campo in campos:
            ms = _a_epoch_ms(fuente.get(campo))
            if ms:
                return ms

    return None


# Funcion desarrollada con el fin de obtener la ventana de tiempo real del chat (inicio y fin) desde SalesIQ, con la fecha de Analytics como respaldo.
def _ventana_chat(detalle: dict, fila: dict):

    global _log_detalle_emitido

    fuentes = [detalle, detalle.get("data"), detalle.get("visitor")]

    ms_inicio = _buscar_ms(fuentes, CAMPOS_INICIO_CHAT)
    ms_fin = _buscar_ms(fuentes, CAMPOS_FIN_CHAT)

    inicio = (
        datetime.fromtimestamp(ms_inicio / 1000, tz=timezone.utc)
        if ms_inicio else None
    )

    fin = (
        datetime.fromtimestamp(ms_fin / 1000, tz=timezone.utc)
        if ms_fin else None
    )

    if not inicio and not fin and not _log_detalle_emitido:
        _log_detalle_emitido = True
        print(
            "[reparar_deal_ids] Detalle sin fechas reconocibles. "
            f"claves={sorted(detalle.keys())} "
            f"fecha_fila={fila.get('Fecha')!r}"
        )

    fecha_fila = _parsear_fecha_analytics(fila.get("Fecha"))

    inicio = inicio or fecha_fila or fin
    fin = fin or fecha_fila

    origen = (
        "salesiq" if ms_inicio or ms_fin
        else "analytics" if fecha_fila
        else None
    )

    return inicio, fin, origen


# Funcion desarrollada con el fin de completar el Deal ID de todas las filas OK que lo tengan vacío en Analytics.
def reparar_deal_ids(
    dry_run: bool = False,
    limite: int = LIMITE_POR_DEFECTO,
    offset: int = 0,
) -> dict:

    global _log_detalle_emitido
    _log_detalle_emitido = False

    t_inicio = time.monotonic()

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

    # Orden estable entre corridas, para que el offset sea válido.
    pendientes = sorted(
        (f for f in filas_ok if _vacio(f.get("Deal ID"))),
        key=lambda f: (
            str(f.get("Conversation ID") or ""),
            str(f.get("Attempt ID") or ""),
        ),
    )

    total_pendientes = len(pendientes)
    lote = pendientes[offset:offset + limite]

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
        "ok_sin_deal_id": total_pendientes,
        "offset": offset,
        "limite": limite,
        "procesadas_en_lote": 0,
        "reparadas": 0,
        "no_encontradas": [],
        "requieren_revision_manual": [],
        "fallos_actualizacion": [],
        "propuestas": [],
    }

    for fila in lote:

        if time.monotonic() - t_inicio > TIEMPO_MAXIMO_SEG:
            print("[reparar_deal_ids] Tiempo máximo alcanzado; se corta el lote.")
            break

        resumen["procesadas_en_lote"] += 1

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

            inicio, fin, origen_fecha = _ventana_chat(detalle, fila)

            busqueda = buscar_deal_id_por_chat_detallado(
                texto_chat,
                inicio,
                fin,
                margen_dias=MARGEN_DIAS_REPARACION,
            )

            deal_id = busqueda["deal_id"]

        except Exception as e:

            print(f"[reparar_deal_ids] ERROR en {conversation_id}: {e}")

            resumen["requieren_revision_manual"].append(
                {**referencia, "motivo": f"Error: {e}"}
            )
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        if not deal_id:
            resumen["no_encontradas"].append(
                {
                    **referencia,
                    "motivo": busqueda["motivo"],
                    "mensajes": len(mensajes),
                    "fecha_fila": fila.get("Fecha"),
                    "origen_fecha": origen_fecha,
                    "ventana": busqueda["ventana"],
                    "deals_en_ventana": busqueda["deals_en_ventana"],
                    "deals_cualquier_fuente": busqueda.get(
                        "deals_en_ventana_cualquier_fuente", 0
                    ),
                    "telefonos": busqueda["telefonos"],
                    "emails": busqueda["emails"],
                    "detalle_error": busqueda.get("detalle_error"),
                }
            )
            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        resumen["propuestas"].append(
            {
                **referencia,
                "deal_id": deal_id,
                "criterio": busqueda["criterio"],
            }
        )

        print(
            "[reparar_deal_ids] Propuesta: "
            f"conv={conversation_id} visit={visit_id} deal={deal_id}"
        )

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

    # Siguiente offset: en dry_run nada cambia en Analytics, así
    # que se avanza todo lo procesado. En modo real, las filas
    # reparadas salen de la lista de pendientes, así que solo se
    # avanza lo que quedó sin resolver.
    avance = resumen["procesadas_en_lote"]

    if not dry_run:
        avance -= resumen["reparadas"]

    siguiente = offset + avance

    resumen["siguiente_offset"] = siguiente
    resumen["quedan_por_revisar"] = max(
        0,
        (total_pendientes - (0 if dry_run else resumen["reparadas"]))
        - siguiente,
    )
    resumen["duracion_seg"] = round(time.monotonic() - t_inicio, 1)

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
            limite = max(1, min(int(request.args.get("limite", LIMITE_POR_DEFECTO)), 50))
        except ValueError:
            limite = LIMITE_POR_DEFECTO

        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            offset = 0

        try:
            resultado = reparar_deal_ids(
                dry_run=dry_run,
                limite=limite,
                offset=offset,
            )
        except Exception as e:
            print(f"[reparar-deal-ids] ERROR no controlado: {e}")
            return jsonify({"error": str(e)}), 500

        return jsonify(resultado), 200