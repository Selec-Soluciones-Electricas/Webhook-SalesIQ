import os
import requests
from datetime import datetime, timezone

from flask import current_app, jsonify

from services.retell_procesador import procesar_pendientes_sofia
from utils.security import cron_autorizado


def register_sofia_cron_routes(app):

    @app.post("/cron/sofia")
    def ejecutar_cron_sofia():

        # 1. Bloquear solicitudes no autorizadas.
        if not cron_autorizado():
            return jsonify({
                "error": "No autorizado"
            }), 401

        # 2. Verificar el agente de Sofia.
        agente = (
            os.getenv("RETELL_SOFIA_AGENT_ID") or ""
        ).strip()

        if not agente:
            return jsonify({
                "error": "Agente de Sofia no configurado"
            }), 503

        # 3. Ejecutar exclusivamente en simulacion.
        # No se habilitan escrituras reales en Zoho CRM.

        try:
            # Recuperar las llamadas de las ultimas 48 horas.
            # Las fechas se calculan en UTC.
            fin_ms = int(
                datetime.now(timezone.utc).timestamp() * 1000
            )

            inicio_ms = fin_ms - (48 * 60 * 60 * 1000)


            # Planificar una ventana historica rotativa.
            # Por ahora solo se calcula y registra.
            # No ejecuta recuperacion historica adicional.
            from services.retell_ventanas_recuperacion import (
                seleccionar_ventana_historica_rotativa,
            )

            inicio_historico_ms = int(
                datetime(
                    2026, 10, 13, tzinfo=timezone.utc
                ).timestamp() * 1000
            )

            dia_utc = fin_ms // 86400000

            ventana_historica = (
                seleccionar_ventana_historica_rotativa(
                    inicio_historico_ms,
                    fin_ms,
                    dia_utc,
                )
            )

            current_app.logger.info(
                "[SOFIA CRON] Ventana historica planificada: "
                "%s de %s",
                ventana_historica["indice_ventana"],
                ventana_historica["total_ventanas"],
            )

            resultado = procesar_pendientes_sofia(
                agente,
                simulacion=True,
                inicio_ms=inicio_ms,
                fin_ms=fin_ms,
            )


        except Exception:
            current_app.logger.exception(
                "[SOFIA CRON] Error procesando llamadas"
            )
            return jsonify({
                "error": "Fallo el procesamiento de Sofia"
            }), 500

        # 4. Comprobar que el procesador devolvio
        # el estado de simulacion esperado.
        if (
            not isinstance(resultado, dict)
            or resultado.get("estado") != "simulacion"
        ):
            return jsonify({
                "error": "Procesamiento no confirmado"
            }), 503


        # 4.1. Comprobar consultas que requieren revision.
        # No declarar completado un periodo con consultas
        # que no pudieron clasificarse correctamente.

        consultas_en_revision = resultado.get(
            "consultas_en_revision"
        )

        total_consultas_en_revision = resultado.get(
            "total_consultas_en_revision"
        )

        if (
            not isinstance(consultas_en_revision, list)
            or type(total_consultas_en_revision) is not int
            or total_consultas_en_revision != len(
                consultas_en_revision
            )
        ):
            return jsonify({
                "error": "Resultado de revisiones invalido",
                "escrituras_crm": False,
            }), 503

        if total_consultas_en_revision > 0:

            current_app.logger.warning(
                "[SOFIA CRON] Consultas pendientes de "
                "revision: %s",
                total_consultas_en_revision,
            )

            return jsonify({
                "error": "Existen consultas sin clasificar",
                "recuperacion_requerida": True,
                "consultas_en_revision": (
                    total_consultas_en_revision
                ),
                "escrituras_crm": False,
            }), 503



        # 4.2. Comprobar revisiones del clasificador principal.
        revisiones_generales = resultado.get(
            "revisiones_detectadas"
        )

        total_revisiones_generales = resultado.get(
            "total_revisiones_detectadas"
        )

        if (
            not isinstance(revisiones_generales, list)
            or type(total_revisiones_generales) is not int
            or total_revisiones_generales != len(
                revisiones_generales
            )
        ):
            return jsonify({
                "error": "Resultado de revisiones generales invalido",
                "escrituras_crm": False,
            }), 503

        if total_revisiones_generales > 0:
            current_app.logger.warning(
                "[SOFIA CRON] Llamadas pendientes "
                "de revision general: %s",
                total_revisiones_generales,
            )

            # Continuar con las solicitudes validas.
            # Las revisiones se informan al finalizar.


        # 5. Preparar borradores de Casos.
        # Sin consultar ni modificar Zoho CRM.
        from services.retell_casos_lote import (
            preparar_borradores_consultas,
        )

        # Recuperar consultas generales y postventas.
        consultas = resultado.get("consultas_detectadas")
        postventas = resultado.get("postventas_detectadas")

        if (
            not isinstance(consultas, list)
            or not isinstance(postventas, list)
        ):
            return jsonify({
                "error": "Lista de solicitudes invalida",
                "escrituras_crm": False,
            }), 503

        # Ambas solicitudes comparten el flujo
        # de verificacion y creacion de Casos.
        total_consultas_generales = len(consultas)
        total_postventas = len(postventas)

        consultas = consultas + postventas



        # Consultar primero cuales Casos ya existen.
        # Busquedas agrupadas de solo lectura.
        from services.retell_casos_lote import (
            consultar_consultas_en_lotes,
            planificar_recuperacion_consultas,
        )

        from services.retell_casos import (
            buscar_casos_consulta_por_call_ids,
        )

        from services.sofia.crm_sandbox import (
        obtener_conexion_sandbox,
        )

        try:
            conexion_sandbox = obtener_conexion_sandbox()

            barrido = consultar_consultas_en_lotes(
                consultas,
                consultar_lote=lambda call_ids: buscar_casos_consulta_por_call_ids(
                    call_ids,
                    conexion=conexion_sandbox,
                ),
                tamano_lote=10,
                max_lotes=10,
            )

            if barrido["estado"] != "ok":
                current_app.logger.warning(
                    "[SOFIA CRON] Barrido de Casos "
                    "no completado: %s",
                    barrido["estado"],
                )

                return jsonify({
                    "error": "Busqueda agrupada no completada",
                    "recuperacion_requerida": True,
                    "lotes_consultados": (
                        barrido["lotes_consultados"]
                    ),
                    "escrituras_crm": False,
                }), 503

            # Separar Casos existentes de pendientes.
            # Seleccionar como maximo 30 pendientes.
            plan = planificar_recuperacion_consultas(
                consultas,
                barrido["resultados"],
                max_pendientes=30,
            )

        except Exception:
            current_app.logger.exception(
                "[SOFIA CRON] Error planificando "
                "recuperacion de Casos"
            )

            return jsonify({
                "error": "No se pudo planificar recuperacion",
                "recuperacion_requerida": True,
                "escrituras_crm": False,
            }), 503

        consultas_planificadas = plan["seleccionadas"]


        try:
            borradores = preparar_borradores_consultas(
                consultas_planificadas
            )


        except Exception:
            current_app.logger.exception(
                "[SOFIA CRON] Error preparando Casos"
            )
            return jsonify({
                "error": "No se pudieron preparar Casos"
            }), 500


        # 6. Verificar duplicados en Zoho CRM.
        # Solo consultas de lectura. No crear Casos.
        from services.retell_casos import (
            procesar_creacion_caso_consulta,
            buscar_caso_consulta_por_call_id,
        )
        from services.retell_seguimiento_zoho import (
            buscar_asunto_control_zoho,
        )

        # Interruptor exclusivo para pruebas en Sandbox.
        # Desactivado por defecto.
        escritura_sandbox = (
            os.getenv(
                "SOFIA_SANDBOX_CASES_WRITES_ENABLED",
                "false",
            ).strip().lower() == "true"
        )

        propietario_sandbox = os.getenv(
            "SOFIA_SANDBOX_CASES_OWNER_ID", ""
        ).strip()

        # Exigir autorizacion explicita antes de escribir.
        if escritura_sandbox:
            autorizado = (
                os.getenv(
                    "RETELL_CRM_WRITES_ENABLED", "false"
                ).strip().lower() == "true"
                and os.getenv(
                    "RETELL_CASES_WRITES_ENABLED", "false"
                ).strip().lower() == "true"
                and propietario_sandbox.isascii()
                and propietario_sandbox.isdecimal()
            )

            if not autorizado:
                return jsonify({
                    "error": "Escritura Sandbox no autorizada",
                    "escrituras_crm": False,
                }), 503

        def enviar_caso_sandbox(url, **kwargs):
            destino = (
                "https://sandbox.zohoapis.com"
                "/crm/v8/Cases"
            )

            if url != destino:
                raise RuntimeError(
                    "Destino fuera del Sandbox"
                )

            return requests.post(
                url,
                allow_redirects=False,
                **kwargs,
            )

        resumen_casos = {
            "creacion_simulada": 0,
            "creado": 0,
            "ya_registrado": 0,
            "bloqueado": 0,
        }

        try:
            for consulta in consultas_planificadas:
                decision = procesar_creacion_caso_consulta(
                    consulta,
                    consultar_asunto=lambda modulo, asunto: buscar_asunto_control_zoho(
                        modulo,
                        asunto,
                        conexion=conexion_sandbox,
                    ),
                    consultar_call_id=lambda call_id: buscar_caso_consulta_por_call_id(
                        call_id,
                        conexion=conexion_sandbox,
                    ),
                    simulacion=not escritura_sandbox,
                    propietario_id=(
                        propietario_sandbox
                        if escritura_sandbox else None
                    ),
                    http_post=(
                        enviar_caso_sandbox
                        if escritura_sandbox else None
                    ),
                    obtener_token=(
                        conexion_sandbox["obtener_token"]
                        if escritura_sandbox else None
                    ),
                    crm_base=(
                        "https://sandbox.zohoapis.com/crm/v8"
                        if escritura_sandbox else None
                    ),
                )

                estado = (
                    decision.get("estado")
                    if isinstance(decision, dict)
                    else None
                )

                if estado not in resumen_casos:
                    estado = "bloqueado"

                resumen_casos[estado] += 1

        except Exception:
            current_app.logger.exception(
                "[SOFIA CRON] Error verificando Casos"
            )
            return jsonify({
                "error": "Fallo la verificacion de Casos",
                "escrituras_crm": False,
            }), 503

        # 7. Ante verificaciones fallidas, no
        # considerar exitoso el procesamiento.
        if resumen_casos["bloqueado"] > 0:
            return jsonify({
                "error": "Hay Casos sin verificar",
                "resumen_casos": resumen_casos,
                "escrituras_crm": (
                    resumen_casos["creado"] > 0
                ),
            }), 503


        # 8. Informar el resultado de la simulacion.
        # No marcar solicitudes como recuperadas.

        return jsonify({
            "estado": (
                "sandbox_ejecutado"
                if escritura_sandbox else "simulacion"
            ),
            "procesamiento": (
                "creacion_casos_sandbox"
                if escritura_sandbox
                else "verificacion_simulada"
            ),

            "consultas_detectadas": total_consultas_generales,
            "postventas_detectadas": total_postventas,
            "solicitudes_casos_detectadas": len(consultas),

            "casos_ya_registrados": (
                plan["ya_registradas"]
            ),

            "consultas_pendientes_detectadas": (
                plan["total_pendientes"]
            ),

            "consultas_pendientes_seleccionadas": (
                len(consultas_planificadas)
            ),

            "consultas_pendientes_fuera_de_limite": (
                plan["pendientes_fuera_de_limite"]
            ),

            "lotes_consultados": (
                barrido["lotes_consultados"]
            ),

            "borradores_casos_preparados": len(borradores),

            "resumen_casos": resumen_casos,
            "revisiones_generales": total_revisiones_generales,

            "casos_pendientes_creacion": (
                resumen_casos["creacion_simulada"]
            ),

            "recuperacion_requerida": (
                plan["total_pendientes"] > 0
                or total_revisiones_generales > 0
            ),

            "recuperacion_completada": False,
            "advertencia": (
                "Llamadas pendientes de revision"
                if total_revisiones_generales > 0
                else None
            ),
            "escrituras_crm": resumen_casos["creado"] > 0,
        }), 200
