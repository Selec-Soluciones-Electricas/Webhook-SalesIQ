"""Cron de seguimiento de formularios SELEC."""

import hmac
import os
from flask import jsonify, request


def registrar_rutas_metricas(app):
    @app.route("/cron/metricas-formularios", methods=["POST"])
    def cron_metricas_formularios():
        import json
        from datetime import datetime, timedelta, timezone
        from SELEC_metricas_guardado_seguro import abrir_sesion
        from services.metricas_formularios import (
            consultar_sesion_analytics,
            obtener_url_analytics_formularios,
            PATRON_ID_FORMULARIO,
        )

        esperado = os.getenv("CRON_SECRET", "")
        recibido = request.headers.get("X-Cron-Secret", "")

        if not esperado or not recibido or not hmac.compare_digest(
            esperado, recibido
        ):
            return jsonify({"error": "No autorizado"}), 401

        habilitado = (
            os.getenv("SELEC_FORMULARIOS_ESCRITURA", "0") == "1"
            and os.getenv("SELEC_FORMULARIOS_CRON_ESCRITURA", "0") == "1"
            and request.args.get("dry_run") != "1"
        )

        ahora = datetime.now(timezone.utc)
        limite = (
            ahora - timedelta(hours=24)
        ).strftime("%Y-%m-%d %H:%M:%S")

        criterio = (
            '"Origen" = \'whatsapp\' AND "Estado" = \'INICIADA\' '
            f'AND "Fecha Ultima Actividad" < \'{limite}\''
        )

        try:
            sesion = abrir_sesion()
            url = obtener_url_analytics_formularios()

            respuesta = sesion.get(
                url.removesuffix("/rows") + "/data",
                params={"CONFIG": json.dumps({
                    "responseFormat": "json",
                    "keyValueFormat": True,
                    "selectedColumns": [
                        "ID Formulario", "Origen", "Estado"
                    ],
                    "criteria": criterio,
                })},
                timeout=25,
            )

            if respuesta.status_code != 200:
                raise RuntimeError("Fallo al leer Analytics")

            cuerpo = respuesta.json()
            if (
                not isinstance(cuerpo, dict)
                or cuerpo.get("status") not in (None, "success")
                or not isinstance(cuerpo.get("data"), list)
            ):
                raise RuntimeError("Respuesta de lectura invalida")

            filas = cuerpo["data"]
            ids = [fila.get("ID Formulario") for fila in filas]

            if len(ids) != len(set(ids)):
                raise RuntimeError("IDs de formulario duplicados")

            procesados = 0
            cambiados = 0

            for fila in filas[:25]:
                form_id = fila.get("ID Formulario")

                if (
                    not isinstance(form_id, str)
                    or not PATRON_ID_FORMULARIO.fullmatch(form_id)
                ):
                    raise RuntimeError("ID inesperado")

                if (
                    fila.get("Origen") != "whatsapp"
                    or fila.get("Estado") != "INICIADA"
                ):
                    raise RuntimeError("Origen o estado inesperado")

                procesados += 1

                if not habilitado:
                    continue

                actual = consultar_sesion_analytics(sesion, form_id)

                if (
                    not actual
                    or actual.get("Estado") != "INICIADA"
                    or actual.get("Origen") != "whatsapp"
                ):
                    continue

                config = {
                    "columns": {
                        "Estado": "INCOMPLETA",
                        "Fecha Actualizacion": ahora.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    },
                    "criteria": (
                        f'"ID Formulario" = \'{form_id}\' AND '
                        + criterio
                    ),
                    "dateFormat": "yyyy-MM-dd HH:mm:ss",
                    "addIfNotExist": False,
                }

                actualizado = sesion.put(
                    url,
                    params={"CONFIG": json.dumps(config)},
                    timeout=25,
                )

                if actualizado.status_code != 200:
                    raise RuntimeError(
                        "Actualizacion no confirmada; revisar"
                    )

                respuesta_put = actualizado.json()
                datos = (
                    respuesta_put.get("data")
                    if isinstance(respuesta_put, dict)
                    else None
                )

                if (
                    respuesta_put.get("status") != "success"
                    or not isinstance(datos, dict)
                    or type(datos.get("updatedRows")) is not int
                    or datos["updatedRows"] not in (0, 1)
                ):
                    raise RuntimeError(
                        "Respuesta de actualizacion inesperada"
                    )

                cambiados += datos["updatedRows"]

            return jsonify({
                "estado": "ok",
                "modo": "escritura" if habilitado else "simulacion",
                "candidatos": len(filas),
                "evaluados": procesados,
                "marcados_incompletos": cambiados,
            }), 200

        except Exception:
            app.logger.exception("Error cron formularios")
            return jsonify({
                "error": "Fallo en cron de formularios"
            }), 503
