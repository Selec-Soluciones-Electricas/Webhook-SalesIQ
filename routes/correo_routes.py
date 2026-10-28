import hmac
import os
import threading
import traceback

from flask import Response, jsonify, request

from utils.security import cron_autorizado


def _secreto_valido() -> bool:
    return cron_autorizado()


def _agente_activo() -> bool:
    return os.getenv("CORREO_AGENTE", "off").lower() == "on"


def register_correo_routes(app):

    # -----------------------------------------------------
    # Revisión periódica (respaldo del tiempo real)
    # -----------------------------------------------------
    @app.route("/cron/correos", methods=["GET", "POST"])
    def correos_endpoint():
        if not _secreto_valido():
            return jsonify({"error": "No autorizado"}), 401
        if not _agente_activo():
            return jsonify({"estado": "desactivado (CORREO_AGENTE != on)"})

        dry_run = request.args.get("dry_run", "").lower() in ("1", "true", "si")
        try:
            horas = max(1, min(int(request.args.get("horas", 24)), 24 * 7))
            limite = max(1, min(int(request.args.get("limite", 10)), 30))
        except ValueError:
            horas, limite = 24, 10

        try:
            from agente.correo import ejecutar
            return jsonify(ejecutar(horas=horas, dry_run=dry_run, limite=limite))
        except Exception as e:
            print(f"[cron/correos] ERROR no controlado: {e}", flush=True)
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # -----------------------------------------------------
    # Corrección masiva de la columna Plataforma en Analytics
    #   sin parámetros  -> simulación (solo cuenta filas)
    #   ?aplicar=1      -> actualiza
    # -----------------------------------------------------
    @app.route("/cron/correos/plataformas", methods=["POST"])
    def corregir_plataformas_endpoint():
        if not _secreto_valido():
            return jsonify({"error": "No autorizado"}), 401
        aplicar = request.args.get("aplicar", "").lower() in ("1", "true", "si")
        try:
            from agente.correo import corregir_plataformas
            return jsonify(corregir_plataformas(aplicar=aplicar))
        except Exception as e:
            print(f"[cron/correos/plataformas] ERROR: {e}", flush=True)
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # -----------------------------------------------------
    # Crear / renovar la suscripción de Graph (1 vez al día)
    # -----------------------------------------------------
    @app.route("/cron/suscripciones", methods=["GET", "POST"])
    def suscripciones_endpoint():
        if not _secreto_valido():
            return jsonify({"error": "No autorizado"}), 401
        if not _agente_activo():
            return jsonify({"estado": "desactivado (CORREO_AGENTE != on)"})

        url_publica = os.getenv("URL_PUBLICA")
        if not url_publica:
            return jsonify({"error": "Falta la variable URL_PUBLICA"}), 500
        try:
            from agente.correo import asegurar_suscripciones
            return jsonify(asegurar_suscripciones(url_publica))
        except Exception as e:
            print(f"[cron/suscripciones] ERROR: {e}", flush=True)
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # -----------------------------------------------------
    # Notificaciones de Microsoft Graph (tiempo real)
    # -----------------------------------------------------
    @app.route("/graph/notificaciones", methods=["POST"])
    def graph_notificaciones():
        # 1. Validación al crear la suscripción: devolver el token tal cual, en texto plano.
        token = request.args.get("validationToken")
        if token is not None:
            return Response(token, status=200, mimetype="text/plain")

        if not _agente_activo():
            return "", 202

        # 2. Solo se aceptan buzones configurados y notificaciones con nuestro clientState.
        from agente.correo import _lista_env, procesar_notificacion

        buzon = (request.args.get("buzon") or "").lower()
        if buzon not in _lista_env("CORREO_BUZONES"):
            return "", 202

        esperado = os.getenv("CORREO_GRAPH_CLIENT_STATE", "")
        for n in (request.get_json(silent=True) or {}).get("value", []):
            if not esperado or not hmac.compare_digest(n.get("clientState") or "", esperado):
                print("[graph] notificación con clientState inválido, ignorada", flush=True)
                continue
            mensaje_id = (n.get("resourceData") or {}).get("id")
            if mensaje_id:
                # Graph exige respuesta en pocos segundos: el análisis va en segundo plano.
                threading.Thread(
                    target=procesar_notificacion, args=(buzon, mensaje_id), daemon=True
                ).start()

        return "", 202