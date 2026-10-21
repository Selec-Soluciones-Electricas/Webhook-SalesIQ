import os
import traceback

from flask import jsonify, request


def register_correo_routes(app):

    @app.route("/cron/correos", methods=["GET", "POST"])
    def correos_endpoint():

        secreto_esperado = os.environ.get("CRON_SECRET")
        secreto_recibido = (
            request.headers.get("X-Cron-Secret")
            or request.args.get("secret")
        )
        if not secreto_esperado or secreto_recibido != secreto_esperado:
            return jsonify({"error": "No autorizado"}), 401

        if os.getenv("CORREO_AGENTE", "off").lower() != "on":
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