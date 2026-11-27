import os
import requests
from datetime import datetime, timezone

from flask import current_app, jsonify

from services.retell_procesador import procesar_pendientes_sofia
from utils.security import cron_autorizado


def register_sofia_cron_routes(app):


    @app.post("/cron/sofia/comercial/diagnostico-campos")
    def diagnostico_campos_sofia_comercial():
        # Protegido con el secreto habitual del cron; solo GET a Zoho.
        if not cron_autorizado():
            return jsonify({"error": "No autorizado"}), 401
        from services.sofia.metadatos_comerciales import (
            diagnosticar_campos_comerciales,
        )
        resultado = diagnosticar_campos_comerciales()
        return jsonify(resultado), 200 if resultado.get("estado") == "listo" else 409

    @app.post("/cron/sofia/diagnostico-produccion")
    def diagnostico_sofia_produccion():

        if not cron_autorizado():
            return jsonify({"error": "No autorizado"}), 401

        from services.sofia.crm_produccion import (
            obtener_conexion_produccion,
        )

        try:
            conexion = obtener_conexion_produccion()
            token = conexion["obtener_token"]()

            modulos = {
                "Deals": (
                    "id,Retell_Call_ID,"
                    "Registro_de_prueba_Sof_a"
                ),
                "Cases": (
                    "id,Case_Number,ID_de_llamada_Retell,"
                    "Registro_de_prueba_Sof_a"
                ),
            }

            resultados = {}

            for modulo, campos in modulos.items():
                respuesta = conexion["http_get"](
                    conexion["base"] + "/crm/v8/" + modulo,
                    headers={
                        "Authorization":
                            "Zoho-oauthtoken " + token
                    },
                    params={
                        "fields": campos,
                        "per_page": 1,
                    },
                    timeout=20,
                    allow_redirects=False,
                )

                resultados[modulo] = respuesta.status_code


            # Diagnostico de paginacion, sin escrituras.
            for pagina in (1, 2, 10):
                respuesta = conexion["http_get"](
                    conexion["base"] + "/crm/v8/Deals",
                    headers={
                        "Authorization": "Zoho-oauthtoken " + token
                    },
                    params={
                        "fields": "id,Retell_Call_ID,Registro_de_prueba_Sof_a",
                        "page": pagina,
                        "per_page": 200,
                    },
                    timeout=20,
                    allow_redirects=False,
                )
                resultados[f"Deals_pagina_{pagina}"] = respuesta.status_code


            # Revisar paginacion posterior a 2000 registros.
            # La variable respuesta corresponde a la pagina 10.
            if respuesta.status_code == 200:
                info = respuesta.json().get("info") or {}

                for pagina_extra in range(11, 21):
                    if info.get("more_records") is not True:
                        break

                    token_pagina = info.get("next_page_token")

                    if not isinstance(token_pagina, str) or not token_pagina:
                        resultados[f"Deals_pagina_{pagina_extra}"] = "sin_token"
                        break

                    siguiente = conexion["http_get"](
                        conexion["base"] + "/crm/v8/Deals",
                        headers={
                            "Authorization": "Zoho-oauthtoken " + token
                        },
                        params={
                            "fields": "id,Retell_Call_ID,Registro_de_prueba_Sof_a",
                            "per_page": 200,
                            "page_token": token_pagina,
                        },
                        timeout=20,
                        allow_redirects=False,
                    )

                    resultados[f"Deals_pagina_{pagina_extra}"] = siguiente.status_code

                    if siguiente.status_code != 200:
                        break

                    info = siguiente.json().get("info") or {}

            # Diagnosticar busqueda directa por Call ID.
            # Solo lectura, sin mostrar datos del cliente.
            call_id_prueba = os.getenv(
                "SOFIA_PROD_DEALS_ALLOWED_CALL_ID", ""
            ).strip()

            if call_id_prueba.startswith("call_"):
                prueba_busqueda = conexion["http_get"](
                    conexion["base"] + "/crm/v8/Deals/search",
                    headers={
                        "Authorization": "Zoho-oauthtoken " + token
                    },
                    params={
                        "criteria": (
                            "(Retell_Call_ID:equals:"
                            + call_id_prueba + ")"
                        ),
                        "fields": "id,Retell_Call_ID",
                        "per_page": 2,
                    },
                    timeout=20,
                    allow_redirects=False,
                )

                resultados["Deals_busqueda_http"] = (
                    prueba_busqueda.status_code
                )
            correcto = all(
                estado in (200, 204)
                for estado in resultados.values()
            )

            return jsonify({
                "estado": "ok" if correcto else "revision",
                "organizacion": "verificada",
                "modulos": resultados,
                "escrituras_realizadas": False,
            }), 200 if correcto else 503

        except Exception:
            return jsonify({
                "estado": "error_conexion",
                "escrituras_realizadas": False,
            }), 503

    @app.post("/cron/sofia/caso-prueba-produccion")
    def crear_un_caso_prueba_sofia_produccion():
        # Ruta manual y protegida: no modifica el cron de Sandbox.
        if not cron_autorizado():
            return jsonify({"error": "No autorizado"}), 401

        habilitado = (
            os.getenv("SOFIA_PROD_CASES_WRITES_ENABLED", "false")
            .strip().lower() == "true"
        )
        if not habilitado:
            return jsonify({"estado": "desactivado"}), 403

        call_id = os.getenv(
            "SOFIA_PROD_CASES_ALLOWED_CALL_ID", ""
        ).strip()
        agente = os.getenv("RETELL_SOFIA_AGENT_ID", "").strip()
        caracteres_validos = (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz"
            "0123456789_-"
        )
        if (
            not call_id.startswith("call_")
            or len(call_id) > 128
            or any(c not in caracteres_validos for c in call_id)
            or not agente
        ):
            return jsonify({
                "estado": "bloqueado",
                "motivo": "autorizacion_o_agente_invalido",
            }), 503

        try:
            fin_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            inicio_ms = fin_ms - 48 * 60 * 60 * 1000
            resultado = procesar_pendientes_sofia(
                agente,
                simulacion=True,
                inicio_ms=inicio_ms,
                fin_ms=fin_ms,
                incluir_cotizaciones_sandbox=False,
            )
            if (
                not isinstance(resultado, dict)
                or resultado.get("estado") != "simulacion"
            ):
                return jsonify({
                    "estado": "bloqueado",
                    "motivo": "historial_no_confirmado",
                }), 503

            consultas = resultado.get("consultas_detectadas")
            postventas = resultado.get("postventas_detectadas")
            if not isinstance(consultas, list) or not isinstance(postventas, list):
                return jsonify({
                    "estado": "bloqueado",
                    "motivo": "clasificaciones_no_disponibles",
                }), 503

            candidatas = [
                c for c in consultas + postventas
                if isinstance(c, dict) and c.get("call_id") == call_id
            ]
            if len(candidatas) != 1:
                return jsonify({
                    "estado": "no_disponible",
                    "coincidencias": len(candidatas),
                    "motivo": "llamada_no_elegible_o_fuera_de_48h",
                }), 409

            from services.sofia.registro_casos_produccion import (
                procesar_caso_prueba_desde_clasificacion,
            )
            decision = procesar_caso_prueba_desde_clasificacion(
                candidatas[0]
            )
            if not isinstance(decision, dict):
                return jsonify({"estado": "resultado_incierto"}), 503
            estado = decision.get("estado")
            if estado in ("creado", "ya_registrado"):
                return jsonify({
                    "estado": estado,
                    "case_id": decision.get("case_id"),
                    "registro_de_prueba": True,
                }), 200

            return jsonify({
                "estado": estado or "resultado_incierto",
                "motivo": decision.get("motivo", "sin_detalle"),
            }), 503
        except Exception:
            current_app.logger.exception(
                "[SOFIA PROD] No fue posible confirmar el Caso"
            )
            return jsonify({"estado": "resultado_incierto"}), 503

    @app.post("/cron/sofia/cotizacion-prueba-produccion")
    def crear_una_cotizacion_prueba_sofia_produccion():
        # Ruta manual, separada del cron Sandbox.
        if not cron_autorizado():
            return jsonify({"error": "No autorizado"}), 401
        if os.getenv("SOFIA_PROD_DEALS_WRITES_ENABLED", "false").strip().lower() != "true":
            return jsonify({"estado": "desactivado"}), 403

        call_id = os.getenv("SOFIA_PROD_DEALS_ALLOWED_CALL_ID", "").strip()
        agente = os.getenv("RETELL_SOFIA_AGENT_ID", "").strip()
        caracteres_validos = (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz"
            "0123456789_-"
        )
        if (
            not call_id.startswith("call_")
            or len(call_id) > 128
            or any(c not in caracteres_validos for c in call_id)
            or not agente
        ):
            return jsonify({"estado": "bloqueado", "motivo": "autorizacion_invalida"}), 503

        try:
            fin_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            inicio_ms = fin_ms - 48 * 60 * 60 * 1000
            resultado = procesar_pendientes_sofia(
                agente,
                simulacion=True,
                inicio_ms=inicio_ms,
                fin_ms=fin_ms,
                incluir_cotizaciones_sandbox=True,
            )
            if not isinstance(resultado, dict) or resultado.get("estado") != "simulacion":
                return jsonify({"estado": "bloqueado", "motivo": "historial_no_confirmado"}), 503
            candidatas = resultado.get("cotizaciones_sandbox_candidatas")
            if not isinstance(candidatas, list):
                return jsonify({"estado": "bloqueado", "motivo": "cotizaciones_no_disponibles"}), 503
            encontradas = [
                llamada for llamada in candidatas
                if isinstance(llamada, dict)
                and llamada.get("call_id") == call_id
                and llamada.get("agent_id") == agente
            ]
            if len(encontradas) != 1:
                return jsonify({"estado": "no_disponible", "coincidencias": len(encontradas)}), 409

            from services.sofia.registro_cotizaciones_produccion import (
                registrar_negocio_prueba_produccion,
            )
            decision = registrar_negocio_prueba_produccion(encontradas[0])
            estado = decision.get("estado") if isinstance(decision, dict) else None
            if estado in ("creado", "ya_registrado"):
                return jsonify({
                    "estado": estado,
                    "deal_id": decision.get("deal_id"),
                    "registro_de_prueba": decision.get("registro_de_prueba") is True,
                }), 200
            return jsonify({
                "estado": estado or "resultado_incierto",
                "motivo": (decision.get("motivo") if isinstance(decision, dict) else "sin_detalle"),
            }), 503
        except Exception:
            current_app.logger.exception("[SOFIA PROD] Cotizacion prueba no confirmada")
            return jsonify({"estado": "resultado_incierto"}), 503

    @app.post("/cron/sofia/diagnostico-correo")
    def diagnostico_correo_sofia():
        if not cron_autorizado():
            return jsonify({"error": "No autorizado"}), 401

        # El diagnostico exige escrituras y correos apagados.
        for variable in (
            "SOFIA_PROD_CASES_WRITES_ENABLED",
            "SOFIA_PROD_CASES_MAILS_ENABLED",
        ):
            if os.getenv(variable, "false").strip().lower() == "true":
                return jsonify({
                    "estado": "bloqueado",
                    "motivo": "interruptores_activos",
                }), 409

        import re
        from services.sofia.crm_produccion import (
            obtener_conexion_produccion,
        )
        from services.sofia.notificaciones_casos import (
            notificar_caso_creado,
        )

        call_id = os.getenv(
            "SOFIA_PROD_CASES_ALLOWED_CALL_ID", ""
        ).strip()

        if not re.fullmatch(r"call_[A-Za-z0-9_-]{1,123}", call_id):
            return jsonify({
                "estado": "bloqueado",
                "motivo": "call_id_invalido",
            }), 400

        try:
            conexion = obtener_conexion_produccion()
            token = conexion["obtener_token"]()

            respuesta = conexion["http_get"](
                conexion["base"] + "/crm/v8/Cases/search",
                headers={
                    "Authorization": "Zoho-oauthtoken " + token
                },
                params={
                    "criteria": (
                        "(ID_de_llamada_Retell:equals:"
                        + call_id + ")"
                    ),
                    "fields": "id,ID_de_llamada_Retell",
                    "per_page": 2,
                },
                timeout=20,
                allow_redirects=False,
            )

            if respuesta.status_code != 200:
                return jsonify({
                    "estado": "bloqueado",
                    "motivo": "busqueda_caso",
                    "http": respuesta.status_code,
                }), 200

            filas = respuesta.json().get("data")
            if not isinstance(filas, list):
                raise ValueError("Respuesta invalida")

            coincidentes = [
                fila for fila in filas
                if isinstance(fila, dict)
                and fila.get("ID_de_llamada_Retell") == call_id
            ]

            if len(coincidentes) != 1:
                return jsonify({
                    "estado": "bloqueado",
                    "motivo": "caso_no_unico",
                }), 200

            case_id = str(coincidentes[0].get("id") or "")
            if not case_id.isascii() or not case_id.isdecimal():
                raise ValueError("ID invalido")

            from flask import request
            enviar = request.args.get("enviar") == "1"
            if enviar:
                # Sólo la llamada de prueba ya validada, nunca otros Casos.
                if call_id != "call_3f3dc3b18363780b813db3434e7":
                    return jsonify({"estado": "bloqueado", "motivo": "llamada_incorrecta"}), 403
                if os.getenv("SOFIA_PROD_CASES_MAIL_MANUAL_TEST_ENABLED", "false").strip().lower() != "true":
                    return jsonify({"estado": "desactivado"}), 403
                if os.getenv("SOFIA_PROD_CASES_MAIL_REAL_RECIPIENTS_ENABLED", "false").strip().lower() == "true":
                    return jsonify({"estado": "bloqueado", "motivo": "destinatarios_reales_activos"}), 403
                if os.getenv("SOFIA_PROD_CASES_MAIL_TEST_TO", "").strip().lower() != "ederth@selec.cl":
                    return jsonify({"estado": "bloqueado", "motivo": "destinatario_incorrecto"}), 403
                # Bloqueo atomico de repeticion dentro de este despliegue.
                # El disco temporal se borra al redeplegar; dejar la bandera apagada
                # salvo durante el unico intento expresamente autorizado.
                import tempfile
                ruta_marca = os.path.join(
                    tempfile.gettempdir(),
                    "sofia_correo_prueba_call_3f3dc3b18363780b813db3434e7.lock",
                )
                try:
                    fd = os.open(ruta_marca, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    return jsonify({"estado": "bloqueado", "motivo": "intento_ya_realizado"}), 409
                os.close(fd)

            resultado = notificar_caso_creado(
                {"estado": "creado", "case_id": case_id},
                {"call_id": call_id, "tipo_solicitud": "postventa"},
                solo_diagnostico=not enviar,
                envio_manual_prueba=enviar,
            )

            return jsonify({
                "estado": resultado.get("estado"),
                "motivo": resultado.get("motivo"),
                "correos_enviados": 1 if resultado.get("estado") == "enviado" else 0,
                "intento_manual": enviar,
            }), 200

        except Exception:
            return jsonify({
                "estado": "error_diagnostico",
                "correos_enviados": 0,
            }), 503

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
                incluir_cotizaciones_sandbox=True,
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


        # Piloto independiente: apagado por defecto y limitado por Call ID.
        # El cron y los escritores Sandbox permanecen intactos.
        from services.sofia.cron_piloto_produccion import (
            procesar_piloto_produccion,
        )
        try:
            piloto_produccion = procesar_piloto_produccion(resultado)
            if piloto_produccion.get("estado") == "piloto_ejecutado":
                current_app.logger.warning(
                    "[SOFIA PROD PILOTO] Estados: %s",
                    piloto_produccion.get("resultados", {}),
                )
        except Exception:
            current_app.logger.exception(
                "[SOFIA PROD PILOTO] Fallo; Sandbox sigue separado"
            )

        # Modo automatico en CRM PRODUCCION. Se mantiene separado del piloto
        # manual y conserva escritores de prueba hasta aprobar modo real.
        from services.sofia.cron_automatico_produccion import (
            procesar_produccion_automatica,
        )
        try:
            automatico_produccion = procesar_produccion_automatica(resultado)
            if automatico_produccion.get("estado") == "automatico_pruebas_ejecutado":
                current_app.logger.warning(
                    "[SOFIA PROD AUTO TEST] Estados: %s Recuento: %s Pendientes: %s",
                    automatico_produccion.get("resultados", {}),
                    automatico_produccion.get("recuento", {}),
                    automatico_produccion.get("pendientes_por_continuar", 0),
                )
            elif automatico_produccion.get("estado") == "bloqueado":
                current_app.logger.warning(
                    "[SOFIA PROD AUTO TEST] Bloqueado: %s",
                    automatico_produccion.get("motivo", "sin_detalle"),
                )
        except Exception:
            current_app.logger.exception("[SOFIA PROD AUTO TEST] Fallo; no reintentar escrituras inciertas")

        # Modo comercial permanente: independiente del piloto, apagado por
        # defecto y con preflight de metadatos/llaves unicas de Zoho.
        from services.sofia.cron_comercial_produccion import procesar_cron_comercial
        try:
            comercial = procesar_cron_comercial(resultado)
            candidatas_diag = resultado.get(
                "cotizaciones_sandbox_candidatas", []
            )
            if not isinstance(candidatas_diag, list):
                candidatas_diag = []
                muestra = [
                {
                    "id_final": str(c.get("call_id", ""))[-6:],
                    "fecha": c.get("start_timestamp"),
                    "tipo_fecha": type(
                        c.get("start_timestamp")
                    ).__name__,
                }
                for c in candidatas_diag
                if isinstance(c, dict)
            ]

            revisiones = resultado.get("revisiones_detectadas", [])
            if not isinstance(revisiones, list):
                revisiones = []

            motivos = [
                {
                    "id_final": str(r.get("call_id", ""))[-6:],
                    "motivo": r.get("motivo"),
                    "faltantes": r.get("faltantes"),
                }
                for r in revisiones
                if isinstance(r, dict)
            ]

            current_app.logger.warning(
                "[SOFIA DIAG DETALLE] candidatas=%s revisiones=%s",
                muestra,
                motivos,
            )

            inicio_diag = os.getenv(
                "SOFIA_PROD_COMMERCIAL_START_MS", ""
            )

            elegibles_diag = sum(
                1 for llamada in candidatas_diag
                if isinstance(llamada, dict)
                and isinstance(llamada.get("start_timestamp"), int)
                and inicio_diag.isdecimal()
                and llamada["start_timestamp"] >= int(inicio_diag)
            )

            current_app.logger.warning(
                "[SOFIA DIAGNOSTICO COMERCIAL] "
                "estado=%s candidatas=%s posteriores_inicio=%s "
                "cron_habilitado=%s",
                comercial.get("estado"),
                len(candidatas_diag),
                elegibles_diag,
                os.getenv(
                    "SOFIA_PROD_COMMERCIAL_CRON_ENABLED",
                    "false"
                ).lower() == "true",
            )
            if comercial.get("estado") == "comercial_ejecutado":
                current_app.logger.warning(
                    "[SOFIA PROD COMERCIAL] Recuento: %s Correos: %s Pendientes: %s",
                    comercial.get("recuento", {}),
                    comercial.get("correos", {}),
                    comercial.get("pendientes_por_continuar", 0),
                )
            elif comercial.get("estado") == "bloqueado":
                current_app.logger.warning(
                    "[SOFIA PROD COMERCIAL] Bloqueado: %s",
                    comercial.get("motivo", "sin_detalle"),
                )
        except Exception:
            current_app.logger.exception(
                "[SOFIA PROD COMERCIAL] Fallo sin reintento automatico"
            )

        # 5. Cotizaciones Sandbox independientes de Casos.
        # El procesador antiguo permanece SIEMPRE en simulacion.
        from services.sofia.cron_cotizaciones_sandbox import (
            procesar_cotizaciones_cron_sandbox,
        )
        from services.sofia.crm_sandbox import obtener_conexion_sandbox

        conexion_sandbox = obtener_conexion_sandbox()

        candidatas_cotizaciones = resultado.get(
            "cotizaciones_sandbox_candidatas"
        )
        if not isinstance(candidatas_cotizaciones, list):
            return jsonify({
                "error": "Llamadas de cotizacion no disponibles",
                "escrituras_crm": False,
            }), 503

        resumen_cotizaciones = procesar_cotizaciones_cron_sandbox(
            candidatas_cotizaciones,
            agente,
            conexion=conexion_sandbox,
            http_post=requests.post,
        )

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
                "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
            }), 503

        if total_consultas_en_revision > 0:
            # Una consulta incompleta NO bloquea una cotizacion valida.
            # Sigue informada como pendiente de revision, sin descartarla.
            current_app.logger.warning(
                "[SOFIA CRON] Consultas pendientes de "
                "revision: %s",
                total_consultas_en_revision,
            )

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
                "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
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
                "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
            }), 503

        # Ambas solicitudes comparten el flujo
        # de verificacion y creacion de Casos.
        total_consultas_generales = len(consultas)
        total_postventas = len(postventas)

        consultas = consultas + postventas

        # Modo automatico: solo postventas previamente validadas.
        # Desactivado por defecto y limitado a Zoho Sandbox.
        postventas_auto = (
            os.getenv(
                "SOFIA_SANDBOX_POSTVENTAS_AUTO_ENABLED", "false"
            ).strip().lower() == "true"
        )

        # Automatizacion de consultas generales en Sandbox.
        # Desactivada por defecto.
        consultas_auto = (
            os.getenv(
                "SOFIA_SANDBOX_CONSULTAS_AUTO_ENABLED", "false"
            ).strip().lower() == "true"
        )


        escritura_casos_sandbox = (
            os.getenv(
                "SOFIA_SANDBOX_CASES_WRITES_ENABLED", "false"
            ).strip().lower() == "true"
        )

        if escritura_casos_sandbox and (postventas_auto or consultas_auto):
            from services.sofia.seleccion_postventas_auto import (
                seleccionar_postventas_automaticas,
            )

            try:
                solicitudes_automaticas = []

                # Opcion 2: postventas previamente validadas.
                if postventas_auto:
                    solicitudes_automaticas.extend(
                        seleccionar_postventas_automaticas(postventas)
                    )

                # Opcion 3: consultas generales candidatas.
                # Su validacion final se hara despues
                # de comprobar los duplicados en CRM.
                if consultas_auto:
                    solicitudes_automaticas.extend(
                        consulta
                        for consulta in consultas
                        if isinstance(consulta, dict)
                        and consulta.get("tipo") == "consulta"
                    )

                consultas = solicitudes_automaticas

            except ValueError:
                return jsonify({
                    "error": "Seleccion automatica de Casos invalida",
                    "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
                }), 503


        # Prueba controlada: procesar exclusivamente
        # la llamada autorizada cuando se habiliten
        # las escrituras de Casos en Sandbox.
        if escritura_casos_sandbox and not (postventas_auto or consultas_auto):
            call_id_prueba = os.getenv(
                "SOFIA_SANDBOX_CASES_ALLOWED_CALL_ID",
                "",
            ).strip()

            coincidencias = [
                consulta
                for consulta in consultas
                if isinstance(consulta, dict)
                and consulta.get("call_id") == call_id_prueba
            ]

            # Exigir exactamente una llamada candidata.
            if len(coincidencias) != 1:
                return jsonify({
                    "error": "Llamada de prueba no disponible como Caso",
                    "escrituras_crm": (
                        resumen_cotizaciones["creadas"] > 0
                    ),
                }), 503

            consultas = coincidencias


        # Consultar primero cuales Casos ya existen.
        # Busquedas agrupadas de solo lectura.
        from services.retell_casos_lote import (
            consultar_consultas_en_lotes,
            planificar_recuperacion_consultas,
        )

        from services.retell_casos import (
            buscar_casos_consulta_por_call_ids,
        )

        try:
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
                    "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
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
                "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
            }), 503

        consultas_planificadas = plan["seleccionadas"]
        postventas_auto_pendientes_por_continuar = 0
        consultas_auto_pendientes_por_continuar = 0

        # Procesamiento automatico de Casos en Sandbox.
        # Primero verificar duplicados; luego aplicar fechas
        # y limites independientes para cada tipo.
        if escritura_casos_sandbox and (postventas_auto or consultas_auto):
            from services.sofia.seleccion_postventas_auto import (
                seleccionar_postventas_lote_seguro,
            )
            from services.sofia.seleccion_consultas_auto import (
                seleccionar_consultas_lote_seguro,
            )

            try:
                pendientes_auto = [
                    solicitud
                    for solicitud in consultas
                    if barrido["resultados"][
                        solicitud["call_id"]
                    ]["estado"] == "no_encontrado"
                ]

                consultas_planificadas = []

                # Opcion 2: Postventas.
                if postventas_auto:
                    fecha_postventas = os.getenv(
                        "SOFIA_SANDBOX_POSTVENTAS_AUTO_DESDE_MS",
                        "",
                    ).strip()

                    if (
                        not fecha_postventas.isascii()
                        or not fecha_postventas.isdecimal()
                    ):
                        raise ValueError("Fecha postventas invalida")

                    lote_postventas = seleccionar_postventas_lote_seguro(
                        [
                            s for s in pendientes_auto
                            if s.get("tipo") == "postventa"
                        ],
                        inicio_minimo_ms=int(fecha_postventas),
                        max_por_ejecucion=3,
                    )

                    consultas_planificadas.extend(
                        lote_postventas["seleccionadas"]
                    )

                    postventas_auto_pendientes_por_continuar = (
                        lote_postventas["pendientes_por_continuar"]
                    )

                # Opcion 3: Consultas generales.
                if consultas_auto:
                    fecha_consultas = os.getenv(
                        "SOFIA_SANDBOX_CONSULTAS_AUTO_DESDE_MS",
                        "",
                    ).strip()

                    if (
                        not fecha_consultas.isascii()
                        or not fecha_consultas.isdecimal()
                    ):
                        raise ValueError("Fecha consultas invalida")

                    lote_consultas = seleccionar_consultas_lote_seguro(
                        [
                            s for s in pendientes_auto
                            if s.get("tipo") == "consulta"
                        ],
                        inicio_minimo_ms=int(fecha_consultas),
                        max_por_ejecucion=3,
                    )

                    consultas_planificadas.extend(
                        lote_consultas["seleccionadas"]
                    )

                    consultas_auto_pendientes_por_continuar = (
                        lote_consultas["pendientes_por_continuar"]
                    )

                consultas_planificadas.sort(
                    key=lambda s: (
                        s["start_timestamp"],
                        s["call_id"],
                    )
                )

            except (ValueError, KeyError, TypeError):
                return jsonify({
                    "error": "Seleccion automatica de Casos requiere revision",
                    "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
                }), 503

        # El primer despliegue de Casos usa una sola llamada autorizada.
        # Se implementara modo automatico tras validar la idempotencia.
        casos_escritura_habilitada = (
            os.getenv(
                "SOFIA_SANDBOX_CASES_WRITES_ENABLED", "false"
            ).strip().lower() == "true"
        )
        if casos_escritura_habilitada and not (postventas_auto or consultas_auto):
            call_id_autorizado = os.getenv(
                "SOFIA_SANDBOX_CASES_ALLOWED_CALL_ID", ""
            ).strip()
            if (
                not call_id_autorizado
                or not call_id_autorizado.startswith("call_")
                or len(call_id_autorizado) > 128
                or any(
                    c not in (
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "abcdefghijklmnopqrstuvwxyz"
                        "0123456789_-"
                    ) for c in call_id_autorizado
                )
            ):
                return jsonify({
                    "error": "Casos Sandbox: falta una llamada autorizada",
                    "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
                }), 503
            consultas_planificadas = [
                c for c in consultas_planificadas
                if isinstance(c, dict)
                and c.get("call_id") == call_id_autorizado
            ][:1]

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

        # Autorizacion exclusiva de Casos Sandbox: nunca depender
        # de activar el escritor antiguo del CRM de produccion.
        if escritura_sandbox:
            autorizado = (
                propietario_sandbox.isascii()
                and propietario_sandbox.isdecimal()
            )

            if not autorizado:
                return jsonify({
                    "error": "Escritura Sandbox no autorizada",
                    "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
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
                    sandbox_cases_writes_enabled=escritura_sandbox,
                )

                estado = (
                    decision.get("estado")
                    if isinstance(decision, dict)
                    else None
                )

                if estado not in resumen_casos:
                    estado = "bloqueado"

                # Una escritura real nunca debe terminar
                # contabilizada como simulacion.
                if escritura_sandbox and estado == "creacion_simulada":
                    estado = "bloqueado"

                resumen_casos[estado] += 1

                # Detener el lote ante cualquier resultado
                # no confirmado. No intentar otras inserciones.
                if estado == "bloqueado":
                    break

        except Exception:
            current_app.logger.exception(
                "[SOFIA CRON] Error verificando Casos"
            )
            return jsonify({
                "error": "Fallo la verificacion de Casos",
                "escrituras_crm": resumen_cotizaciones["creadas"] > 0,
            }), 503

        # 7. Ante verificaciones fallidas, no
        # considerar exitoso el procesamiento.
        if resumen_casos["bloqueado"] > 0:
            return jsonify({
                "error": "Hay Casos sin verificar",
                "resumen_casos": resumen_casos,
                "escrituras_crm": (
                    resumen_casos["creado"] > 0
                    or resumen_cotizaciones["creadas"] > 0
                ),
            }), 503


        if resumen_cotizaciones["estado"] in ("bloqueado", "parcial"):
            return jsonify({
                "error": "Cotizaciones Sandbox requieren revision",
                "resumen_cotizaciones": resumen_cotizaciones,
                "resumen_casos": resumen_casos,
                "escrituras_crm": (
                    resumen_casos["creado"] > 0
                    or resumen_cotizaciones["creadas"] > 0
                ),
            }), 503

        # 9. Informar los dos flujos sin revelar datos del cliente.
        return jsonify({
            "estado": (
                "sandbox_ejecutado"
                if escritura_sandbox or resumen_cotizaciones["estado"] == "sandbox_habilitado"
                else "simulacion"
            ),
            "procesamiento": (
                "escritura_sandbox_controlada"
                if escritura_sandbox or resumen_cotizaciones["estado"] == "sandbox_habilitado"
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
            "postventas_auto_pendientes_por_continuar": postventas_auto_pendientes_por_continuar,
            "consultas_auto_pendientes_por_continuar": consultas_auto_pendientes_por_continuar,

            "resumen_casos": resumen_casos,
            "revisiones_generales": total_revisiones_generales,
            "consultas_en_revision": total_consultas_en_revision,

            "casos_pendientes_creacion": (
                resumen_casos["creacion_simulada"]
            ),

            "recuperacion_requerida": (
                plan["total_pendientes"] > 0
                or total_revisiones_generales > 0
                or total_consultas_en_revision > 0
            ),

            "recuperacion_completada": False,
            "advertencia": (
                "Llamadas pendientes de revision"
                if total_revisiones_generales > 0
                or total_consultas_en_revision > 0
                else None
            ),
            "resumen_cotizaciones": resumen_cotizaciones,
            "escrituras_crm": (
                resumen_casos["creado"] > 0
                or resumen_cotizaciones["creadas"] > 0
            ),
        }), 200
