
"""Cron seguro para el catalogo de cuentas SELEC."""

import hmac
import os
from flask import jsonify, request


def registrar_rutas_catalogo_cuentas(app):

    @app.route(
        "/cron/catalogo-cuentas",
        methods=["POST"]
    )
    def cron_catalogo_cuentas():

        esperado = os.getenv("CRON_SECRET", "")
        recibido = request.headers.get(
            "X-Cron-Secret", ""
        )

        if (
            not esperado
            or not recibido
            or not hmac.compare_digest(
                esperado, recibido
            )
        ):
            return jsonify({
                "error": "No autorizado"
            }), 401

        from services.sync_catalogo_cuentas import (
            preparar_sincronizacion,
            preparar_importacion,
            aplicar_cambios,
        )

        habilitado = (
            os.getenv(
                "SELEC_CATALOGO_CUENTAS_ESCRITURA",
                "0"
            ) == "1"
            and request.args.get("dry_run") != "1"
        )

        try:
            plan = preparar_sincronizacion()

            paquete = preparar_importacion(plan)

            nuevas = len(plan["nuevas"])
            modificadas = len(plan["modificadas"])
            cantidad = nuevas + modificadas

            if not habilitado:
                return jsonify({
                    "estado": "ok",
                    "modo": "simulacion",
                    "cuentas_crm": plan["cuentas_crm"],
                    "cuentas_analytics": plan[
                        "cuentas_analytics"
                    ],
                    "nuevas": nuevas,
                    "modificadas": modificadas,
                    "escrituras": 0,
                }), 200

            if paquete is None:
                return jsonify({
                    "estado": "ok",
                    "modo": "escritura",
                    "nuevas": 0,
                    "modificadas": 0,
                    "escrituras": 0,
                }), 200

            from SELEC_metricas_guardado_seguro import (
                abrir_sesion,
            )

            sesion = abrir_sesion()

            try:
                resultado = aplicar_cambios(
                    plan,
                    sesion=sesion,
                    permitir_escritura=True,
                )
            finally:
                sesion.close()

            return jsonify({
                "estado": "ok",
                "modo": "escritura",
                "nuevas": nuevas,
                "modificadas": modificadas,
                "escrituras": resultado["cantidad"],
                "resultado": resultado["estado"],
            }), 200

        except Exception as error:
            app.logger.error(
                "Error sincronizando cuentas: %s",
                type(error).__name__,
            )

            return jsonify({
                "estado": "error",
                "mensaje": "Sincronizacion no completada"
            }), 503
