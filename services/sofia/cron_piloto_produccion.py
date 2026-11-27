"""Piloto opt-in del cron para probar los escritores de produccion.

NO habilita procesamiento masivo. Solo procesa IDs autorizados de prueba,
con tres interruptores independientes y sin alterar Sandbox.
"""
import os
import re


def _activo(nombre):
    return os.getenv(nombre, "false").strip().lower() == "true"


def _valido(call_id):
    return isinstance(call_id, str) and re.fullmatch(
        r"call_[A-Za-z0-9_-]{1,123}", call_id
    ) is not None


def procesar_piloto_produccion(resultado):
    """Usa solo clasificaciones ya recuperadas; nunca llama Retell otra vez.

    No realiza ninguna accion si el interruptor piloto esta apagado.
    Los escritores mantienen sus propios controles de ID, marca y duplicados.
    """
    if not _activo("SOFIA_PROD_CRON_PILOT_ENABLED"):
        return {"estado": "desactivado"}

    if not isinstance(resultado, dict) or resultado.get("estado") != "simulacion":
        return {"estado": "bloqueado", "motivo": "resultado_invalido"}

    estados = {}
    configuraciones = (
        (
            "Deals", "SOFIA_PROD_DEALS_WRITES_ENABLED",
            "SOFIA_PROD_DEALS_ALLOWED_CALL_ID", "cotizaciones_sandbox_candidatas",
        ),
        (
            "Cases", "SOFIA_PROD_CASES_WRITES_ENABLED",
            "SOFIA_PROD_CASES_ALLOWED_CALL_ID", None,
        ),
    )

    for modulo, variable_escritura, variable_id, nombre_lista in configuraciones:
        if not _activo(variable_escritura):
            estados[modulo] = "desactivado"
            continue

        permitido = os.getenv(variable_id, "").strip()
        if not _valido(permitido):
            estados[modulo] = "sin_llamada_autorizada"
            continue

        if modulo == "Cases":
            consultas = resultado.get("consultas_detectadas")
            postventas = resultado.get("postventas_detectadas")
            if not isinstance(consultas, list) or not isinstance(postventas, list):
                estados[modulo] = "listas_invalidas"
                continue
            candidatas = consultas + postventas
        else:
            candidatas = resultado.get(nombre_lista)
            if not isinstance(candidatas, list):
                estados[modulo] = "lista_invalida"
                continue

        coincidencias = [
            item for item in candidatas
            if isinstance(item, dict) and item.get("call_id") == permitido
        ]
        if len(coincidencias) != 1:
            estados[modulo] = (
                "llamada_no_disponible" if not coincidencias else "duplicado_en_historial"
            )
            continue

        # Los escritores verifican otra vez el mismo ID autorizado.
        if modulo == "Deals":
            from services.sofia.registro_cotizaciones_produccion import (
                registrar_negocio_prueba_produccion,
            )
            decision = registrar_negocio_prueba_produccion(coincidencias[0])
        else:
            from services.sofia.registro_casos_produccion import (
                procesar_caso_prueba_desde_clasificacion,
            )
            decision = procesar_caso_prueba_desde_clasificacion(coincidencias[0])

        estado = decision.get("estado") if isinstance(decision, dict) else None
        estados[modulo] = estado if estado in (
            "creado", "ya_registrado", "desactivado", "bloqueado",
            "resultado_incierto", "rechazado",
        ) else "resultado_incierto"

        # Notificar solo en el instante de crear un Caso NUEVO.
        # Un ya_registrado nunca reenvia correo, incluso en siguientes cron.
        if modulo == "Cases" and estado == "creado":
            try:
                from services.sofia.notificaciones_casos import notificar_caso_creado
                aviso = notificar_caso_creado(decision, coincidencias[0])
                estados["Cases_email"] = (
                    aviso.get("estado", "resultado_incierto")
                    if isinstance(aviso, dict)
                    else "resultado_incierto"
                )
            except Exception:
                estados["Cases_email"] = "resultado_incierto"

    return {"estado": "piloto_ejecutado", "resultados": estados}
