"""Procesamiento AUTOMATICO de nuevas llamadas de Sofia, opt-in y solo prueba.

Cada cron recupera llamadas en simulacion. Este consumidor se limita a llamadas
nuevas, validadas y marcadas como prueba, con limite de inserciones por ejecucion.
No crea Accounts/Contacts, no reintenta escrituras inciertas, no envia correos a
personas reales. La conversion a operacion comercial real queda pendiente.
"""

from services.sofia.autorizacion_produccion import (
    activo,
    configuracion_automatica,
    llamada_autorizada,
)


def procesar_produccion_automatica(resultado):
    config = configuracion_automatica()
    if config.get("estado") != "autorizado":
        return config
    if not isinstance(resultado, dict) or resultado.get("estado") != "simulacion":
        return {"estado": "bloqueado", "motivo": "simulacion_requerida"}

    raw_deals = resultado.get("cotizaciones_sandbox_candidatas")
    raw_consultas = resultado.get("consultas_detectadas")
    raw_postventas = resultado.get("postventas_detectadas")
    if any(not isinstance(x, list) for x in (raw_deals, raw_consultas, raw_postventas)):
        return {"estado": "bloqueado", "motivo": "listas_invalidas"}

    # Validar lista completa antes de CUALQUIER escritura; evitar la misma llamada
    # en dos modulos o dos entradas de la misma ejecucion.
    candidatos = []
    ids = set()
    for modulo, items in (("Cases", raw_consultas + raw_postventas), ("Deals", raw_deals)):
        if not activo("SOFIA_PROD_CASES_WRITES_ENABLED" if modulo == "Cases" else "SOFIA_PROD_DEALS_WRITES_ENABLED"):
            continue
        for item in items:
            if not isinstance(item, dict):
                return {"estado": "bloqueado", "motivo": "item_invalido"}
            call_id = item.get("call_id")
            fecha = item.get("start_timestamp")
            # Ignorar registros viejos y sin fecha; no asumir la fecha actual.
            if type(fecha) is not int or fecha < config["inicio_ms"]:
                continue
            if not llamada_autorizada(modulo, call_id, fecha):
                return {"estado": "bloqueado", "motivo": "llamada_no_autorizada"}
            if modulo == "Cases" and not (
                item.get("estado") == "candidata_caso"
                and item.get("tipo") in ("consulta", "postventa")
                and item.get("tipo_solicitud") == item.get("tipo")
            ):
                return {"estado": "bloqueado", "motivo": "caso_no_elegible"}
            if call_id in ids:
                return {"estado": "bloqueado", "motivo": "duplicado_en_resultados"}
            ids.add(call_id)
            candidatos.append((fecha, call_id, modulo, item))

    candidatos.sort(key=lambda fila: (fila[0], fila[1]))
    total_pendiente = max(0, len(candidatos) - config["maximo"])
    estados = {
        "Cases": "desactivado" if not activo("SOFIA_PROD_CASES_WRITES_ENABLED") else "sin_nuevas",
        "Deals": "desactivado" if not activo("SOFIA_PROD_DEALS_WRITES_ENABLED") else "sin_nuevas",
        "Cases_email": "desactivado" if not activo("SOFIA_PROD_CASES_MAILS_ENABLED") else "sin_nuevas",
    }
    recuento = {"creados": 0, "ya_registrados": 0, "bloqueados": 0, "resultado_incierto": 0}
    for _, _, modulo, item in candidatos[:config["maximo"]]:
        if modulo == "Cases":
            from services.sofia.registro_casos_produccion import (
                procesar_caso_prueba_desde_clasificacion,
            )
            decision = procesar_caso_prueba_desde_clasificacion(item)
        else:
            from services.sofia.registro_cotizaciones_produccion import (
                registrar_negocio_prueba_produccion,
            )
            decision = registrar_negocio_prueba_produccion(item)
        estado = decision.get("estado") if isinstance(decision, dict) else None
        if estado not in ("creado", "ya_registrado", "bloqueado", "desactivado", "rechazado", "resultado_incierto"):
            estado = "resultado_incierto"
        estados[modulo] = estado
        if estado == "creado":
            recuento["creados"] += 1
        elif estado == "ya_registrado":
            recuento["ya_registrados"] += 1
        elif estado == "resultado_incierto":
            recuento["resultado_incierto"] += 1
        else:
            recuento["bloqueados"] += 1

        # El estado de creación en CRM es la UNICA condicion para notificar.
        # No se envia sobre Casos preexistentes, aun cuando cambie el cron.
        if modulo == "Cases" and estado == "creado":
            try:
                from services.sofia.notificaciones_casos import notificar_caso_creado
                aviso = notificar_caso_creado(decision, item)
                estados["Cases_email"] = aviso.get("estado", "resultado_incierto") if isinstance(aviso, dict) else "resultado_incierto"
            except Exception:
                estados["Cases_email"] = "resultado_incierto"

        # Incertidumbre en un POST: no arriesgar nuevos POST en la misma corrida.
        if estado == "resultado_incierto":
            break

    return {
        "estado": "automatico_pruebas_ejecutado",
        "resultados": estados,
        "recuento": recuento,
        "pendientes_por_continuar": total_pendiente,
    }
