import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request

from services.salesiq_service import (
    listar_conversaciones_cerradas,
    obtener_detalle_conversacion,
    obtener_mensajes_conversacion,
    agregar_tag_conversacion,
)
from services.zoho_service import get_salesiq_access_token
from services.clasificacion_cotizacion import decidir_resultado
from services.crm_lookup_service import (
    extraer_candidatos_telefono,
    buscar_deal_id_por_telefono,
)
from services.analytics_service import (
    agregar_fila_analytics,
    existe_attempt_id_analytics,
)


# Margen de horas hacia atrás en cada corrida.
VENTANA_HORAS = 48

PAUSA_ENTRE_LLAMADAS = 0.4

CHILE_TZ = ZoneInfo("America/Santiago")

# =========================================================
# FRASES PARA DETECTAR INTENTOS DE COTIZACIÓN
# =========================================================

FRASE_INICIO_COTIZACION = (
    "Perfecto, trabajaremos en su solicitud de cotización"
)

FRASE_EXITO_COTIZACION = (
    "Un ejecutivo de Selec se pondrá"
)

FRASE_ERROR_COTIZACION = (
    "ocurrió un inconveniente al registrarla"
)


def _registrar_en_analytics(
    conversation_id: str,
    visitid: str,
    resultado: str,
    deal_id: str,
    fecha,
    attempt_id: str = None,
) -> bool:

    fecha_str = (
        fecha.strftime("%d-%b-%Y %H:%M:%S")
        if fecha
        else ""
    )

    return agregar_fila_analytics(
        {
            "Conversation ID": conversation_id or "",
            "Visit ID": f"#{visitid}" if visitid else "",
            "Resultado": resultado,
            "Deal ID": deal_id or "",
            "Fecha": fecha_str,
            "Attempt ID": attempt_id or "",
        },
        date_format="dd-MMM-yyyy HH:mm:ss",
    )


def _obtener_canal_visitante(visitor: dict) -> str:
    """
    Obtiene el canal real de SalesIQ.

    En las respuestas actuales de SalesIQ el canal suele venir
    como visitor.channel_details.channel o visitor.channel_name,
    no como visitor.channel.
    """

    visitor = visitor or {}
    channel_details = visitor.get("channel_details") or {}

    return str(
        visitor.get("channel")
        or channel_details.get("channel")
        or visitor.get("channel_name")
        or ""
    ).strip().lower()


def _detectar_intentos_cotizacion(mensajes: list) -> list:
    """
    Recorre los mensajes de una conversación en orden
    cronológico y detecta cada intento de cotización.

    Un intento comienza cuando aparece la frase de inicio
    del flujo de cotización.

    Puede terminar como:
    - OK
    - Error
    - Incompleto
    """

    intentos = []
    intento_actual = None
    numero_intento = 0

    for mensaje in mensajes:

        texto = str(
            mensaje.get("text") or ""
        )

        time_ms = mensaje.get("time_ms")

        # =================================================
        # INICIO DE UNA NUEVA COTIZACIÓN
        # =================================================

        if FRASE_INICIO_COTIZACION in texto:

            # Si ya había un intento abierto y aparece
            # otro inicio, el anterior quedó incompleto.
            if (
                intento_actual
                and intento_actual["resultado"] == "En proceso"
            ):
                intento_actual["resultado"] = "Incompleto"
                intento_actual["fin_ms"] = time_ms

            numero_intento += 1

            intento_actual = {
                "numero": numero_intento,
                "resultado": "En proceso",
                "inicio_ms": time_ms,
                "fin_ms": None,
                "mensajes": [texto],
            }

            intentos.append(intento_actual)
            continue

        if intento_actual is None:
            continue

        intento_actual["mensajes"].append(texto)

        # =================================================
        # COTIZACIÓN EXITOSA
        # =================================================

        if FRASE_EXITO_COTIZACION in texto:
            intento_actual["resultado"] = "OK"
            intento_actual["fin_ms"] = time_ms
            intento_actual = None
            continue

        # =================================================
        # ERROR AL REGISTRAR
        # =================================================

        if FRASE_ERROR_COTIZACION in texto:
            intento_actual["resultado"] = "Error"
            intento_actual["fin_ms"] = time_ms
            intento_actual = None
            continue

    # =====================================================
    # INTENTO QUE QUEDÓ ABIERTO
    # =====================================================

    # Este cron procesa conversaciones cerradas. Si al final
    # todavía hay un intento abierto, se considera incompleto.
    if (
        intento_actual
        and intento_actual["resultado"] == "En proceso"
    ):
        intento_actual["resultado"] = "Incompleto"

    return intentos


def _fecha_desde_ms(valor_ms):
    if not valor_ms:
        return None

    try:
        return datetime.fromtimestamp(
            int(valor_ms) / 1000,
            tz=timezone.utc,
        ).astimezone(CHILE_TZ)
    except (TypeError, ValueError, OSError):
        return None


def ejecutar_reconciliacion():

    screenname = os.environ.get("SALESIQ_SCREENNAME")
    tag_id_ok = os.environ.get("SALESIQ_TAG_ID_CRM_OK")
    tag_id_error = os.environ.get("SALESIQ_TAG_ID_CRM_ERROR")
    tag_id_incompleto = os.environ.get("SALESIQ_TAG_ID_INCOMPLETO")

    attempt_tracking_start_raw = os.environ.get(
        "ATTEMPT_TRACKING_START_MS"
    )

    try:
        attempt_tracking_start_ms = int(
            attempt_tracking_start_raw
        )
    except (TypeError, ValueError):
        return {
            "error": (
                "Falta o es inválida la variable "
                "ATTEMPT_TRACKING_START_MS"
            )
        }

    resumen = {
        "cerradas_recibidas": 0,
        "revisados": 0,
        "omitidos_no_whatsapp": 0,
        "ok": 0,
        "error": 0,
        "incompleto": 0,
        "postventa_excluidos": 0,
        "fallos_tag": 0,
        "registrados_analytics": 0,
        "ya_registrados_analytics": 0,
    }

    if (
        not screenname
        or not tag_id_ok
        or not tag_id_error
        or not tag_id_incompleto
    ):
        return {
            "error": (
                "Faltan variables de entorno: SALESIQ_SCREENNAME / "
                "SALESIQ_TAG_ID_CRM_OK / SALESIQ_TAG_ID_CRM_ERROR / "
                "SALESIQ_TAG_ID_INCOMPLETO"
            )
        }

    salesiq_token = get_salesiq_access_token()

    if not salesiq_token:
        return {
            "error": "No se pudo obtener el access token de SalesIQ."
        }

    ahora = datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=VENTANA_HORAS)

    desde_ms = int(desde.timestamp() * 1000)
    hasta_ms = int(ahora.timestamp() * 1000)

    conversaciones = listar_conversaciones_cerradas(
        screenname,
        salesiq_token,
        desde_ms,
        hasta_ms,
    )

    resumen["cerradas_recibidas"] = len(conversaciones)

    for conv in conversaciones:

        visitor = conv.get("visitor") or {}

        conversation_id = str(
            conv.get("id")
            or visitor.get("active_conversation_id")
            or ""
        )

        if not conversation_id:
            continue

        # El listado de conversaciones no siempre entrega el
        # canal en visitor["channel"]. Consultamos el detalle
        # para leer channel_details.channel / channel_name.
        detalle = obtener_detalle_conversacion(
            conversation_id,
            screenname,
            salesiq_token,
        )

        visitor_detalle = detalle.get("visitor") or {}

        canal = (
            _obtener_canal_visitante(visitor_detalle)
            or _obtener_canal_visitante(visitor)
        )

        if "whatsapp" not in canal:
            resumen["omitidos_no_whatsapp"] += 1
            continue

        resumen["revisados"] += 1

        tags_actuales = {
            str(t.get("id"))
            for t in (detalle.get("tags") or [])
            if t.get("id")
        }

        # =================================================
        # SIEMPRE ANALIZAR LOS INTENTOS DEL CHAT
        # =================================================
        # Los tags son solo informativos. Ya no deciden si una
        # conversación completa se procesa o se omite.

        mensajes = obtener_mensajes_conversacion(
            conversation_id,
            screenname,
            salesiq_token,
        )

        intentos = _detectar_intentos_cotizacion(
            mensajes
        )

        # Si no hubo ningún intento formal de cotización,
        # conservamos solamente la exclusión informativa de
        # Postventa. No registramos un "Incompleto" genérico.
        if not intentos:
            texto_completo = "\n".join(
                str(m.get("text") or "")
                for m in mensajes
            )

            if decidir_resultado(texto_completo) == "POSTVENTA":
                resumen["postventa_excluidos"] += 1

            time.sleep(PAUSA_ENTRE_LLAMADAS)
            continue

        visitid = (
            visitor_detalle.get("visitid")
            or visitor.get("visitid")
            or detalle.get("reference_id")
            or conv.get("reference_id")
            or ""
        )

        for intento in intentos:

            resultado = intento.get("resultado")

            if resultado not in (
                "OK",
                "Error",
                "Incompleto",
            ):
                continue

            inicio_ms = intento.get("inicio_ms")

            try:
                inicio_ms = int(inicio_ms)
            except (TypeError, ValueError):
                continue

            # ---------------------------------------------
            # NO TOCAR DATOS HISTÓRICOS
            # ---------------------------------------------
            if inicio_ms < attempt_tracking_start_ms:
                continue

            attempt_id = (
                f"{conversation_id}-{inicio_ms}"
            )

            # ---------------------------------------------
            # COMPROBAR SI ESTE INTENTO YA EXISTE
            # ---------------------------------------------
            existe = existe_attempt_id_analytics(
                attempt_id
            )

            if existe is None:
                print(
                    "[cron] No se pudo verificar "
                    f"Attempt ID: {attempt_id}"
                )
                continue

            # ---------------------------------------------
            # ASEGURAR EL TAG CORRESPONDIENTE
            # ---------------------------------------------
            if resultado == "OK":
                tag_id_resultado = tag_id_ok
            elif resultado == "Error":
                tag_id_resultado = tag_id_error
            else:
                tag_id_resultado = tag_id_incompleto

            if (
                tag_id_resultado
                and tag_id_resultado not in tags_actuales
            ):
                if agregar_tag_conversacion(
                    conversation_id,
                    tag_id_resultado,
                    salesiq_token,
                ):
                    tags_actuales.add(tag_id_resultado)
                else:
                    resumen["fallos_tag"] += 1

            # Si ya existe en Analytics, no volver a insertar.
            if existe:
                resumen["ya_registrados_analytics"] += 1
                continue

            fecha_inicio = _fecha_desde_ms(
                inicio_ms
            )

            deal_id = None

            # ---------------------------------------------
            # RECUPERAR DEAL ID PARA UN OK DE RESPALDO
            # ---------------------------------------------
            # Normalmente quotation.py ya registró el OK en
            # tiempo real. Este bloque actúa como respaldo si
            # esa escritura falló.
            if resultado == "OK":

                texto_intento = "\n".join(
                    str(t or "")
                    for t in intento.get("mensajes", [])
                )

                candidatos = extraer_candidatos_telefono(
                    texto_intento
                )

                fecha_fin = _fecha_desde_ms(
                    intento.get("fin_ms")
                )

                deal_id = buscar_deal_id_por_telefono(
                    candidatos,
                    fecha_inicio,
                    fecha_fin,
                )

            if _registrar_en_analytics(
                conversation_id,
                visitid,
                resultado,
                deal_id,
                fecha_inicio,
                attempt_id,
            ):
                resumen["registrados_analytics"] += 1

                if resultado == "OK":
                    resumen["ok"] += 1
                elif resultado == "Error":
                    resumen["error"] += 1
                else:
                    resumen["incompleto"] += 1

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

        if (
            not secreto_esperado
            or secreto_recibido != secreto_esperado
        ):
            return jsonify({"error": "No autorizado"}), 401

        resultado = ejecutar_reconciliacion()

        return jsonify(resultado), 200
