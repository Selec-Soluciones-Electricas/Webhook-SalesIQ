import os
import time
import traceback
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
from services.crm_lookup_service import buscar_deal_id_por_chat
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
# Deben coincidir con los mensajes de conversation/quotation.py.
# Si cambias esos textos, actualiza también estas constantes.

FRASE_INICIO_COTIZACION = (
    "Perfecto, trabajaremos en su solicitud de cotización"
)

FRASE_EXITO_COTIZACION = (
    "Un ejecutivo de Selec se pondrá"
)

FRASE_ERROR_COTIZACION = (
    "ocurrió un inconveniente al registrarla"
)


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

# Funcion desarrollada con el fin de obtener el canal del visitante (whatsapp, website, etc.) sin importar en qué campo lo entregue SalesIQ.
def _obtener_canal_visitante(visitor: dict) -> str:
    """
    Devuelve el canal en minúsculas, o "" si no se encuentra.

    SalesIQ no es consistente: según el endpoint, el canal viene
    en visitor["channel"], en visitor["channel_details"]["channel"]
    o en visitor["channel_details"]["channel_name"].
    """

    if not isinstance(visitor, dict):
        return ""

    detalles = visitor.get("channel_details") or {}

    if not isinstance(detalles, dict):
        detalles = {}

    candidatos = [
        detalles.get("channel"),
        detalles.get("channel_name"),
        visitor.get("channel"),
        visitor.get("channel_name"),
    ]

    for valor in candidatos:
        if valor:
            return str(valor).strip().lower()

    return ""


# Funcion desarrollada con el fin de convertir un epoch en milisegundos a datetime UTC, tolerando valores vacíos o inválidos.
def _fecha_desde_ms(ms) -> datetime:
    """
    Devuelve un datetime aware en UTC, o None si el valor no es
    válido.

    Se usa UTC para ser consistente con quotation.py, que
    registra en Analytics con datetime.now(timezone.utc).
    """

    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


# Funcion desarrollada con el fin de obtener el texto de un mensaje de SalesIQ, sin importar la estructura en que venga.
def _texto_mensaje(mensaje: dict) -> str:

    if not isinstance(mensaje, dict):
        return str(mensaje or "")

    texto = mensaje.get("text")

    if texto:
        return str(texto)

    contenido = mensaje.get("message")

    if isinstance(contenido, dict):
        return str(contenido.get("text") or contenido.get("msg") or "")

    if isinstance(contenido, str):
        return contenido

    return str(mensaje.get("msg") or "")


# Campos donde SalesIQ puede entregar la hora de un mensaje,
# según el endpoint y la versión de la API.
CAMPOS_TIEMPO_MENSAJE = (
    "time",
    "sent_time",
    "created_time",
    "timestamp",
    "msg_time",
    "time_in_ms",
    "message_time",
    "sent_time_in_ms",
)

_log_estructura_mensaje_emitido = False


# Funcion desarrollada con el fin de convertir un valor de tiempo (epoch en s/ms, texto numérico o ISO 8601) a epoch en milisegundos.
def _a_epoch_ms(valor):

    if valor is None or valor == "":
        return None

    # Numérico o texto numérico: "1790248157628", "1790248157628.0",
    # 1790248157 (segundos)
    try:
        numero = float(valor)

        if numero <= 0:
            return None

        # Si viene en segundos (10 dígitos), pasar a ms.
        if numero < 1e11:
            numero *= 1000

        return int(numero)

    except (TypeError, ValueError):
        pass

    # Texto ISO 8601: "2026-09-24T09:01:34.000Z", "2026-09-24T09:01:34-03:00"
    try:
        texto = str(valor).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(texto)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return int(dt.timestamp() * 1000)

    except (TypeError, ValueError):
        return None


# Funcion desarrollada con el fin de obtener el momento (epoch ms) de un mensaje de SalesIQ, revisando el nivel superior y el objeto "message" anidado.
def _tiempo_mensaje(mensaje: dict):

    global _log_estructura_mensaje_emitido

    if not isinstance(mensaje, dict):
        return None

    fuentes = [mensaje]

    if isinstance(mensaje.get("message"), dict):
        fuentes.append(mensaje["message"])

    for fuente in fuentes:
        for campo in CAMPOS_TIEMPO_MENSAJE:
            ms = _a_epoch_ms(fuente.get(campo))
            if ms:
                return ms

    # Log único por corrida con la estructura real del mensaje,
    # para poder ajustar CAMPOS_TIEMPO_MENSAJE si hace falta.
    if not _log_estructura_mensaje_emitido:

        _log_estructura_mensaje_emitido = True

        anidado = mensaje.get("message")

        print(
            "[cron] Mensaje sin hora reconocible. "
            f"claves={sorted(mensaje.keys())} "
            f"claves_message={sorted(anidado.keys()) if isinstance(anidado, dict) else None} "
            f"ejemplo={str(mensaje)[:300]}"
        )

    return None


# Funcion desarrollada con el fin de separar una conversación en intentos de cotización, cada uno con su resultado (OK, Error o Incompleto).
def _detectar_intentos_cotizacion(mensajes: list) -> list:
    """
    Recorre los mensajes en orden cronológico. Cada vez que
    aparece FRASE_INICIO_COTIZACION se abre un intento nuevo.

    El intento se cierra como:
        - "Error"      si aparece FRASE_ERROR_COTIZACION
        - "OK"         si aparece FRASE_EXITO_COTIZACION
        - "Incompleto" si empieza otro intento antes de cerrarse,
                       o si el chat terminó con el intento abierto

    Devuelve una lista de dicts:
        {
            "resultado": "OK" | "Error" | "Incompleto",
            "inicio_ms": int,
            "fin_ms": int | None,
            "mensajes": [str, ...],   # textos del intento
        }
    """

    ordenados = sorted(
        (m for m in (mensajes or []) if m),
        key=lambda m: _tiempo_mensaje(m) or 0,
    )

    intentos = []
    actual = None

    for mensaje in ordenados:

        texto = _texto_mensaje(mensaje)
        tiempo = _tiempo_mensaje(mensaje)

        if FRASE_INICIO_COTIZACION in texto:

            # Un intento abierto que no terminó antes de que
            # comenzara otro queda como Incompleto.
            if actual:
                actual["resultado"] = "Incompleto"
                intentos.append(actual)

            actual = {
                "resultado": None,
                "inicio_ms": tiempo,
                "fin_ms": tiempo,
                "mensajes": [texto],
            }

            continue

        if not actual:
            continue

        actual["mensajes"].append(texto)

        if tiempo:
            actual["fin_ms"] = tiempo

        # Se revisa primero el error: es el caso más específico.
        if FRASE_ERROR_COTIZACION in texto:
            actual["resultado"] = "Error"
            intentos.append(actual)
            actual = None
            continue

        if FRASE_EXITO_COTIZACION in texto:
            actual["resultado"] = "OK"
            intentos.append(actual)
            actual = None
            continue

    # El chat ya está cerrado: si quedó un intento abierto,
    # el visitante no terminó la cotización.
    if actual:
        actual["resultado"] = "Incompleto"
        intentos.append(actual)

    return intentos


# Funcion desarrollada con el fin de registrar una fila en el sistema de analytics.
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

    visitid = str(visitid or "")

    if visitid and not visitid.startswith("#"):
        visitid = f"#{visitid}"

    return agregar_fila_analytics(
        {
            "Conversation ID": conversation_id or "",
            "Visit ID": visitid,
            "Resultado": resultado,
            "Deal ID": deal_id or "",
            "Fecha": fecha_str,
            "Attempt ID": attempt_id or "",
        },
        date_format="dd-MMM-yyyy HH:mm:ss",
    )


# =========================================================
# JOB DE RECONCILIACIÓN
# =========================================================

def ejecutar_reconciliacion():

    global _log_estructura_mensaje_emitido
    _log_estructura_mensaje_emitido = False

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
        "ok_sin_deal_id": 0,
        "errores_conversacion": 0,
        "sin_intentos": 0,
        "intentos_detectados": 0,
        "omitidos_historicos": 0,
        "omitidos_sin_tiempo": 0,
        "verificacion_fallida": 0,
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
    ) or []

    resumen["cerradas_recibidas"] = len(conversaciones)

    for conv in conversaciones:

        conversation_id = ""

        # Un error en una conversación no debe tumbar el job
        # completo: se registra y se sigue con la siguiente.
        try:

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
            ) or {}

            visitor_detalle = detalle.get("visitor") or {}

            canal = (
                _obtener_canal_visitante(visitor_detalle)
                or _obtener_canal_visitante(visitor)
            )

            if "whatsapp" not in canal:
                resumen["omitidos_no_whatsapp"] += 1
                time.sleep(PAUSA_ENTRE_LLAMADAS)
                continue

            resumen["revisados"] += 1

            tags_actuales = {
                str(t.get("id"))
                for t in (detalle.get("tags") or [])
                if isinstance(t, dict) and t.get("id")
            }

            # =============================================
            # SIEMPRE ANALIZAR LOS INTENTOS DEL CHAT
            # =============================================
            # Los tags son solo informativos. Ya no deciden si
            # una conversación completa se procesa o se omite.

            mensajes = obtener_mensajes_conversacion(
                conversation_id,
                screenname,
                salesiq_token,
            ) or []

            intentos = _detectar_intentos_cotizacion(
                mensajes
            )

            resumen["intentos_detectados"] += len(intentos)

            # Si no hubo ningún intento formal de cotización,
            # conservamos solamente la exclusión informativa de
            # Postventa. No registramos un "Incompleto" genérico.
            if not intentos:

                resumen["sin_intentos"] += 1

                # Muestra de los primeros mensajes para verificar
                # en el log que el texto se está leyendo bien.
                muestra = [
                    _texto_mensaje(m)[:40]
                    for m in mensajes[:3]
                ]

                print(
                    "[cron] Sin intentos: "
                    f"conv={conversation_id} "
                    f"mensajes={len(mensajes)} "
                    f"muestra={muestra}"
                )

                texto_completo = "\n".join(
                    _texto_mensaje(m) for m in mensajes
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
                    resumen["omitidos_sin_tiempo"] += 1
                    print(
                        "[cron] Intento sin hora de inicio: "
                        f"conv={conversation_id} "
                        f"resultado={resultado}"
                    )
                    continue

                # -----------------------------------------
                # NO TOCAR DATOS HISTÓRICOS
                # -----------------------------------------
                if inicio_ms < attempt_tracking_start_ms:
                    resumen["omitidos_historicos"] += 1
                    print(
                        "[cron] Intento histórico omitido: "
                        f"conv={conversation_id} "
                        f"inicio_ms={inicio_ms} "
                        f"tracking_start_ms={attempt_tracking_start_ms}"
                    )
                    continue

                attempt_id = (
                    f"{conversation_id}-{inicio_ms}"
                )

                # -----------------------------------------
                # COMPROBAR SI ESTE INTENTO YA EXISTE
                # -----------------------------------------
                existe = existe_attempt_id_analytics(
                    attempt_id
                )

                if existe is None:
                    resumen["verificacion_fallida"] += 1
                    print(
                        "[cron] No se pudo verificar "
                        f"Attempt ID: {attempt_id}"
                    )
                    continue

                # -----------------------------------------
                # ASEGURAR EL TAG CORRESPONDIENTE
                # -----------------------------------------
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

                # -----------------------------------------
                # RECUPERAR DEAL ID PARA UN OK DE RESPALDO
                # -----------------------------------------
                # Normalmente quotation.py ya registró el OK en
                # tiempo real. Este bloque actúa como respaldo si
                # esa escritura falló.
                if resultado == "OK":

                    texto_intento = "\n".join(
                        str(t or "")
                        for t in intento.get("mensajes", [])
                    )

                    fecha_fin = _fecha_desde_ms(
                        intento.get("fin_ms")
                    )

                    deal_id = buscar_deal_id_por_chat(
                        texto_intento,
                        fecha_inicio,
                        fecha_fin,
                    )

                    if not deal_id:
                        resumen["ok_sin_deal_id"] += 1
                        print(
                            "[cron] OK sin Deal ID: "
                            f"attempt_id={attempt_id}"
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

        except Exception as e:

            resumen["errores_conversacion"] += 1

            print(
                "[cron] ERROR procesando conversación "
                f"{conversation_id!r}: {e}"
            )
            traceback.print_exc()

        time.sleep(PAUSA_ENTRE_LLAMADAS)

    return resumen


# =========================================================
# RUTA
# =========================================================

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

        try:

            resultado = ejecutar_reconciliacion()

        except Exception as e:

            print(f"[cron/reconciliar] ERROR no controlado: {e}")
            traceback.print_exc()

            return jsonify({
                "error": "Error no controlado en la reconciliación",
                "detalle": str(e),
            }), 500

        return jsonify(resultado), 200