"""Despacho comercial real de Sofía. INACTIVO POR DEFECTO.

No permite escritura sin: consentimiento mediante flags, cutoff, datos válidos,
metadatos de Zoho (incluidas claves únicas) y bloqueo de modos piloto. El
escritor vuelve a verificar duplicados en CRM antes de cada POST.
"""
import os
import re

from services.sofia.metadatos_comerciales import diagnosticar_campos_comerciales
from services.sofia.registro_negocios_comerciales import _configuracion, registrar_negocio_comercial

_ID = re.compile(r"call_[A-Za-z0-9_-]{1,123}\Z")


def _activo(nombre):
    return os.getenv(nombre, "false").strip().lower() == "true"


def procesar_cron_comercial(resultado, *, diagnosticar=None, escribir=None, notificar=None):
    if not _activo("SOFIA_PROD_COMMERCIAL_CRON_ENABLED"):
        return {"estado": "desactivado"}
    cfg = _configuracion()
    if cfg.get("estado") != "autorizado":
        return cfg
    if not isinstance(resultado, dict) or resultado.get("estado") != "simulacion":
        return {"estado": "bloqueado", "motivo": "resultado_invalido"}
    limite = os.getenv("SOFIA_PROD_COMMERCIAL_MAX_PER_RUN", "1").strip()
    if not re.fullmatch(r"[1-5]", limite):
        return {"estado": "bloqueado", "motivo": "limite_invalido"}
    candidatas = resultado.get("cotizaciones_sandbox_candidatas")
    if not isinstance(candidatas, list):
        return {"estado": "bloqueado", "motivo": "candidatas_invalidas"}

    # Validar todo antes de cualquier escritura; nunca tomar fecha del servidor
    # como reemplazo de una fecha de llamada ausente.
    lista, vistos = [], set()
    for item in candidatas:
        if not isinstance(item, dict):
            return {"estado": "bloqueado", "motivo": "candidata_invalida"}
        ts, call_id = item.get("start_timestamp"), item.get("call_id")
        if type(ts) is not int or ts < cfg["inicio"]:
            continue
        if (ts > cfg["ahora"] + 300000 or not isinstance(call_id, str)
                or _ID.fullmatch(call_id) is None):
            return {"estado": "bloqueado", "motivo": "identificador_invalido"}
        if call_id in vistos:
            return {"estado": "bloqueado", "motivo": "duplicado_en_lote"}
        vistos.add(call_id)
        lista.append((ts, call_id, item))
    if not lista:
        return {"estado": "comercial_sin_nuevas", "recuento": {"creados": 0, "ya_registrados": 0}}

    verificar = diagnosticar if diagnosticar is not None else diagnosticar_campos_comerciales
    try:
        preflight = verificar()
    except Exception:
        return {"estado": "bloqueado", "motivo": "metadatos_inconclusos"}
    if not isinstance(preflight, dict) or preflight.get("estado") != "listo":
        return {"estado": "bloqueado", "motivo": "metadatos_no_listos"}

    escritor = escribir if escribir is not None else registrar_negocio_comercial
    lista.sort(key=lambda x: (x[0], x[1]))
    recuento = {"creados": 0, "ya_registrados": 0, "bloqueados": 0,
                "rechazados": 0, "resultado_incierto": 0}
    escrituras = 0
    pendientes = 0
    correos = {"enviados": 0, "bloqueados": 0, "resultado_incierto": 0}
    for indice, (_, _, llamada) in enumerate(lista):
        if escrituras >= int(limite):
            pendientes = len(lista) - indice
            break
        try:
            decision = escritor(llamada, autorizar=True)
            estado = decision.get("estado") if isinstance(decision, dict) else None
        except Exception:
            estado = "resultado_incierto"
        if estado == "creado":
            recuento["creados"] += 1
            escrituras += 1
            try:
                if notificar is None:
                    from services.sofia.notificaciones_negocios_comerciales import (
                        notificar_negocio_comercial_creado,
                    )
                    aviso = notificar_negocio_comercial_creado(decision, llamada)
                else:
                    aviso = notificar(decision, llamada)
                estado_correo = aviso.get("estado") if isinstance(aviso, dict) else "resultado_incierto"
            except Exception:
                estado_correo = "resultado_incierto"
            if estado_correo == "enviado":
                correos["enviados"] += 1
            elif estado_correo == "resultado_incierto":
                correos["resultado_incierto"] += 1
            elif estado_correo != "desactivado":
                correos["bloqueados"] += 1
        elif estado == "ya_registrado":
            recuento["ya_registrados"] += 1
        elif estado == "rechazado":
            recuento["rechazados"] += 1
            escrituras += 1
        elif estado == "resultado_incierto":
            recuento["resultado_incierto"] += 1
            break  # Nunca reintentar automáticamente un resultado incierto.
        else:
            recuento["bloqueados"] += 1
            escrituras += 1
    return {"estado": "comercial_ejecutado", "recuento": recuento,
            "correos": correos, "pendientes_por_continuar": pendientes}
